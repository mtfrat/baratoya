"""Casos chicos de la clave de super_cadenas. No pega a la red."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import super_cadenas as sc


def _fila(
    nombre: str,
    marca: str,
    precio: float,
    tid: str,
    *,
    tienda: str | None = None,
    presentacion: str = "",
    ean: str = "",
    url: str = "",
    pc: bool = False,
    pc_id: str = "",
) -> dict:
    if pc:
        return {
            "nombre": nombre,
            "marca": marca,
            "presentacion": presentacion,
            "precioMin": precio,
            "id": pc_id,
        }
    return {
        "nombre": nombre,
        "marca": marca,
        "presentacion": presentacion,
        "precio": precio,
        "tienda": tienda or tid,
        "tienda_id": tid,
        "url": url or f"https://example.test/{tid}",
        "ean": ean,
    }


def _nombres(grupos: list[dict]) -> list[str]:
    return [g["nombre"] for g in grupos]


class MatchTests(unittest.TestCase):
    def test_yerba_no_es_bebida_con_yerba(self) -> None:
        grupos = sc.agrupar_mismo_producto(
            "yerba",
            [
                _fila("Yerba Mate Playadito 1 kg", "Playadito", 3969, "dia", presentacion="1 kg"),
                _fila(
                    "Bebida gasificada con yerba",
                    "Otra",
                    1500,
                    "masonline",
                    presentacion="354 ml",
                ),
            ],
        )
        self.assertEqual(len(grupos), 1)
        self.assertIn("Playadito", grupos[0]["nombre"])
        self.assertNotIn("bebida", grupos[0]["nombre"].casefold())

    def test_1kg_y_1000g_mismo_grupo(self) -> None:
        grupos = sc.agrupar_mismo_producto(
            "yerba playadito",
            [
                _fila("Yerba Mate Playadito 1 kg", "Playadito", 3969, "dia", presentacion="1 kg"),
                _fila(
                    "Yerba Mate Playadito 1000 g",
                    "PLAYADITO",
                    4100,
                    "masonline",
                    presentacion="1000 g",
                ),
            ],
        )
        self.assertEqual(len(grupos), 1)
        self.assertEqual(len(grupos[0]["ofertas"]), 2)
        self.assertEqual({o["tienda_id"] for o in grupos[0]["ofertas"]}, {"dia", "masonline"})

    def test_500g_no_va_con_1kg(self) -> None:
        grupos = sc.agrupar_mismo_producto(
            "yerba playadito",
            [
                _fila("Yerba Mate Playadito 500 g", "Playadito", 2200, "dia", presentacion="500 g"),
                _fila("Yerba Mate Playadito 1 kg", "Playadito", 3969, "masonline", presentacion="1 kg"),
            ],
        )
        self.assertEqual(len(grupos), 2)

    def test_balde_2_porciento(self) -> None:
        juntos = sc.agrupar_mismo_producto(
            "yerba playadito",
            [
                _fila("Yerba Mate Playadito 1000 g", "Playadito", 3969, "dia", presentacion="1000 g"),
                _fila("Yerba Mate Playadito 980 g", "Playadito", 3900, "masonline", presentacion="980 g"),
            ],
        )
        self.assertEqual(len(juntos), 1)
        lejos = sc.agrupar_mismo_producto(
            "yerba playadito",
            [
                _fila("Yerba Mate Playadito 1000 g", "Playadito", 3969, "dia", presentacion="1000 g"),
                _fila("Yerba Mate Playadito 970 g", "Playadito", 3800, "masonline", presentacion="970 g"),
            ],
        )
        self.assertEqual(len(lejos), 2)

    def test_pack_no_es_unidad(self) -> None:
        grupos = sc.agrupar_mismo_producto(
            "yerba playadito",
            [
                _fila("Yerba Mate Playadito 1 kg", "Playadito", 3969, "dia", presentacion="1 kg"),
                _fila("Yerba Mate Playadito pack x3", "Playadito", 11000, "masonline"),
            ],
        )
        self.assertEqual(len(grupos), 2)
        pack = next(g for g in grupos if "pack" in g["tamano"])
        self.assertIsNone(pack["pum"])
        self.assertEqual(pack["pum_nota"], "precio por kg/L no disponible")
        self.assertEqual(pack["precio"], 11000)

    def test_pack_con_contenido_tiene_unitario(self) -> None:
        grupos = sc.agrupar_mismo_producto(
            "agua",
            [
                _fila("Agua Villavicencio 1 L", "Villavicencio", 900, "dia", presentacion="1 L"),
                _fila("Agua Villavicencio 6 x 1 L", "Villavicencio", 6000, "masonline"),
            ],
        )
        self.assertEqual(len(grupos), 2)
        pack = next(g for g in grupos if g["precio"] == 6000)
        self.assertEqual(pack["tamano"], "6 x 1 L")
        self.assertAlmostEqual(pack["pum"], 1000.0)
        self.assertEqual(pack["pum_unidad"], "L")
        self.assertEqual(pack["precio"], 6000)

    def test_sin_contenido_no_hay_ars_por_kg(self) -> None:
        grupos = sc.agrupar_mismo_producto(
            "yerba playadito",
            [_fila("Yerba Mate Playadito 6 un", "Playadito", 9000, "dia")],
        )
        self.assertEqual(len(grupos), 1)
        self.assertIsNone(grupos[0]["pum"])
        self.assertEqual(grupos[0]["pum_nota"], "precio por kg/L no disponible")

    def test_dos_ean_distintos_no_se_juntan(self) -> None:
        grupos = sc.agrupar_mismo_producto(
            "yerba playadito",
            [
                _fila(
                    "Yerba Mate Playadito 1 kg",
                    "Playadito",
                    3969,
                    "dia",
                    presentacion="1 kg",
                    ean="7790080012345",
                ),
                _fila(
                    "Yerba Mate Playadito 1 kg",
                    "Playadito",
                    4100,
                    "masonline",
                    presentacion="1 kg",
                    ean="7790080099999",
                ),
                _fila(
                    "Yerba Mate Playadito 1 kg",
                    "Playadito",
                    4000,
                    "carrefour",
                    presentacion="1 kg",
                ),
            ],
        )
        self.assertEqual(len(grupos), 3)
        for g in grupos:
            eans = {o["ean"] for o in g["ofertas"] if o["ean"]}
            self.assertLessEqual(len(eans), 1)

    def test_mismo_ean_dia_y_precios_claros(self) -> None:
        ean = "7790070509123"
        grupos = sc.agrupar_mismo_producto(
            "yerba chamigo",
            [
                _fila(
                    "Yerba Mate Chamigo 500 Gr",
                    "CHAMIGO",
                    2000,
                    "precios_claros",
                    presentacion="500 gr",
                    pc=True,
                    pc_id=ean,
                ),
                _fila(
                    "Yerba Chamigo tradicional 500 gr",
                    "OTRA",
                    1950,
                    "dia",
                    tienda="Día",
                    presentacion="500 gr",
                    ean=ean,
                    url="https://diaonline.supermercadosdia.com.ar/yerba-mate-chamigo-500-gr-53413/p",
                ),
            ],
        )
        self.assertEqual(len(grupos), 1)
        self.assertEqual(grupos[0]["ean"], ean)
        self.assertEqual({o["tienda_id"] for o in grupos[0]["ofertas"]}, {"dia", "precios_claros"})
        self.assertEqual(grupos[0]["precio"], 1950)

    def test_sin_ean_se_junta_por_marca_tipo_balde(self) -> None:
        grupos = sc.agrupar_mismo_producto(
            "yerba playadito",
            [
                _fila(
                    "Yerba Mate Playadito 1 kg",
                    "Playadito",
                    3969,
                    "dia",
                    presentacion="1 kg",
                    ean="7790080011111",
                ),
                _fila(
                    "Yerba Mate Playadito 1 kg",
                    "Playadito",
                    4200,
                    "masonline",
                    presentacion="1 kg",
                ),
            ],
        )
        self.assertEqual(len(grupos), 1)
        self.assertEqual(len(grupos[0]["ofertas"]), 2)

    def test_marca_vacia_no_cruza_con_marca(self) -> None:
        grupos = sc.agrupar_mismo_producto(
            "yerba",
            [
                _fila("Yerba Mate 1 kg", "", 3000, "dia", presentacion="1 kg"),
                _fila("Yerba Mate 1 kg", "Playadito", 3969, "masonline", presentacion="1 kg"),
            ],
        )
        self.assertEqual(len(grupos), 2)

    def test_precio_grande_no_usa_promo_total(self) -> None:
        def fake(tienda_id, nombre, precio, hoy=None, ya_descuento=False):
            total = round(float(precio) * 0.8, 2)
            return {
                "total": total,
                "promo": {
                    "aplicada": True,
                    "banco": "Banco",
                    "descuento": "20%",
                    "motivo": "",
                    "total": total,
                    "canal": "online",
                    "tope": "1000",
                },
                "promos": [],
            }

        with patch.object(sc, "aplicar_oferta", fake):
            grupos = sc.agrupar_mismo_producto(
                "yerba playadito",
                [
                    _fila("Yerba Mate Playadito 1 kg", "Playadito", 3969, "dia", presentacion="1 kg"),
                    _fila(
                        "Yerba Mate Playadito 1 kg",
                        "Playadito",
                        4500,
                        "masonline",
                        presentacion="1 kg",
                    ),
                ],
            )
        self.assertEqual(len(grupos), 1)
        self.assertEqual(grupos[0]["precio"], 3969)
        self.assertEqual(grupos[0]["mas_barato"], ["dia"])
        barato = next(o for o in grupos[0]["ofertas"] if o["barato"])
        self.assertEqual(barato["precio"], 3969)
        self.assertNotEqual(barato["total"], barato["precio"])
        self.assertTrue(all(o["barato"] == (o["precio"] == 3969) for o in grupos[0]["ofertas"]))

    def test_clave_textual(self) -> None:
        p = _fila("Yerba Mate Playadito 1 kg", "Playadito", 3969, "dia", presentacion="1 kg")
        size, pack = sc._medida_de(p)
        self.assertEqual(sc._clave(p, size, pack), ("PLAYADITO", "yerba", ("g", 1000), ("unit",)))
        bebida = _fila("Bebida gasificada con yerba", "Otra", 1500, "dia")
        self.assertEqual(sc._tipo_de(bebida), "")
        self.assertEqual(sc._tipo_de(p), "yerba")

    def test_playadito_suave_1kg_sin_ean_va_al_grupo_principal(self) -> None:
        # Vivo 4 oct 2026: La Anonima (sin EAN) quedaba sola con su "La mas barata".
        main = "7793704000928"
        otro = "7793704000225"
        grupos = sc.agrupar_mismo_producto(
            "yerba playadito",
            [
                _fila("Yerba Mate Suave Playadito 1kg", "Playadito", 3969, "masonline", ean=main),
                _fila("Yerba Mate Playadito Suave 1 Kg.", "PLAYADITO", 5208, "dia", ean=main),
                _fila("Yerba mate Playadito suave con palo 1 kg.", "Playadito", 5209, "carrefour", ean=main),
                _fila("Yerba Playadito Suave 1kg", "Playadito", 5845.89, "comodin", ean=otro),
                _fila("Yerba Mate c/Palo Suave Playadito x 1 Kg.", "Playadito", 5350, "laanonima"),
            ],
        )
        principal = next(g for g in grupos if g["ean"] == main)
        self.assertIn("laanonima", {o["tienda_id"] for o in principal["ofertas"]})
        self.assertEqual(len(principal["ofertas"]), 4)
        self.assertEqual(principal["mas_barato"], ["masonline"])
        # Un EAN distinto no se mezcla aunque el texto sea parecido.
        self.assertEqual(len(grupos), 2)
        aparte = next(g for g in grupos if g["ean"] == otro)
        self.assertEqual({o["tienda_id"] for o in aparte["ofertas"]}, {"comodin"})
        for g in grupos:
            self.assertEqual(sum(1 for o in g["ofertas"] if o["barato"]), 1)

    def test_sin_ean_misma_tienda_cada_uno_a_su_grupo(self) -> None:
        grupos = sc.agrupar_mismo_producto(
            "yerba playadito",
            [
                _fila("Yerba Mate Playadito Suave 500 Gr.", "PLAYADITO", 2835, "dia", ean="7793704000911"),
                _fila("Yerba Mate Sin Palo Playadito 500 Gr.", "PLAYADITO", 3945, "dia", ean="7793704000881"),
                _fila("Yerba Playadito Despalada 500gr", "Playadito", 4248.39, "comodin", ean="7793704000881"),
                _fila("Yerba Playadito Hierbas 500gr", "Playadito", 3602.59, "comodin", ean="7793704000508"),
                _fila("Yerba Mate c/Palo Suave Playadito x 500 g.", "Playadito", 2550, "laanonima"),
                _fila("Yerba Mate Despalada Playadito x 500 g.", "Playadito", 5150, "laanonima"),
                _fila("Yerba Mate Compuesta con Hierbas Playadito x 500 g.", "Playadito", 4400, "laanonima"),
            ],
        )
        self.assertEqual(len(grupos), 3)
        por_ean = {g["ean"]: g for g in grupos}
        def la(ean: str) -> str:
            return next(o["nombre"] for o in por_ean[ean]["ofertas"] if o["tienda_id"] == "laanonima")
        self.assertIn("Suave", la("7793704000911"))
        self.assertIn("Despalada", la("7793704000881"))
        self.assertIn("Hierbas", la("7793704000508"))

    def test_sin_ean_misma_tienda_distinto_producto_no_se_juntan(self) -> None:
        grupos = sc.agrupar_mismo_producto(
            "yerba playadito",
            [
                _fila("Yerba Mate c/Palo Suave Playadito x 500 g.", "Playadito", 2550, "laanonima"),
                _fila("Yerba Mate Despalada Playadito x 500 g.", "Playadito", 5150, "laanonima"),
            ],
        )
        self.assertEqual(len(grupos), 2)

    def test_gramaje_con_x_no_es_pack(self) -> None:
        for nombre, size in (
            ("Yerba Mate Playadito Lata X 500 Gr", ("g", 500)),
            ("Yerba Mate Despalada Playadito x 500 g.", ("g", 500)),
            ("Yerba Mate c/Palo Suave Playadito x 1 Kg.", ("g", 1000)),
            ("Yerba Mate Playadito Sin Palo X 500g", ("g", 500)),
            ("Aceite Natura x 900 ml", ("ml", 900)),
        ):
            p = _fila(nombre, "Playadito", 1000, "masonline")
            self.assertEqual(sc._medida_de(p), (size, None), nombre)
            self.assertNotIn("pack", sc._tamano_fila(*sc._medida_de(p)), nombre)

    def test_multipack_real_sigue_siendo_pack(self) -> None:
        for nombre, n in (
            ("Yerba Mate Playadito pack x6", 6),
            ("Yerba Mate Playadito 12 un", 12),
            ("Yerba Mate en Saquitos Playadito x 25 un.", 25),
            ("Gaseosa Coca Cola x 6", 6),
        ):
            size, pack = sc._medida_de(_fila(nombre, "Playadito", 1000, "masonline"))
            self.assertIsNotNone(pack, nombre)
            self.assertEqual(pack[0], n, nombre)
        size, pack = sc._medida_de(_fila("Agua Villavicencio 6 x 1 L", "Villavicencio", 6000, "dia"))
        self.assertEqual(pack, (6, ("ml", 1000)))

    def test_lata_500_gr_no_se_mezcla_con_despalada(self) -> None:
        grupos = sc.agrupar_mismo_producto(
            "yerba playadito",
            [
                _fila("Yerba Mate Playadito Lata X 500 Gr", "Playadito", 13959, "masonline", ean="7793704000089"),
                _fila("Yerba Mate Sin Palo Playadito 500 Gr.", "PLAYADITO", 3945, "dia", ean="7793704000881"),
                _fila("Yerba Mate Despalada Playadito x 500 g.", "Playadito", 5150, "laanonima"),
            ],
        )
        self.assertEqual(len(grupos), 2)
        lata = next(g for g in grupos if g["ean"] == "7793704000089")
        self.assertEqual(lata["tamano"], "500 g")
        self.assertEqual({o["tienda_id"] for o in lata["ofertas"]}, {"masonline"})
        self.assertAlmostEqual(lata["pum"], 27918.0)
        self.assertEqual(lata["pum_unidad"], "kg")
        self.assertEqual(lata["pum_nota"], "")
        despalada = next(g for g in grupos if g["ean"] == "7793704000881")
        self.assertEqual({o["tienda_id"] for o in despalada["ofertas"]}, {"dia", "laanonima"})
        for o in despalada["ofertas"]:
            self.assertIsNotNone(o["pum"])
            self.assertEqual(o["pum_nota"], "")



class BancoFiltroTest(unittest.TestCase):
    """El filtro muestra un banco, no un id ni una frase cortada. No toca precios."""

    def test_etiquetas(self) -> None:
        import promos_hoy as ph

        self.assertEqual(ph.etiqueta_banco("varios bancos (ver banks_named)"), "Varios bancos")
        self.assertEqual(ph.etiqueta_banco("Banco_Comafi_MODO"), "Banco Comafi MODO")
        self.assertEqual(ph.etiqueta_banco("Anses"), "ANSES")
        self.assertEqual(ph.etiqueta_banco("ANSES"), "ANSES")
        self.assertEqual(ph.etiqueta_banco("Modo"), "MODO")
        self.assertEqual(ph.etiqueta_banco("MODO, Modo, ICBC, Visa"), "MODO, ICBC, Visa")
        self.assertEqual(ph.etiqueta_banco("NaranjaX"), "Naranja X")
        self.assertEqual(
            ph.etiqueta_banco("Exclusivo en sucursales. Pagando con Modo desde la APP SUPERVIELLE con tus tarjetas de cre"),
            "Banco Supervielle MODO",
        )
        self.assertEqual(
            ph.etiqueta_banco("LUNES 10% DE DESCUENTO A TRAVES DE MERCADO PAGO - NO ACUMULABE CON OTRAS OFERTAS"),
            "Mercado Pago",
        )
        self.assertEqual(ph.etiqueta_banco("20% de descuento"), "")
        self.assertEqual(ph.etiqueta_banco("Banco Columbia"), "Banco Columbia")

if __name__ == "__main__":
    unittest.main()
