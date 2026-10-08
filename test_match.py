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
        # El sustantivo de cabeza es "bebida": nunca cae en el tipo yerba.
        self.assertEqual(sc._tipo_de(bebida), "bebida")
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

class RelevanciaSuperTest(unittest.TestCase):
    """"leche" trae leche primero. Postres, accesorios y golosinas que la nombran no la tapan."""

    def test_leche_antes_que_postres_y_accesorios(self) -> None:
        filas = [
            _fila("Flan Exquisita Dulce De Leche Sobre 40gr", "Exquisita", 1363, "carrefour", ean="7790000000011"),
            _fila("Postre Ser Sabor Dulce de Leche 100g", "Ser", 2308, "carrefour", ean="7790000000028"),
            _fila("Hervidor de leche acero 1 L", "Hudson", 9999, "carrefour", ean="7790000000035"),
            _fila("Batidor de leche a pila", "Atma", 4999, "jumbo", ean="7790000000042"),
            _fila("Alfajor Dulce De Leche Terrabusi 55g", "Terrabusi", 2150, "jumbo", ean="7790000000059"),
            _fila("Leche chocolatada La Serenisima 1 L", "La Serenisima", 6750, "dia", ean="7790000000066"),
            _fila("Leche Entera La Serenisima 1 L", "La Serenisima", 2050, "dia", ean="7790000000073"),
            _fila("Leche Descremada Ilolay 1 L", "Ilolay", 2549, "jumbo", ean="7790000000080"),
        ]
        nombres = _nombres(sc.agrupar_mismo_producto("leche", filas))
        for fuera in ("Flan", "Postre", "Hervidor", "Batidor", "Alfajor"):
            self.assertFalse(any(n.startswith(fuera) for n in nombres), (fuera, nombres))
        self.assertTrue(nombres[0].startswith("Leche Entera") or nombres[0].startswith("Leche Descremada"), nombres)
        self.assertEqual(nombres[-1], "Leche chocolatada La Serenisima 1 L")

    def test_dulce_de_leche_es_dulce(self) -> None:
        self.assertEqual(sc._tipo_en("Dulce de leche La Serenisima 400 g"), "dulce")
        self.assertEqual(sc._tipo_en("Hervidor de leche"), "hervidor")
        self.assertEqual(sc._tipo_en("Leche Entera 1 L"), "leche")
        filas = [
            _fila("Postre Ser Sabor Dulce de Leche 100g", "Ser", 2308, "carrefour", ean="7790000000028"),
            _fila("Dulce de Leche La Serenisima 400 g", "La Serenisima", 3499, "dia", ean="7790000000097"),
        ]
        nombres = _nombres(sc.agrupar_mismo_producto("dulce de leche", filas))
        self.assertEqual(nombres[0], "Dulce de Leche La Serenisima 400 g")


class RelevanciaElectroTest(unittest.TestCase):
    """"heladera" trae heladeras antes que organizadores, hueveras o jarras."""

    def test_heladera_antes_que_accesorios(self) -> None:
        import electro

        def p(nombre: str, precio: float) -> dict:
            return {"nombre": nombre, "precio": precio, "tienda": "T", "tienda_id": "t"}

        productos = [
            p("Organizador Heladera Nouvelle Cuisine 1040501", 9269),
            p("Jarra Termolar 2.5lt Guarani azul", 14719),
            p("Huevera Heladera Todos Los Modelos Samsung", 16019),
            p("Conservadora Garden 34 lt azul", 27599),
            p("Estante De Vidrio Heladera Bespoke Samsung", 43329),
            p("Heladera Midea Ciclica 295lt", 792402),
            p("Freezer Horizontal Gafa 200 L", 600000),
            p("Heladera Frigobar Vondom Negra 47L", 321999),
            p("Samsung Heladera No Frost 380 L", 1500000),
        ]
        out = [x["nombre"] for x in electro.ordenar(productos, "heladera")]
        self.assertEqual(
            out[:4],
            [
                "Heladera Frigobar Vondom Negra 47L",
                "Freezer Horizontal Gafa 200 L",
                "Heladera Midea Ciclica 295lt",
                "Samsung Heladera No Frost 380 L",
            ],
        )
        self.assertNotIn("Jarra Termolar 2.5lt Guarani azul", out)
        self.assertNotIn("Conservadora Garden 34 lt azul", out)
        self.assertEqual(set(out[4:]), {
            "Organizador Heladera Nouvelle Cuisine 1040501",
            "Huevera Heladera Todos Los Modelos Samsung",
            "Estante De Vidrio Heladera Bespoke Samsung",
        })

    def test_sin_coincidencias_no_se_vacia(self) -> None:
        import electro

        productos = [{"nombre": "Jarra Termolar", "precio": 10.0}]
        self.assertEqual(len(electro.ordenar(productos, "heladera")), 1)


