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


if __name__ == "__main__":
    unittest.main()