class PaginasTest(unittest.TestCase):
    """404 en HTML para personas, JSON para /api. Favicon servido."""

    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient
        import app as app_mod

        cls.client = TestClient(app_mod.app)

    def test_404_html(self) -> None:
        r = self.client.get("/no-existe-esto", headers={"Accept": "text/html"})
        self.assertEqual(r.status_code, 404)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertIn("BaratoYa", r.text)
        self.assertNotIn('"detail"', r.text)

    def test_404_api_sigue_json(self) -> None:
        r = self.client.get("/api/no-existe")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json().get("detail"), "Not Found")

    def test_favicon(self) -> None:
        for path in ("/favicon.svg", "/favicon.ico"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn("image/svg+xml", r.headers["content-type"])
            self.assertIn("#163300", r.text)


class MeliAvisoTest(unittest.TestCase):
    """Un 403 de Mercado Libre llega una sola vez, en castellano, y la búsqueda sigue."""

    def test_403_una_vez_en_super_y_electro(self) -> None:
        import asyncio as aio
        from fastapi.testclient import TestClient
        import app as app_mod
        import electro

        from meli import AVISO_CATALOGO_CERRADO

        aviso = AVISO_CATALOGO_CERRADO
        meli_403 = {
            "tienda": "Mercado Libre", "tienda_id": "mla", "http": 403, "ok": False,
            "n": 0, "productos": [], "aviso": aviso,
        }

        async def gate(request, q):
            return {"ok": True, "plan": "free", "used": 1, "remaining": 4, "limit": 5}

        async def meli(q, limit=10):
            return dict(meli_403)

        async def super_(q, consultas=None):
            return {"productos": [], "q_usada": q, "fuentes": [
                {"tienda": "Dia", "tienda_id": "dia", "http": 200, "ok": False, "n": 0}]}

        async def promos():
            return []

        async def pc(path, params):
            return 200, {"productos": []}

        async def vtex(client, store, q):
            return {"tienda": store["nombre"], "tienda_id": store["id"], "http": 206, "ok": False, "productos": []}

        with patch.object(app_mod, "_exigir_busqueda", gate), \
                patch.object(app_mod, "buscar_meli", meli), \
                patch.object(app_mod, "buscar_super", super_), \
                patch.object(app_mod, "buscar_promos", promos), \
                patch.object(app_mod, "pc_get", pc), \
                patch("meli.buscar_meli", meli), \
                patch.object(electro, "_one", vtex):
            client = TestClient(app_mod.app)
            r = client.get("/api/buscar?q=leche")
            self.assertEqual(r.status_code, 200)
            mla = [f for f in r.json()["cadenas"] if f.get("tienda_id") == "mla"]
            self.assertEqual(len(mla), 1)
            self.assertEqual(mla[0]["aviso"], aviso)
            r = client.get("/api/electro?q=heladera")
            self.assertEqual(r.status_code, 200)
            mla = [f for f in r.json()["data"]["fuentes"] if f.get("tienda_id") == "mla"]
            self.assertEqual(len(mla), 1)
            self.assertEqual(mla[0]["aviso"], aviso)


class PromosSemanaTest(unittest.TestCase):
    """Pruebas para promos-semana: do_not_apply no se resta y día ISO 7 = domingo."""

    def test_do_not_apply_no_se_resta(self) -> None:
        from datetime import date
        import promos_hoy as ph

        # Tarjeta válida en vigencia, porcentaje, canal online y con tope,
        # pero con motivo en do_not_apply -> nunca se resta.
        rec = ph._base(
            chain_id="dia",
            cadena="Día",
            banco="Prex",
            percent=30.0,
            days={0},  # Lunes (0)
            canal="online",
            cap=20000.0,
            inicio=date(2026, 10, 5),
            fin=date(2026, 10, 5),
            do_not_apply="Solo una vez / primera compra con Prex",
        )
        ok, motivo, total = ph.puede_restar(rec, "Leche Entera", 5000.0, date(2026, 10, 5))
        self.assertFalse(ok)
        self.assertEqual(total, 5000.0)
        self.assertEqual(motivo, "Solo una vez / primera compra con Prex")

        # Comprobar también que si do_not_apply es None la tarjeta sí se resta (control)
        rec_ok = dict(rec)
        rec_ok["do_not_apply"] = None
        ok_resta, _, total_resta = ph.puede_restar(rec_ok, "Leche Entera", 5000.0, date(2026, 10, 5))
        self.assertTrue(ok_resta)
        self.assertEqual(total_resta, 3500.0)

    def test_dia_iso_7_es_domingo(self) -> None:
        from datetime import date
        import promos_hoy as ph

        # El domingo 11/10/2026 tiene weekday() == 6
        domingo = date(2026, 10, 11)
        self.assertEqual(domingo.weekday(), 6)
        self.assertEqual(ph.NOMBRE_DIA[6], "domingo")

        # Cargar catálogo de promos-semana y verificar que las filas con ISO 7 mapean a domingo (6)
        recs = ph.cargar(forzar=True)
        recs_domingo = [r for r in recs if 6 in r.get("days", set())]
        self.assertGreater(len(recs_domingo), 0)

        # En la tarjeta pública de una promo de domingo figura el domingo
        card = ph.tarjeta_publica(recs_domingo[0])
        self.assertTrue("domingo" in card["dias"] or card["dias"] == "todos los días")

        # En el catálogo, el grupo domingo incluye las tarjetas con día 6
        cat = ph.catalogo(domingo)
        grupo_domingo = next(g for g in cat["por_dia"] if g["dia"] == "domingo")
        self.assertTrue(grupo_domingo["hoy"])
        self.assertGreater(len(grupo_domingo["items"]), 0)


class PreciosLogosTypoTest(unittest.TestCase):
    """Pruebas para el brief precios-logos-typo (lote crítico 1–3)."""

    def test_consultas_busqueda_playadito_suave_1kg(self) -> None:
        from app import consultas_busqueda

        consultas = consultas_busqueda("playadito suave 1 kg")
        self.assertIn("playadito suave 1 kg", consultas)
        self.assertIn("playadito suave", consultas)
        # La versión de una palabra "playadito" debe estar para fallback de Precios Claros
        self.assertIn("playadito", consultas)

    def test_agrupar_playadito_suave_no_confunde_sin_palo_500g(self) -> None:
        grupos = sc.agrupar_mismo_producto(
            "playadito suave 1 kg",
            [
                _fila(
                    "Yerba Mate Suave Playadito 1kg",
                    "Playadito",
                    5289.0,
                    "masonline",
                    presentacion="1 kg",
                    ean="7793704000928",
                ),
                _fila(
                    "Yerba Suave Playadito 1 Kg",
                    "PLAYADITO",
                    5198.0,
                    "precios_claros",
                    presentacion="1.0 kg",
                    pc=True,
                    pc_id="7793704000928",
                ),
                _fila(
                    "Yerba Mate Elaborada sin Palo Playadito 500 Gr",
                    "PLAYADITO",
                    3969.0,
                    "precios_claros",
                    presentacion="500.0 gr",
                    pc=True,
                    pc_id="7793704000881",
                ),
            ],
        )
        # 500g sin palo no cumple con 1kg ni con suave
        self.assertEqual(len(grupos), 1)
        self.assertEqual(grupos[0]["ean"], "7793704000928")
        self.assertEqual(len(grupos[0]["ofertas"]), 2)
        tiendas = {o["tienda_id"] for o in grupos[0]["ofertas"]}
        self.assertEqual(tiendas, {"masonline", "precios_claros"})
        self.assertEqual(grupos[0]["precio"], 5198.0)

    def test_agrupar_playadito_suave_sin_especificar_peso(self) -> None:
        grupos = sc.agrupar_mismo_producto(
            "playadito suave",
            [
                _fila(
                    "Yerba Mate Suave Playadito 1kg",
                    "Playadito",
                    5289.0,
                    "masonline",
                    presentacion="1 kg",
                    ean="7793704000928",
                ),
                _fila(
                    "Yerba Mate Suave con Palo Playadito 500 Gr",
                    "PLAYADITO",
                    2758.0,
                    "precios_claros",
                    presentacion="500.0 gr",
                    pc=True,
                    pc_id="7793704000911",
                ),
                _fila(
                    "Yerba Mate Elaborada sin Palo Playadito 500 Gr",
                    "PLAYADITO",
                    3969.0,
                    "precios_claros",
                    presentacion="500.0 gr",
                    pc=True,
                    pc_id="7793704000881",
                ),
            ],
        )
        # Suave 1kg y Suave 500g quedan separados; Sin Palo no tiene 'suave'
        eans = [g["ean"] for g in grupos]
        self.assertIn("7793704000928", eans)
        self.assertIn("7793704000911", eans)
        self.assertNotIn("7793704000881", eans)

    def test_cache_control_headers_en_con_cuenta(self) -> None:
        from app import _con_cuenta

        resp = _con_cuenta({"test": 123}, {"plan": "free", "used": 1, "remaining": 4})
        self.assertIn("Cache-Control", resp.headers)
        self.assertIn("no-store", resp.headers["Cache-Control"])
        self.assertIn("max-age=0", resp.headers["Cache-Control"])
        self.assertEqual(resp.headers.get("Pragma"), "no-cache")

    def test_brand_logos_vector_oficiales_validos(self) -> None:
        from pathlib import Path
        import json

        logos_json = Path(__file__).parent / "data" / "brand-logos.json"
        self.assertTrue(logos_json.exists())
        data = json.loads(logos_json.read_text(encoding="utf-8"))
        self.assertIn("brands", data)
        self.assertGreater(len(data["brands"]), 20)

        # Verificar que existen los logos vectoriales oficiales de bancos clave
        static_logos = Path(__file__).parent / "static" / "brand-logos"
        bancos_clave = [
            "galicia", "bbva", "santander", "macro", "nacion", "provincia",
            "cuenta_dni", "ciudad", "credicoop", "hipotecario", "supervielle",
            "patagonia", "bancor", "comafi", "columbia", "icbc", "uala",
            "cencopay", "la_anonima", "modo", "mercado_pago", "naranja_x",
        ]
        for banco in bancos_clave:
            svg_path = static_logos / f"{banco}.svg"
            self.assertTrue(svg_path.exists(), f"Falta SVG para {banco}")
            content = svg_path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("<svg"), f"{banco} no empieza con <svg")
            self.assertTrue(content.strip().endswith("</svg>"), f"{banco} no termina con </svg>")
            self.assertIn('rx="14"', content, f"{banco} no tiene el radio de esquina estándar")

    def test_tipografia_atkinson_y_baskerville_en_index(self) -> None:
        from pathlib import Path

        tpl = (Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")
        faces = (Path(__file__).parent / "templates" / "_font_faces.css").read_text(encoding="utf-8")
        self.assertIn("--font-ui: \"Atkinson Hyperlegible\"", tpl)
        self.assertIn("--font-serif: \"Libre Baskerville\"", tpl)
        self.assertIn("font-display: swap", faces)
        self.assertIn("/static/fonts/atkinson-hyperlegible-400.woff2", faces)
        self.assertIn("/static/fonts/atkinson-hyperlegible-700.woff2", faces)
        self.assertIn("/static/fonts/libre-baskerville-400.woff2", faces)
        self.assertIn("/static/fonts/libre-baskerville-700.woff2", faces)
        self.assertNotIn("fonts.googleapis.com", tpl)
        self.assertNotIn("fonts.googleapis.com", faces)
        self.assertIn("#163300", tpl.casefold())
        self.assertIn("#9fe870", tpl.casefold())

    def test_aplicar_oferta_con_banco_preferido_y_banco_inexistente(self) -> None:
        from datetime import date
        from promos_hoy import aplicar_oferta

        # Martes 06/10/2026: Naranja X 30% en Dia
        d_martes = date(2026, 10, 6)
        res_naranja = aplicar_oferta("dia", "Yerba Mate 1kg", 10000.0, d_martes, bancos_permitidos=["naranja_x"])
        self.assertEqual(res_naranja["total"], 7000.0)
        self.assertIsNotNone(res_naranja["promo"])
        self.assertTrue(res_naranja["promo"]["aplicada"])
        self.assertIn("Naranja X", res_naranja["promo"]["linea_corta"])
        self.assertIn("30%", res_naranja["promo"]["linea_corta"])

        # Si el usuario solo tiene un banco sin promo ese día, no se descuenta
        res_fantasma = aplicar_oferta("dia", "Yerba Mate 1kg", 10000.0, d_martes, bancos_permitidos=["banco_inexistente"])
        self.assertEqual(res_fantasma["total"], 10000.0)
        self.assertIsNone(res_fantasma["promo"])

    def test_agrupar_con_promo_on_off_y_supermercados(self) -> None:
        from datetime import date

        filas = [
            _fila("Yerba Mate 1kg", "Playadito", 10000.0, "dia"),
            _fila("Yerba Mate 1kg", "Playadito", 9500.0, "disco"),
        ]
        d_martes = date(2026, 10, 6)

        # con_promo=True: calcula descuento
        g_on = sc.agrupar_mismo_producto("yerba mate", filas, hoy=d_martes, con_promo=True, bancos_permitidos=["naranja_x"])
        ofertas_on = g_on[0]["ofertas"]
        promos_on = [o.get("promo") for o in ofertas_on if o.get("promo")]
        self.assertTrue(len(promos_on) > 0)

        # con_promo=False: precio puro de góndola, sin promo
        g_off = sc.agrupar_mismo_producto("yerba mate", filas, hoy=d_martes, con_promo=False)
        ofertas_off = g_off[0]["ofertas"]
        for o in ofertas_off:
            self.assertIsNone(o.get("promo"))

        # supermercados_permitidos: filtra y deja solo Dia en ofertas
        g_fav = sc.agrupar_mismo_producto("yerba mate", filas, hoy=d_martes, supermercados_permitidos=["dia"])
        self.assertEqual(len(g_fav[0]["ofertas"]), 1)
        self.assertEqual(g_fav[0]["ofertas"][0]["tienda_id"], "dia")

    def test_supermercados_preferidos_filtrado_y_promos(self) -> None:
        import promos_hoy
        from super_cadenas import normalizar_cadena_id

        # 1. Con supermarkets=["dia"], ofertas de carrefour no aparecen en el grupo
        filas = [
            _fila("Yerba Mate 1kg", "Playadito", 10000.0, "dia"),
            _fila("Yerba Mate 1kg", "Playadito", 9500.0, "carrefour"),
        ]
        g1 = sc.agrupar_mismo_producto("yerba mate", filas, supermercados_permitidos=["dia"])
        self.assertEqual(len(g1), 1)
        tiendas1 = [o["tienda_id"] for o in g1[0]["ofertas"]]
        self.assertIn("dia", tiendas1)
        self.assertNotIn("carrefour", tiendas1)

        # 2. Grupo solo Carrefour + filtro Día -> grupo omitido
        filas_carrefour = [
            _fila("Yerba Mate 1kg", "Playadito", 9500.0, "carrefour"),
        ]
        g2 = sc.agrupar_mismo_producto("yerba mate", filas_carrefour, supermercados_permitidos=["dia"])
        self.assertEqual(len(g2), 0)

        # 3. Lista vacía de supers -> sin filtro (muestra todas las cadenas)
        g_vacio = sc.agrupar_mismo_producto("yerba mate", filas, supermercados_permitidos=[])
        self.assertEqual(len(g_vacio), 1)
        self.assertEqual(set(o["tienda_id"] for o in g_vacio[0]["ofertas"]), {"dia", "carrefour"})

        g_none = sc.agrupar_mismo_producto("yerba mate", filas, supermercados_permitidos=None)
        self.assertEqual(len(g_none), 1)
        self.assertEqual(set(o["tienda_id"] for o in g_none[0]["ofertas"]), {"dia", "carrefour"})

        # Normalización de alias
        self.assertEqual(normalizar_cadena_id("Día"), "dia")
        self.assertEqual(normalizar_cadena_id("coto"), "cotodigital")
        self.assertEqual(normalizar_cadena_id("la anónima"), "laanonima")
        self.assertEqual(normalizar_cadena_id("Mas Online"), "masonline")

        # 4. Promos filtradas por cadena preferida
        cat = promos_hoy.catalogo()
        por_dia = cat.get("por_dia", [])
        self.assertTrue(len(por_dia) > 0)
        todas_las_promos = [item for g in por_dia for item in g.get("items", [])]
        self.assertTrue(len(todas_las_promos) > 0)
        promos_dia = [p for p in todas_las_promos if normalizar_cadena_id(p.get("chain_id") or p.get("cadena")) == "dia"]
        self.assertTrue(len(promos_dia) > 0)
        self.assertTrue(all(normalizar_cadena_id(p.get("chain_id") or p.get("cadena")) == "dia" for p in promos_dia))
        # Si filtramos por día, ninguna promo es de carrefour
        self.assertTrue(all(normalizar_cadena_id(p.get("chain_id") or p.get("cadena")) != "carrefour" for p in promos_dia))

    def test_links_tienda_target_blank_y_sin_ruido_legal(self) -> None:
        from pathlib import Path

        tpl = (Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")
        # Todos los links externos de tienda deben abrir en nueva pestaña
        tpl_clean = tpl.replace('\\"', '"')
        self.assertIn('target="_blank" rel="noopener noreferrer"', tpl_clean)
        # No debe haber acordeón ni texto crudo de letra de promo en las cards
        self.assertNotIn("store-legal", tpl)
        self.assertNotIn("Letra de la promo", tpl)
        # Debe tener los estilos de góndola tachado y promo pill
        self.assertIn(".store-gondola", tpl)
        self.assertIn(".store-promo-line", tpl)
        self.assertIn("prefs-dialog", tpl)

    def test_preferencias_usuario_normalizar_y_endpoints(self) -> None:
        from unittest.mock import AsyncMock, patch
        import cuentas
        from fastapi.testclient import TestClient
        from app import app

        # Normalización de prefs
        norm = cuentas.normalizar_prefs({"show_promo_price": False, "banks": ["Galicia", " "], "supermarkets": ["DIA", "carrefour"]})
        self.assertFalse(norm["show_promo_price"])
        self.assertEqual(norm["banks"], ["galicia"])
        self.assertEqual(norm["supermarkets"], ["dia", "carrefour"])

        # Default prefs
        self.assertTrue(cuentas.DEFAULT_PREFS["show_promo_price"])
        self.assertEqual(cuentas.DEFAULT_PREFS["banks"], [])
        self.assertEqual(cuentas.DEFAULT_PREFS["supermarkets"], [])

        # Endpoints
        client = TestClient(app)
        with patch("cuentas.cuentas_on", return_value=True):
            # Sin token -> 401
            r_unauth = client.get("/api/cuenta/preferencias")
            self.assertEqual(r_unauth.status_code, 401)

            # Con sesión válida -> GET y POST funcionan
            with patch("cuentas.usuario", AsyncMock(return_value={"id": "u-123", "email": "test@baratoya.com"})):
                with patch("cuentas.leer_cuenta", AsyncMock(return_value={"plan": "free", "used": 0, "remaining": 5, "limit": 5, "prefs": norm})):
                    with patch("cuentas.guardar_preferencias", AsyncMock(return_value={"ok": True, "prefs": norm})):
                        headers = {"Authorization": "Bearer mock-token"}
                        r_get = client.get("/api/cuenta/preferencias", headers=headers)
                        self.assertEqual(r_get.status_code, 200)
                        self.assertEqual(r_get.json()["prefs"]["show_promo_price"], False)

                        r_post = client.post("/api/cuenta/preferencias", json=norm, headers=headers)
                        self.assertEqual(r_post.status_code, 200)
                        self.assertTrue(r_post.json()["ok"])

    def test_migracion_sql_perfil_prefs_existente_y_valida(self) -> None:
        from pathlib import Path

        migration_path = Path(__file__).parent / "supabase" / "migrations" / "baratoya_perfil_prefs.sql"
        self.assertTrue(migration_path.exists(), "La migración SQL de preferencias de perfil debe existir")
        sql = migration_path.read_text(encoding="utf-8")
        self.assertIn("alter table public.profiles", sql.lower())
        self.assertIn("add column if not exists prefs jsonb", sql.lower())
        self.assertIn("grant update (prefs", sql.lower())


class PromosSuperTests(unittest.TestCase):
    """Pruebas del brief 'Ver promociones del supermercado':
    - Día + lunes -> N promos con precio final
    - Cuotas no bajan precio
    - do_not_apply no resta
    - Descuentos efectivos calculan precio final y ordenan con cuotas al final
    - Endpoint /api/promos?cadena=dia&dia=lunes
    - Cadena sin promos no explota
    """

    def test_dia_lunes_promos_con_precio_final(self) -> None:
        import promos_hoy as ph

        res = ph.promos_para_cadena("dia", "lunes", 3000.0, "Dulce de leche")
        self.assertEqual(res["cadena"], "Día")
        self.assertEqual(res["chain_id"], "dia")
        self.assertEqual(res["dia"], "lunes")
        self.assertEqual(res["precio_gondola"], 3000.0)

        # Hay N promos para Día el lunes
        promos = res["promos"]
        self.assertGreater(len(promos), 0)
        self.assertEqual(res["total"], len(promos))

        # Cada promo tiene un precio final definido
        for p in promos:
            self.assertIsNotNone(p.get("precio_final"))
            self.assertIsInstance(p["precio_final"], (int, float))

    def test_cuotas_no_bajan_precio(self) -> None:
        import promos_hoy as ph

        res = ph.promos_para_cadena("dia", "lunes", 3000.0, "Dulce de leche")
        promos_cuotas = [p for p in res["promos"] if p.get("cuotas")]
        self.assertGreater(len(promos_cuotas), 0)

        for p in promos_cuotas:
            self.assertFalse(p["puede_restar"], f"{p['banco']} con cuotas no debe restar")
            self.assertEqual(p["descuento"], 0.0)
            self.assertEqual(p["precio_final"], 3000.0, "Cuotas deben mantener el precio de góndola")
            self.assertIn("cuotas", p["cuotas"].lower())

    def test_do_not_apply_no_resta(self) -> None:
        import promos_hoy as ph

        res = ph.promos_para_cadena("dia", "lunes", 3000.0, "Dulce de leche")
        promos_dna = [p for p in res["promos"] if p.get("do_not_apply")]
        self.assertGreater(len(promos_dna), 0)

        for p in promos_dna:
            self.assertFalse(p["puede_restar"], f"{p['banco']} con do_not_apply no debe restar")
            self.assertEqual(p["descuento"], 0.0)
            self.assertEqual(p["precio_final"], 3000.0, "do_not_apply no debe restar del precio")
            self.assertTrue(len(p["do_not_apply"]) > 0)

        # Prex específicamente tiene motivo do_not_apply
        prex = next((p for p in promos_dna if "prex" in p["banco"].lower()), None)
        self.assertIsNotNone(prex)
        self.assertEqual(prex["precio_final"], 3000.0)
        self.assertFalse(prex["puede_restar"])
        self.assertEqual(prex["do_not_apply"], "Solo una vez / primera compra con Prex")

    def test_dia_martes_descuento_efectivo_y_orden(self) -> None:
        import promos_hoy as ph

        res = ph.promos_para_cadena("dia", "martes", 3000.0, "Dulce de leche")
        promos = res["promos"]
        self.assertGreater(len(promos), 0)

        # Hay promos que sí aplican descuento efectivo
        aplican = [p for p in promos if p["puede_restar"]]
        self.assertGreater(len(aplican), 0)

        for p in aplican:
            self.assertGreater(p["descuento"], 0.0)
            self.assertLess(p["precio_final"], 3000.0)
            self.assertEqual(round(p["precio_final"] + p["descuento"], 2), 3000.0)

        # Comprobar Naranja X Plan Épico (30% sobre 3000 = $900 -> final $2100)
        epico = next((p for p in aplican if "épico" in p["banco"].lower()), None)
        self.assertIsNotNone(epico)
        self.assertEqual(epico["precio_final"], 2100.0)
        self.assertEqual(epico["descuento"], 900.0)

        # Comprobar orden: los descuentos efectivos van primero (menor precio final primero)
        # y las promos de cuotas van al final
        precios_aplican = [p["precio_final"] for p in aplican]
        self.assertEqual(precios_aplican, sorted(precios_aplican), "Deben ordenarse de menor precio final a mayor")

        # Verificar que las cuotas quedan después de los descuentos efectivos
        indices_descuento = [i for i, p in enumerate(promos) if p["puede_restar"]]
        indices_cuotas = [i for i, p in enumerate(promos) if p.get("cuotas")]
        if indices_descuento and indices_cuotas:
            self.assertLess(max(indices_descuento), min(indices_cuotas), "Cuotas deben estar al final")

    def test_api_promos_cadena_endpoint(self) -> None:
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from app import app
        import cuentas

        client = TestClient(app)

        # Sin sesión da 401
        r_anon = client.get("/api/promos?cadena=dia&dia=lunes&precio=3000&nombre=Dulce+de+leche")
        self.assertEqual(r_anon.status_code, 401)
        self.assertEqual(r_anon.json().get("reason"), "auth")

        # Con sesión da 200 y devuelve las promos
        async def fake_usuario(token):
            return {"id": "00000000-0000-0000-0000-000000000001", "email": "test@baratoya.app"}

        with patch.object(cuentas, "token_de", return_value="tok_valido"), \
             patch.object(cuentas, "cuentas_on", return_value=True), \
             patch.object(cuentas, "usuario", fake_usuario):
            r = client.get("/api/promos?cadena=dia&dia=lunes&precio=3000&nombre=Dulce+de+leche")
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertEqual(data["cadena"], "Día")
            self.assertEqual(data["chain_id"], "dia")
            self.assertEqual(data["dia"], "lunes")
            self.assertEqual(data["precio_gondola"], 3000.0)
            self.assertGreater(data["total"], 0)
            self.assertEqual(len(data["promos"]), data["total"])

            for p in data["promos"]:
                self.assertIn("banco", p)
                self.assertIn("oferta", p)
                self.assertIn("precio_final", p)
                self.assertIn("puede_restar", p)

    def test_cadena_sin_promos_responde_amigable(self) -> None:
        from unittest.mock import patch
        import promos_hoy as ph
        from fastapi.testclient import TestClient
        from app import app
        import cuentas

        # Directo en Python
        res = ph.promos_para_cadena("El Abastecedor", "lunes", 2500.0)
        self.assertEqual(res["chain_id"], "abastecedor")
        self.assertEqual(res["total"], 0)
        self.assertEqual(len(res["promos"]), 0)
        self.assertIn("abastecedor", res["nota"].lower())

        # Vía endpoint con sesión
        async def fake_usuario(token):
            return {"id": "00000000-0000-0000-0000-000000000001", "email": "test@baratoya.app"}

        client = TestClient(app)
        with patch.object(cuentas, "token_de", return_value="tok_valido"), \
             patch.object(cuentas, "cuentas_on", return_value=True), \
             patch.object(cuentas, "usuario", fake_usuario):
            r = client.get("/api/promos?cadena=abastecedor&dia=lunes&precio=2500")
            self.assertEqual(r.status_code, 200)
            data = r.json()
            self.assertEqual(data["total"], 0)
            self.assertIn("abastecedor", data["nota"].lower())


class LandingPlanesMercadoPagoTest(unittest.TestCase):
    """Pruebas para el brief landing-planes-mp (producto vendible)."""

    def test_landing_html_contiene_mockup_como_funciona_y_planes(self) -> None:
        from fastapi.testclient import TestClient
        from app import app

        client = TestClient(app)
        r = client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("baratoya-hero-landing.jpg", r.text)
        self.assertIn("Cómo funciona", r.text)
        self.assertIn("/planes", r.text)
        self.assertIn("BaratoYa Plus", r.text)
        self.assertIn("$1.990", r.text)
        self.assertIn("Precios estimados", r.text)

    def test_planes_endpoint_html(self) -> None:
        from fastapi.testclient import TestClient
        from app import app

        client = TestClient(app)
        r = client.get("/planes")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Gratis", r.text)
        self.assertIn("BaratoYa Plus", r.text)
        self.assertIn("$1.990", r.text)
        self.assertIn("Mercado Pago", r.text)
        import json
        import re

        blocks = re.findall(
            r'<script type="application/ld\+json">(.*?)</script>',
            r.text,
            flags=re.S,
        )
        self.assertEqual(len(blocks), 1)
        data = json.loads(blocks[0])
        self.assertEqual(data["@context"], "https://schema.org")
        self.assertEqual(data["@type"], "SoftwareApplication")
        self.assertEqual(data["name"], "BaratoYa")
        offers = {item["name"]: item for item in data["offers"]}
        self.assertEqual(offers["Gratis"]["@type"], "Offer")
        self.assertEqual(offers["Gratis"]["price"], "0")
        self.assertEqual(offers["Gratis"]["priceCurrency"], "ARS")
        self.assertEqual(offers["BaratoYa Plus"]["@type"], "Offer")
        self.assertEqual(offers["BaratoYa Plus"]["price"], "1990")
        self.assertEqual(offers["BaratoYa Plus"]["priceCurrency"], "ARS")
        self.assertNotIn("aggregateRating", data)
        self.assertNotIn("review", data)

    def test_static_hero_landing_asset(self) -> None:
        from fastapi.testclient import TestClient
        from app import app

        client = TestClient(app)
        r = client.get("/static/baratoya-hero-landing.jpg")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers.get("content-type", "").startswith("image/"))

    def test_checkout_sin_sesion_da_401(self) -> None:
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from app import app
        import cuentas

        client = TestClient(app)
        # Sin cuentas configuradas responde 503
        r_503 = client.post("/api/cuenta/checkout")
        self.assertEqual(r_503.status_code, 503)

        # Con cuentas configuradas pero sin Bearer token responde 401
        with patch.object(cuentas, "cuentas_on", return_value=True):
            r = client.post("/api/cuenta/checkout")
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.json().get("reason"), "auth")

    def test_cuentas_pagina_publica_valores(self) -> None:
        import cuentas

        pub = cuentas.pagina_publica()
        self.assertEqual(pub["plan_label"], "$1.990")
        self.assertEqual(pub["plan_price"], 1990)
        self.assertEqual(pub["plan_cents"], 199000)

    def test_404_y_legal_tienen_enlace_a_planes(self) -> None:
        from fastapi.testclient import TestClient
        from app import app

        client = TestClient(app)
        r404 = client.get("/ruta-que-no-existe-para-test")
        self.assertEqual(r404.status_code, 404)
        self.assertIn("/planes", r404.text)

        r_term = client.get("/terminos")
        self.assertEqual(r_term.status_code, 200)
        self.assertIn("/planes", r_term.text)

    def test_admin_requiere_permisos(self) -> None:
        from fastapi.testclient import TestClient
        from app import app

        client = TestClient(app)
        r = client.get("/admin")
        self.assertEqual(r.status_code, 403)


class BatchPendientesLoteTest(unittest.TestCase):
    """Pruebas del lote único BRIEF-pendientes-lote.md (P0, P0b, P1, P1.5, P2)."""

    def test_anonimo_sin_promos_da_401(self) -> None:
        from fastapi.testclient import TestClient
        from app import app

        client = TestClient(app)
        r = client.get("/api/promos")
        self.assertEqual(r.status_code, 401)
        data = r.json()
        self.assertFalse(data.get("ok"))
        self.assertEqual(data.get("reason"), "auth")
        self.assertIn("cuenta gratis", data.get("error", "").lower())

    def test_anonimo_buscar_da_401(self) -> None:
        from fastapi.testclient import TestClient
        from app import app

        client = TestClient(app)
        r = client.get("/api/buscar?q=leche")
        self.assertEqual(r.status_code, 401)
        data = r.json()
        self.assertFalse(data.get("ok"))
        self.assertEqual(data.get("reason"), "auth")
        self.assertIn("cuenta gratis", data.get("error", "").lower())

    def test_home_nav_limpia_y_promos_wall_presente(self) -> None:
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from app import app
        import cuentas

        with patch.object(cuentas, "cuentas_on", return_value=True):
            client = TestClient(app)
            r = client.get("/")
            self.assertEqual(r.status_code, 200)
            # Link promos en nav está oculto por defecto para anónimos
            self.assertIn('id="nav-promos-link" hidden', r.text)
            # Muro de login para promos bancarias presente
            self.assertIn('id="promos-wall"', r.text)
            self.assertIn("Creá una cuenta gratis para ver promos y precios", r.text)
            self.assertIn('id="promos-wall-cta"', r.text)
            # Form modal entrar tiene toggle y mensajes
            self.assertIn('id="cuenta-toggle-modo"', r.text)
            self.assertIn('id="cuenta-submit"', r.text)

    def test_admin_subroutes_anonimo_da_403(self) -> None:
        from fastapi.testclient import TestClient
        from app import app

        client = TestClient(app)
        for path in ["/admin", "/admin/usuarios", "/admin/usuarios/123", "/admin/busquedas", "/admin/pagos"]:
            r = client.get(path)
            self.assertEqual(r.status_code, 403, f"Fallo en {path}")
            self.assertIn("No podés abrir esto", r.text)

    def test_admin_subroutes_admin_da_200(self) -> None:
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from app import app
        import cuentas

        async def fake_usuario(token):
            return {"id": "00000000-0000-0000-0000-000000000001", "email": "baratoyaba@gmail.com"}

        async def fake_es_admin(token, uid):
            return True

        async def fake_listar_usuarios():
            return [{
                "id": "00000000-0000-0000-0000-000000000001",
                "id_corto": "00000000",
                "email": "baratoyaba@gmail.com",
                "plan_display": "Plus",
                "trial_ends_at": "—",
                "searches_used": 10,
                "role": "admin",
                "created_at": "1 oct 2026, 12:00 ART",
                "last_sign_in": "5 oct 2026, 20:00 ART",
            }]

        async def fake_detalle_usuario(uid):
            return {
                "usuario": {
                    "id": uid,
                    "id_corto": uid[:8],
                    "email": "test@baratoya.app",
                    "plan_display": "Trial Plus",
                    "trial_ends_at": "12 oct 2026, 12:00 ART",
                    "searches_used": 2,
                    "role": "user",
                    "created_at": "5 oct 2026, 12:00 ART",
                    "last_sign_in": "5 oct 2026, 12:00 ART",
                    "paid_at": "—",
                },
                "busquedas": [{"query": "yerba", "created_at": "5 oct 2026, 12:05 ART"}],
            }

        async def fake_listar_busquedas(limit=50):
            return [{"id": "1", "user_id": "u1", "email": "test@baratoya.app", "query": "leche", "created_at": "5 oct 2026, 12:10 ART"}]

        async def fake_listar_pagos():
            return {
                "pagos": [{"payment_id": "999888", "user_id": "u1", "email": "pago@baratoya.app", "monto": "$1.990", "status": "Aprobado", "fecha": "5 oct 2026, 10:00 ART"}],
                "total_mes": "$1.990",
                "total_lifetime": "$1.990",
                "cobro_activo": True,
                "vacio": False,
            }

        client = TestClient(app)
        with patch.object(cuentas, "token_de", return_value="tok_admin"), \
             patch.object(cuentas, "cuentas_on", return_value=True), \
             patch.object(cuentas, "usuario", fake_usuario), \
             patch.object(cuentas, "es_admin", fake_es_admin), \
             patch.object(cuentas, "admin_listar_usuarios", fake_listar_usuarios), \
             patch.object(cuentas, "admin_detalle_usuario", fake_detalle_usuario), \
             patch.object(cuentas, "admin_listar_busquedas", fake_listar_busquedas), \
             patch.object(cuentas, "admin_listar_pagos", fake_listar_pagos):

            r_resumen = client.get("/admin")
            self.assertEqual(r_resumen.status_code, 200)
            self.assertIn("Panel de Administración", r_resumen.text)

            r_usr = client.get("/admin/usuarios")
            self.assertEqual(r_usr.status_code, 200)
            self.assertIn("baratoyaba@gmail.com", r_usr.text)

            r_det = client.get("/admin/usuarios/00000000-0000-0000-0000-000000000001")
            self.assertEqual(r_det.status_code, 200)
            self.assertIn("test@baratoya.app", r_det.text)
            self.assertIn("yerba", r_det.text)

            r_srch = client.get("/admin/busquedas")
            self.assertEqual(r_srch.status_code, 200)
            self.assertIn("leche", r_srch.text)

            r_pagos = client.get("/admin/pagos")
            self.assertEqual(r_pagos.status_code, 200)
            self.assertIn("999888", r_pagos.text)
            self.assertIn("$1.990", r_pagos.text)

    def test_trial_7_dias_activo_freemium(self) -> None:
        from datetime import datetime, timedelta, timezone
        import cuentas

        # 1. Signup / nuevo usuario con trial en el futuro
        futuro = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        self.assertTrue(cuentas.es_trial_activo(futuro))

        calc_activo = cuentas.calcular_plan_efectivo("free", None, futuro, "user")
        self.assertEqual(calc_activo["plan_efectivo"], "paid")
        self.assertTrue(calc_activo["es_trial"])
        self.assertTrue(calc_activo["trial_activo"])
        self.assertFalse(calc_activo["trial_vencido"])

    def test_trial_vencido_dia_8_vuelve_a_free(self) -> None:
        from datetime import datetime, timedelta, timezone
        import cuentas

        # 2. Día 8 simulado: fecha en el pasado
        pasado = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self.assertFalse(cuentas.es_trial_activo(pasado))

        calc_vencido = cuentas.calcular_plan_efectivo("free", None, pasado, "user")
        self.assertEqual(calc_vencido["plan_efectivo"], "free")
        self.assertFalse(calc_vencido["es_trial"])
        self.assertFalse(calc_vencido["trial_activo"])
        self.assertTrue(calc_vencido["trial_vencido"])

    def test_pago_mp_supersede_trial_a_paid_permanente(self) -> None:
        from datetime import datetime, timedelta, timezone
        import cuentas

        # 3. Usuario paga con MP -> plan paid permanente
        futuro = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        calc_paid = cuentas.calcular_plan_efectivo("paid", "2026-10-05T20:00:00Z", futuro, "user")
        self.assertEqual(calc_paid["plan_efectivo"], "paid")
        self.assertTrue(calc_paid["es_paid"])
        self.assertFalse(calc_paid["es_trial"])
        self.assertFalse(calc_paid["trial_activo"])

    def test_consumir_trial_activo_no_consume_cupo(self) -> None:
        import asyncio
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch, AsyncMock
        import cuentas

        futuro = (datetime.now(timezone.utc) + timedelta(days=6)).isoformat()
        uid = "00000000-0000-0000-0000-000000000002"

        # Mock respuesta de profile con trial activo
        class FakeResponse:
            status_code = 200
            def json(self):
                return [{"id": uid, "plan": "free", "paid_at": None, "trial_ends_at": futuro, "role": "user", "searches_used": 15}]

        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def get(self, *args, **kwargs):
                return FakeResponse()
            async def post(self, *args, **kwargs):
                return FakeResponse()

        with patch.object(cuentas, "cupo_on", return_value=True), \
             patch("httpx.AsyncClient", return_value=FakeClient()):
            res = asyncio.run(cuentas.consumir(uid, "yerba mate"))
            self.assertTrue(res["ok"])
            self.assertEqual(res["plan"], "paid")
            self.assertTrue(res["trial"])
            self.assertIsNone(res["remaining"])

    def test_contacto_soporte_visible_en_footer_y_legal(self) -> None:
        from fastapi.testclient import TestClient
        from app import app

        client = TestClient(app)
        for url in ["/", "/planes", "/terminos", "/privacidad", "/aviso-precios"]:
            r = client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertIn("baratoyaba@gmail.com", r.text, f"Mail no encontrado en {url}")

    def test_planes_modal_auth_modo_toggle_y_campos(self) -> None:
        from fastapi.testclient import TestClient
        from app import app

        client = TestClient(app)
        r = client.get("/planes")
        self.assertEqual(r.status_code, 200)
        self.assertIn('id="cuenta-toggle-modo"', r.text)
        self.assertIn('id="cuenta-submit"', r.text)
        self.assertIn('id="cuenta-email"', r.text)
        self.assertIn('id="cuenta-pass"', r.text)
        self.assertIn("7 días Plus gratis", r.text)
        self.assertIn("baratoyaba@gmail.com", r.text)

    def test_admin_usuario_no_encontrado_da_404(self) -> None:
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from app import app
        import cuentas

        async def fake_usuario(token):
            return {"id": "00000000-0000-0000-0000-000000000001", "email": "baratoyaba@gmail.com"}

        async def fake_es_admin(token, uid):
            return True

        async def fake_detalle_none(uid):
            return None

        client = TestClient(app)
        with patch.object(cuentas, "token_de", return_value="tok_admin"), \
             patch.object(cuentas, "cuentas_on", return_value=True), \
             patch.object(cuentas, "usuario", fake_usuario), \
             patch.object(cuentas, "es_admin", fake_es_admin), \
             patch.object(cuentas, "admin_detalle_usuario", fake_detalle_none):
            r = client.get("/admin/usuarios/00000000-0000-0000-0000-999999999999")
            self.assertEqual(r.status_code, 404)
            self.assertIn("Usuario no encontrado", r.text)

    def test_consumir_trial_vencido_bloquea_por_cupo(self) -> None:
        import asyncio
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch
        import cuentas

        pasado = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        uid = "00000000-0000-0000-0000-000000000003"

        class FakeResponseProfile:
            status_code = 200
            def json(self):
                return [{"id": uid, "plan": "free", "paid_at": None, "trial_ends_at": pasado, "role": "user", "searches_used": 5}]

        class FakeResponseRpcQuota:
            status_code = 200
            def json(self):
                return {"ok": False, "reason": "quota", "plan": "free", "used": 5, "remaining": 0, "limit": 5}

        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def get(self, *args, **kwargs):
                return FakeResponseProfile()
            async def post(self, *args, **kwargs):
                return FakeResponseRpcQuota()

        with patch.object(cuentas, "cupo_on", return_value=True), \
             patch("httpx.AsyncClient", return_value=FakeClient()):
            res = asyncio.run(cuentas.consumir(uid, "yerba mate"))
            self.assertFalse(res["ok"])
            self.assertEqual(res["reason"], "quota")


class ListaPrivacidadTest(unittest.TestCase):
    """P0: /api/lista y /api/alertas solo con sesión; ?email= y el email del body se ignoran."""

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path
        from fastapi.testclient import TestClient
        import app as app_mod
        import cuentas

        self.app_mod = app_mod
        self.cuentas = cuentas
        self.tmp = tempfile.TemporaryDirectory()
        self.p_db = patch.object(app_mod, "DB_PATH", Path(self.tmp.name) / "t.sqlite")
        self.p_db.start()
        self.client = TestClient(app_mod.app)

        async def fake_usuario(token):
            return {
                "tok-a": {"id": "u-a", "email": "a@example.com"},
                "tok-b": {"id": "u-b", "email": "b@example.com"},
            }.get(token)

        self.p_on = patch.object(cuentas, "cuentas_on", return_value=True)
        self.p_user = patch.object(cuentas, "usuario", fake_usuario)
        self.p_on.start()
        self.p_user.start()

    def tearDown(self) -> None:
        self.p_user.stop()
        self.p_on.stop()
        self.p_db.stop()
        self.tmp.cleanup()

    def _item(self, nombre: str, email: str | None = None) -> dict:
        d = {"nombre": nombre, "tienda": "Dia", "precio": 1000, "url": "https://example.test/x/" + nombre}
        if email:
            d["email"] = email
        return d

    def test_sin_sesion_401(self) -> None:
        c = self.client
        for r in (
            c.get("/api/lista?email=test@example.com"),
            c.get("/api/lista"),
            c.post("/api/lista", json=self._item("yerba", "test@example.com")),
            c.get("/api/alertas?email=test@example.com"),
            c.post("/api/alertas/revisar", json={"email": "test@example.com"}),
        ):
            self.assertEqual(r.status_code, 401, r.text)
            self.assertEqual(r.json(), {"ok": False, "reason": "auth", "error": "Sin sesión."})

    def test_token_invalido_401(self) -> None:
        r = self.client.get("/api/lista?email=a@example.com", headers={"Authorization": "Bearer nada"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["reason"], "auth")

    def test_sesion_a_no_ve_lista_de_b(self) -> None:
        c = self.client
        ha = {"Authorization": "Bearer tok-a"}
        hb = {"Authorization": "Bearer tok-b"}
        # B guarda algo; A intenta guardar "a nombre de B" con email en el body: queda en la lista de A.
        self.assertTrue(c.post("/api/lista", json=self._item("solo-b"), headers=hb).json()["ok"])
        self.assertTrue(c.post("/api/lista", json=self._item("de-a", "b@example.com"), headers=ha).json()["ok"])

        ra = c.get("/api/lista?email=b@example.com", headers=ha).json()
        self.assertTrue(ra["ok"])
        self.assertEqual(ra["email"], "a@example.com")
        self.assertEqual([i["nombre"] for i in ra["items"]], ["de-a"])
        self.assertNotIn("Quien escriba", ra["aviso"])

        rb = c.get("/api/lista", headers=hb).json()
        self.assertEqual([i["nombre"] for i in rb["items"]], ["solo-b"])

        al = c.get("/api/alertas?email=b@example.com", headers=ha).json()
        self.assertEqual([i["nombre"] for i in al["alertas"]], ["de-a"])

    def test_cliente_no_manda_mail_ni_texto_viejo(self) -> None:
        from pathlib import Path
        html = (Path(self.app_mod.__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("/api/lista?email=", html)
        self.assertNotIn("Quien escriba este mail", html)
        self.assertNotIn('id="lista-email"', html)


class LogoBTest(unittest.TestCase):
    """Marca oficial: ícono carrito + wordmark CSS, sin Inter, favicon nuevo."""

    def _client(self):
        from fastapi.testclient import TestClient
        from app import app

        return TestClient(app)

    def test_favicon_es_carrito(self) -> None:
        client = self._client()
        for path in ("/favicon.svg", "/favicon.ico"):
            r = client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn("#163300", r.text)
            self.assertIn("#9FE870", r.text)
            self.assertNotIn(">B<", r.text)
            self.assertNotIn("Inter", r.text)

    def test_lockup_en_paginas_publicas(self) -> None:
        client = self._client()
        paths = ("/", "/planes", "/promos-bancarias-supermercados", "/aviso-precios", "/terminos", "/privacidad")
        for path in paths:
            r = client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self._assert_lockup(r.text, path)
            self.assertNotIn("googletagmanager.com", r.text)
        missing = client.get("/no-existe-logo-b", headers={"Accept": "text/html"})
        self.assertEqual(missing.status_code, 404)
        self._assert_lockup(missing.text, "404")
        admin = client.get("/admin")
        self.assertEqual(admin.status_code, 403)
        self._assert_lockup(admin.text, "admin")

    def _assert_lockup(self, html: str, path: str) -> None:
        self.assertIn('aria-label="BaratoYa — inicio"', html, path)
        self.assertIn("/static/icon-carrito-b.svg", html, path)
        self.assertIn('class="b">Barato</span>', html, path)
        self.assertIn('class="y">Ya</span>', html, path)
        self.assertIn('href="/static/apple-touch-icon.png"', html, path)
        self.assertIn("/static/icon-32.png", html, path)
        self.assertNotIn("family=Inter", html, path)
        self.assertNotIn("fonts.googleapis.com", html, path)
        self.assertIn('font-family: "Libre Baskerville"', html, path)
        self.assertIn('font-family: "Atkinson Hyperlegible"', html, path)
        self.assertIn("font-display: swap", html, path)
        self.assertIn("/static/fonts/libre-baskerville-400.woff2", html, path)
        self.assertIn("/static/fonts/atkinson-hyperlegible-700.woff2", html, path)

    def test_assets_de_marca(self) -> None:
        client = self._client()
        for path in (
            "/static/icon-carrito-b.svg",
            "/static/icon-carrito-b-inv.svg",
            "/static/icon-32.png",
            "/static/apple-touch-icon.png",
            "/static/icon-512.png",
            "/static/baratoya-hero-landing.jpg",
            "/static/baratoya-hero-landing.webp",
            "/static/baratoya-hero-landing-640.webp",
            "/static/baratoya-hero-landing-720.webp",
            "/static/fonts/atkinson-hyperlegible-400.woff2",
            "/static/fonts/atkinson-hyperlegible-700.woff2",
            "/static/fonts/libre-baskerville-400.woff2",
            "/static/fonts/libre-baskerville-700.woff2",
        ):
            r = client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertGreater(len(r.content), 100, path)

    def test_ga_solo_con_measurement_id_valido(self) -> None:
        import os
        from unittest.mock import patch

        client = self._client()
        with patch.dict(os.environ, {"GA_MEASUREMENT_ID": "G-5X047YX59B"}):
            for path in ("/", "/planes", "/promos-bancarias-supermercados", "/privacidad"):
                r = client.get(path)
                self.assertIn("https://www.googletagmanager.com/gtag/js?id=G-5X047YX59B", r.text, path)
                self.assertIn("gtag('config', 'G-5X047YX59B')", r.text, path)
                self.assertIn("requestIdleCallback", r.text, path)
                self.assertNotIn('<script async src="https://www.googletagmanager.com/gtag/js', r.text, path)
            missing = client.get("/no-existe-ga", headers={"Accept": "text/html"})
            self.assertIn("G-5X047YX59B", missing.text)
            admin = client.get("/admin")
            self.assertEqual(admin.status_code, 403)
            self.assertIn("gtag('config', 'G-5X047YX59B')", admin.text)
        with patch.dict(os.environ, {"GA_MEASUREMENT_ID": 'G-5X047YX59B";alert(1)'}):
            r = client.get("/")
            self.assertNotIn("googletagmanager", r.text)
            self.assertNotIn("alert(1)", r.text)
        with patch.dict(os.environ, {"GA_MEASUREMENT_ID": ""}):
            self.assertNotIn("googletagmanager", client.get("/").text)


class PrivacidadHeroTest(unittest.TestCase):
    """Cookie de sesión + GA4 en /privacidad, aviso liviano, hero WebP y og en legales."""

    OG_JPG = 'property="og:image" content="https://baratoya.app/static/baratoya-hero-landing.jpg"'
    AVISO = "Usamos cookies de sesión y Google Analytics."

    def setUp(self) -> None:
        from fastapi.testclient import TestClient
        from app import app

        self.client = TestClient(app)

    def test_privacidad_documenta_cookie_y_analytics(self) -> None:
        html = self.client.get("/privacidad").text
        self.assertIn("baratoya_at", html)
        self.assertIn("Google Analytics", html)
        self.assertIn("cookie de sesión", html)
        self.assertIn("_ga", html)
        self.assertNotIn("cuando exista", html)

    def test_aviso_de_cookies_no_bloquea_y_enlaza_privacidad(self) -> None:
        for path in ("/", "/planes", "/promos-bancarias-supermercados", "/privacidad", "/terminos", "/aviso-precios"):
            html = self.client.get(path).text
            self.assertIn(self.AVISO, html, path)
            self.assertIn('class="cookie-note"', html, path)
            self.assertIn('href="/privacidad"', html, path)
        missing = self.client.get("/no-existe-aviso", headers={"Accept": "text/html"})
        self.assertEqual(missing.status_code, 404)
        self.assertIn(self.AVISO, missing.text)
        self.assertIn('<meta name="description" content="Esa dirección no está en BaratoYa. Volvé al inicio para comparar precios." />', missing.text)

    def test_hero_webp_en_home_y_og_sigue_jpg(self) -> None:
        html = self.client.get("/").text
        self.assertIn('srcset="/static/baratoya-hero-landing.webp 1280w', html)
        self.assertIn("/static/baratoya-hero-landing-640.webp 640w", html)
        self.assertIn("/static/baratoya-hero-landing-720.webp 720w", html)
        self.assertIn('type="image/webp"', html)
        self.assertIn('src="/static/baratoya-hero-landing.jpg"', html)
        self.assertIn('fetchpriority="high"', html)
        self.assertIn('rel="preload"', html)
        self.assertIn('as="image"', html)
        self.assertIn('alt="BaratoYa: precios de hoy en CABA"', html)
        self.assertIn('width="1280"', html)
        self.assertIn('height="720"', html)
        self.assertIn(self.OG_JPG, html)
        head = html.split("</head>", 1)[0]
        self.assertIn(self.OG_JPG, head)
        self.assertIn('name="twitter:image" content="https://baratoya.app/static/baratoya-hero-landing.jpg"', head)
        self.assertNotIn('og:image" content="https://baratoya.app/static/baratoya-hero-landing.webp"', head)
        title = html.split("<title>", 1)[1].split("</title>", 1)[0]
        desc = html.split('<meta name="description" content="', 1)[1].split('"', 1)[0]
        self.assertLessEqual(len(title), 60)
        self.assertGreaterEqual(len(desc), 140)
        self.assertLessEqual(len(desc), 155)
        self.assertIn(f'property="og:title" content="{title}"', html)
        self.assertIn(f'property="og:description" content="{desc}"', html)
        self.assertIn(f'name="twitter:title" content="{title}"', html)
        self.assertIn(f'name="twitter:description" content="{desc}"', html)

    def test_webp_se_sirve(self) -> None:
        r = self.client.get("/static/baratoya-hero-landing.webp")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers.get("content-type", "").startswith("image/webp"), r.headers.get("content-type"))
        self.assertGreater(len(r.content), 1000)
        self.assertTrue(r.content.startswith(b"RIFF"))

    def test_legales_tienen_og_image_jpg(self) -> None:
        for path in ("/terminos", "/privacidad", "/aviso-precios"):
            html = self.client.get(path).text
            self.assertEqual(html.count(self.OG_JPG), 1, path)


if __name__ == "__main__":
    unittest.main()


