"""Páginas públicas de precio por producto. Sin red: leen la captura."""
from __future__ import annotations

import json
import os
import re
import unittest
from html.parser import HTMLParser

os.environ["BARATOYA_PRECIOS_OFFLINE"] = "1"

from fastapi.testclient import TestClient

import app as app_mod
import precios_seo
from precios_seo import (
    CATALOGO,
    HUB_H1,
    HUB_TITLE,
    MIN_CADENAS,
    PATH_HUB,
    armar_vista,
    pagina_categoria,
    pagina_commodity,
    pagina_precios,
    pagina_producto,
    resumen_precios,
    vistas_publicadas,
)


class _H1(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in = False
        self.h1: list[str] = []
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self._in = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "h1" and self._in:
            self.h1.append("".join(self._buf).strip())
            self._in = False

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)


def _ld_json(html: str) -> list[dict]:
    bloques = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>',
        html,
        flags=re.S,
    )
    return [json.loads(b) for b in bloques]


class PreciosPublicosTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        precios_seo.reiniciar_cache()
        cls.client = TestClient(app_mod.app)
        cls.hub = pagina_precios()
        cls.productos = vistas_publicadas()
        cls.res = cls.client.get(PATH_HUB)
        cls.html = cls.res.text

    def test_hay_productos_de_verdad(self) -> None:
        self.assertGreaterEqual(len(self.productos), 20)
        self.assertLessEqual(len(self.productos), 40)
        slugs = [p["slug"] for p in self.productos]
        self.assertEqual(len(slugs), len(set(slugs)))
        for spec in CATALOGO:
            self.assertNotIn("precio", spec)
        for vista in self.productos:
            self.assertGreaterEqual(vista["n"], MIN_CADENAS)
            self.assertGreater(vista["low"], 0)
            self.assertGreaterEqual(vista["high"], vista["low"])
            self.assertIn(vista["fecha"], vista["capturado_texto"])

    def test_hub_seo(self) -> None:
        self.assertEqual(self.res.status_code, 200)
        self.assertIn("text/html", self.res.headers.get("content-type", ""))
        self.assertEqual(HUB_TITLE, "Comparar precios de supermercados hoy en CABA | BaratoYa")
        self.assertLessEqual(len(HUB_TITLE), 60)
        self.assertGreaterEqual(len(HUB_TITLE), 45)
        self.assertIn("Comparar precios de supermercados hoy", HUB_TITLE)
        self.assertIn("CABA", HUB_H1)
        self.assertGreaterEqual(len(self.hub["description"]), 120)
        self.assertLessEqual(len(self.hub["description"]), 155)
        self.assertIn("Comparar precios de supermercados hoy", self.hub["description"])
        self.assertIn("CABA", self.hub["description"])
        self.assertIn("actualiza", self.hub["description"])
        self.assertNotIn("$", self.hub["description"])
        self.assertIn(f"<title>{HUB_TITLE}</title>", self.html)
        self.assertIn(f'<meta name="description" content="{self.hub["description"]}" />', self.html)
        self.assertIn(f'<link rel="canonical" href="{self.hub["canonical"]}" />', self.html)
        self.assertIn(f'property="og:title" content="{HUB_TITLE}"', self.html)
        self.assertIn(f'property="og:url" content="{self.hub["canonical"]}"', self.html)
        self.assertIn('property="og:image"', self.html)
        parser = _H1()
        parser.feed(self.html)
        self.assertEqual(parser.h1, [HUB_H1])
        self.assertNotIn("<script src=", self.html)
        self.assertIn(self.hub["intro"], self.html)
        self.assertIn("CABA", self.hub["intro"])
        self.assertIn("Se actualiza", self.hub["intro"])
        self.assertIn("Entrá por categoría o por producto", self.hub["intro"])
        self.assertIn("Captura más reciente:", self.html)
        self.assertIn('id="categorias"', self.html)
        arriba = self.html.split('id="categorias"', 1)[1].split("<h2", 1)[0]
        for grupo in self.hub["grupos"]:
            self.assertIn(f'href="{grupo["href"]}">{grupo["categoria"]}</a>', arriba)
        self.assertIn('href="/descuentos-supermercados/', arriba)
        self.assertIn(">descuentos en supermercados hoy</a>", arriba)
        self.assertIn('href="/promos-bancarias-supermercados/coto"', arriba)
        self.assertIn(">promos bancarias Coto</a>", arriba)
        self.assertIn('href="/promos-bancarias-supermercados/carrefour"', arriba)
        self.assertIn(">promos bancarias Carrefour</a>", arriba)
        preguntas = [item["q"] for item in self.hub["faq"]]
        self.assertEqual(
            preguntas,
            [
                "¿Cómo comparar precios de supermercados?",
                "¿Qué cadenas entran en la comparación?",
                "¿Cada cuánto se actualizan los precios?",
                "¿En qué se diferencia de las promos bancarias?",
            ],
        )
        bloques = _ld_json(self.html)
        faq = next(b for b in bloques if b["@type"] == "FAQPage")
        self.assertEqual([q["name"] for q in faq["mainEntity"]], preguntas)
        for item, publicado in zip(self.hub["faq"], faq["mainEntity"]):
            self.assertEqual(publicado["acceptedAnswer"]["text"], item["a"])
            self.assertIn(item["q"], self.html)
            visible = re.sub(r"<[^>]+>", "", item.get("html") or item["a"])
            self.assertEqual(visible, item["a"])
            self.assertIn(item["a"] if not item.get("html") else "promos bancarias de supermercados", self.html)
        self.assertIn('href="/promos-bancarias-supermercados"', self.html)
        self.assertIn('href="/descuentos-supermercados"', self.html)
        cadenas = self.hub["cadenas"]
        self.assertGreaterEqual(len(cadenas), 2)
        respuesta_cadenas = self.hub["faq"][1]["a"]
        for nombre in cadenas:
            self.assertIn(nombre, respuesta_cadenas)
        self.assertNotIn("Coto", respuesta_cadenas)
        for vista in self.productos:
            self.assertIn(f'href="{vista["href"]}"', self.html)
            self.assertIn(vista["resumen"], self.html)
        for grupo in self.hub["grupos"]:
            self.assertIn(f'<h2><a href="{grupo["href"]}">{grupo["categoria"]}</a></h2>', self.html)

    def test_cada_producto(self) -> None:
        for vista in self.productos:
            self.assertLessEqual(len(vista["title"]), 60, vista["slug"])
            self.assertTrue(vista["title"].endswith(" | BaratoYa"), vista["title"])
            self.assertLessEqual(len(vista["description"]), 155, vista["slug"])
            self.assertTrue(vista["h1"].startswith("Precio de "), vista["slug"])
            self.assertIn("hoy en supermercados", vista["h1"])
            res = self.client.get(vista["href"])
            self.assertEqual(res.status_code, 200, vista["slug"])
            html = res.text
            self.assertNotIn("<script src=", html)
            self.assertIn(f"<title>{vista['title']}</title>", html)
            self.assertIn(f'<meta name="description" content="{vista["description"]}" />', html)
            self.assertIn(f'<link rel="canonical" href="{vista["canonical"]}" />', html)
            self.assertIn(f'property="og:title" content="{vista["title"]}"', html)
            self.assertIn(f'property="og:url" content="{vista["canonical"]}"', html)
            parser = _H1()
            parser.feed(html)
            self.assertEqual(parser.h1, [vista["h1"]])
            self.assertIn(vista["resumen"], html)
            self.assertIn(f"Capturado el {vista['capturado_texto']}.", html)
            self.assertIn("Más barato", html)
            for oferta in vista["ofertas"]:
                self.assertIn(oferta["precio_txt"], html)
                self.assertIn(oferta["tienda"], html)
                self.assertIn(oferta["fecha"], html)
                self.assertGreater(oferta["precio"], 0)
            baratos = [o for o in vista["ofertas"] if o["barato"]]
            self.assertGreaterEqual(len(baratos), 1)
            self.assertEqual(baratos[0]["precio"], vista["low"])
            bloques = _ld_json(html)
            tipos = {b.get("@type") for b in bloques}
            self.assertEqual(tipos, {"Product", "FAQPage", "BreadcrumbList"})
            product = next(b for b in bloques if b["@type"] == "Product")
            self.assertEqual(product["name"], vista["nombre_visible"])
            self.assertIn(vista["nombre_visible"], vista["h1"])
            self.assertIn(vista["nombre_visible"], vista["description"])
            self.assertNotEqual(vista["nombre_visible"], vista["title"])
            offer = product["offers"]
            self.assertEqual(offer["@type"], "AggregateOffer")
            self.assertEqual(offer["priceCurrency"], "ARS")
            self.assertEqual(offer["lowPrice"], f"{vista['low']:.2f}")
            self.assertEqual(offer["highPrice"], f"{vista['high']:.2f}")
            self.assertEqual(offer["offerCount"], vista["n"])
            self.assertEqual(len(offer["offers"]), vista["n"])
            for crudo, publicado in zip(offer["offers"], vista["ofertas"]):
                self.assertEqual(crudo["price"], f"{publicado['precio']:.2f}")
                self.assertEqual(crudo["priceCurrency"], "ARS")
                self.assertEqual(crudo["seller"]["name"], publicado["tienda"])
            faq = next(b for b in bloques if b["@type"] == "FAQPage")
            self.assertEqual([q["name"] for q in faq["mainEntity"]], [item["q"] for item in vista["faq"]])
            for item in vista["faq"]:
                self.assertIn(item["q"], html)
                self.assertIn(item["a"], html)
            crumbs = next(b for b in bloques if b["@type"] == "BreadcrumbList")
            esperados = [
                "https://baratoya.app/",
                "https://baratoya.app/precios",
                "https://baratoya.app" + vista["categoria_href"],
            ]
            nombres = ["Inicio", "Comparar precios", vista["categoria"]]
            if vista["commodity_href"]:
                esperados.append("https://baratoya.app" + vista["commodity_href"])
                nombres.append(vista["commodity_nombre"])
            esperados.append(vista["canonical"])
            nombres.append(vista["nombre_visible"])
            self.assertEqual([c["item"] for c in crumbs["itemListElement"]], esperados)
            self.assertEqual([c["name"] for c in crumbs["itemListElement"]], nombres)
            self.assertIn(f'href="{vista["categoria_href"]}"', html)
            if vista["commodity_href"]:
                self.assertIn(f'href="{vista["commodity_href"]}"', html)
                self.assertIn(vista["commodity_anchor"], html)
            self.assertIn('href="/promos-bancarias-supermercados"', html)
            self.assertIn('href="/"', html)

    def test_no_publica_una_sola_cadena(self) -> None:
        spec = CATALOGO[0]
        raw = {
            "slug": spec["slug"],
            "nombre": "Leche Entera Sachet de prueba",
            "marca": "La Serenísima",
            "capturado": "2026-10-10T09:00:00-03:00",
            "capturado_texto": "10 oct 2026, 09:00 (Buenos Aires)",
            "ofertas": [{"tienda": "Día", "tienda_id": "dia", "precio": 1000, "url": "https://diaonline.supermercadosdia.com.ar/x"}],
        }
        self.assertIsNone(armar_vista(spec, {**raw, "nombre": "Leche Entera Sachet de prueba"}))
        # El nombre de prueba no pasa el filtro de la ficha real. Una ficha armada a mano
        # con el nombre que sí pasa y una sola cadena tampoco se publica.
        crudo = next(p for p in self.productos if p["slug"] == spec["slug"])
        self.assertIsNone(armar_vista(spec, {
            "nombre": crudo["nombre"],
            "marca": crudo["marca"],
            "capturado": crudo["capturado"],
            "capturado_texto": crudo["capturado_texto"],
            "ofertas": crudo["ofertas"][:1],
        }))

    def test_titulo_corto_conserva_nombre_y_marca(self) -> None:
        casos = {
            "Yerba Suave Playadito 1 kg": "Yerba Suave Playadito 1 kg",
            "Lavandina Ayudín Original 1 Lt.": "Lavandina Ayudín Original 1 L",
        }
        for nombre, visible in casos.items():
            titulo = precios_seo._titulo(nombre)
            self.assertEqual(titulo, f"Precio {visible} hoy | BaratoYa")
            self.assertLessEqual(len(titulo), 60)
            self.assertTrue(titulo.endswith(" | BaratoYa"))
            self.assertIn("Ayudín" if "Ayudín" in visible else "Playadito", titulo)

    def test_titulo_largo_saca_relleno_y_conserva_marca(self) -> None:
        casos = {
            "Leche Entera 3% Sachet 1 Lts La Serenísima": "Leche Sachet 1 L La Serenísima",
            "Gaseosa Coca-Cola Sabor Original 2.25 Lt.": "Coca-Cola 2.25 L",
            "Gaseosa Coca-Cola Sabor Original 2.25 L": "Coca-Cola 2.25 L",
            "Mermelada Sabor Durazno 454 Grs La Campagnola": "Mermelada Durazno 454 g La Campagnola",
            "Dulce de Leche La Serenisima Clasico 400 Gr.": "Dulce de Leche La Serenísima 400 g",
            "Harina de trigo 0000 Favorita fortificada 1 kg.": "Harina de trigo 0000 Favorita 1 kg",
        }
        for nombre, esperado in casos.items():
            titulo = precios_seo._titulo(nombre)
            self.assertLessEqual(len(titulo), 60, titulo)
            self.assertTrue(titulo.endswith(" | BaratoYa"), titulo)
            self.assertTrue(titulo.startswith("Precio "), titulo)
            corto = titulo.removeprefix("Precio ").removesuffix(" hoy | BaratoYa")
            self.assertEqual(corto, esperado, titulo)
            self.assertNotEqual(titulo, f"Precio {nombre} hoy")

    def test_titulo_no_termina_en_token_suelto(self) -> None:
        nombres = (
            "Leche Entera 3% Sachet 1 Lts La Serenísima",
            "Mermelada Sabor Durazno 454 Grs La Campagnola",
            "Queso Cremoso Untable Marca Propia Extra La",
            "Caja Grande Familiar Economica Pack De ColaLargaQueNoEntra",
            "Galletitas Dulces Rellenas Chocolate Y RellenoExtra",
            "Fideos Especiales Integrales Seleccion Premium Grande El",
        )
        for nombre in nombres:
            titulo = precios_seo._titulo(nombre)
            corto = titulo.removeprefix("Precio ").removesuffix(" hoy | BaratoYa")
            self.assertLessEqual(len(titulo), 60, titulo)
            self.assertFalse(precios_seo._cierra_mal(corto.split()), titulo)
            self.assertNotIn(corto.split()[-1].casefold().strip(".,"), {"la", "de", "el", "y"})

    def test_titulo_no_separa_numero_de_unidad(self) -> None:
        casos = (
            ("Gaseosa Coca-Cola Sabor Original 2.25 L", "2.25 L"),
            ("Gaseosa Coca-Cola Sabor Original 2.25 Lt.", "2.25 L"),
            ("Leche Entera 3% Sachet 1 Lts La Serenísima", "1 L"),
            ("Harina de trigo 0000 Favorita fortificada 1 kg.", "1 kg"),
            ("Dulce de Leche La Serenisima Clasico 400 Gr.", "400 g"),
            ("Bebida Energia Maxima Fresh 2.25 L ExtraGrande", "2.25 L"),
            ("Yerba Mate Seleccion Especial 1 kg PaqueteGrande", "1 kg"),
            ("Leche Parcial Descremada Sachet 1 Lts BotellaExtra", "1 L"),
        )
        for nombre, pegado in casos:
            titulo = precios_seo._titulo(nombre)
            self.assertIn(pegado, titulo, titulo)
            self.assertLessEqual(len(titulo), 60, titulo)
            corto = titulo.removeprefix("Precio ").removesuffix(" hoy | BaratoYa").split()
            partes = precios_seo._nombre_visible(nombre).split()
            for i, tok in enumerate(partes[:-1]):
                if not precios_seo._es_numero(tok) or not precios_seo._es_unidad(partes[i + 1]):
                    continue
                if tok not in corto:
                    continue
                j = corto.index(tok)
                self.assertEqual(corto[j + 1], partes[i + 1], titulo)
                self.assertNotEqual(corto[-1], tok, titulo)

    def test_titulo_prioriza_marca_sobre_descriptor(self) -> None:
        leche = precios_seo._titulo("Leche Entera 3% Sachet 1 Lts La Serenísima")
        self.assertIn("La Serenísima", leche)
        self.assertNotIn("Entera", leche)
        self.assertNotIn("3%", leche)

        coca = precios_seo._titulo("Gaseosa Coca-Cola Sabor Original 2.25 Lt.", "COKE/COCACOLA")
        self.assertIn("Coca-Cola", coca)
        self.assertNotIn("Sabor", coca)
        self.assertNotIn("Original", coca)
        self.assertNotIn("Gaseosa", coca)

        papel = precios_seo._titulo("Papel Higiénico Doble Hoja Fusion Higienol 4 Ud.", "HIGIENOL")
        self.assertIn("Higienol", papel)
        self.assertNotIn("Fusion", papel)
        self.assertLessEqual(len(papel), 60)

        playadito = precios_seo._titulo(
            "Yerba Mate Seleccion Especial Suave Playadito 1 kg",
            "Playadito",
        )
        self.assertIn("Playadito", playadito)
        self.assertLessEqual(len(playadito), 60)
        corto = playadito.removeprefix("Precio ").removesuffix(" hoy | BaratoYa")
        self.assertNotEqual(corto.split()[-1], "1")

    def test_hub_y_jsonld_no_cambian_con_el_titulo(self) -> None:
        self.assertEqual(HUB_TITLE, "Comparar precios de supermercados hoy en CABA | BaratoYa")
        self.assertEqual(self.hub["title"], HUB_TITLE)
        self.assertLessEqual(len(HUB_TITLE), 60)
        for slug in (
            "leche-la-serenisima-sachet-1l",
            "coca-cola-original-2-25l",
            "yerba-playadito-1kg",
        ):
            vista = next(p for p in self.productos if p["slug"] == slug)
            product = json.loads(vista["ld_product"])
            self.assertEqual(product["name"], vista["nombre_visible"])
            self.assertIn(vista["nombre_visible"], vista["h1"])
            self.assertLessEqual(len(vista["title"]), 60)
            self.assertTrue(vista["title"].endswith(" | BaratoYa"))
            self.assertNotEqual(product["name"], vista["title"])
            self.assertNotIn(" | BaratoYa", product["name"])

    def test_nombre_visible_ejemplos_serp(self) -> None:
        """Los títulos flojos del 2026-10-13 salen prolijos, sin tocar el dato."""
        casos = {
            "Leche La serenisima clásica 3% 1L": (
                "Leche La Serenísima clásica 3% 1 L",
                "Precio Leche La Serenísima clásica 3% 1 L hoy | BaratoYa",
            ),
            "Leche Descremada 1 Lts La Serenisima": (
                "Leche Descremada 1 L La Serenísima",
                "Precio Leche Descremada 1 L La Serenísima hoy | BaratoYa",
            ),
            "Dulce de Leche La Serenisima Clasico 400 Gr.": (
                "Dulce de Leche La Serenísima Clásico 400 g",
                "Precio Dulce de Leche La Serenísima 400 g hoy | BaratoYa",
            ),
            "Queso Rallado La Serenisima 130 gr": (
                "Queso Rallado La Serenísima 130 g",
                "Precio Queso Rallado La Serenísima 130 g hoy | BaratoYa",
            ),
            "Galletitas Crackers CRIOLLITAS 300g": (
                "Galletitas Crackers Criollitas 300 g",
                "Precio Galletitas Crackers Criollitas 300 g hoy | BaratoYa",
            ),
            "Cerveza QUILMES Botella 1 L": (
                "Cerveza Quilmes Botella 1 L",
                "Precio Cerveza Quilmes Botella 1 L hoy | BaratoYa",
            ),
            "Jabon en polvo ALA Bicarbonato 800 Gr.": (
                "Jabón en polvo Ala Bicarbonato 800 g",
                "Precio Jabón en polvo Ala Bicarbonato 800 g hoy | BaratoYa",
            ),
            "Leche Descremada La Serenísima 1sachet 1lt": (
                "Leche Descremada La Serenísima 1 sachet 1 L",
                "Precio Leche Descremada La Serenísima 1 L hoy | BaratoYa",
            ),
            "Te Común La Virginia 25saq": (
                "Té Común La Virginia 25 saquitos",
                "Precio Té Común La Virginia 25 saquitos hoy | BaratoYa",
            ),
            "Leche  Entera Ilolay U.a.t. Brik  1 Lt": (
                "Leche Entera Ilolay UAT Brik 1 L",
                "Precio Leche Entera Ilolay UAT Brik 1 L hoy | BaratoYa",
            ),
            "Yerba Mate Taragui 1 Kg": (
                "Yerba Mate Taragüí 1 kg",
                "Precio Yerba Mate Taragüí 1 kg hoy | BaratoYa",
            ),
            "Atun al natural": (
                "Atún al natural",
                "Precio Atún al natural hoy | BaratoYa",
            ),
            "Azucar Ledesma 1 kg": (
                "Azúcar Ledesma 1 kg",
                "Precio Azúcar Ledesma 1 kg hoy | BaratoYa",
            ),
        }
        for crudo, (visible, titulo) in casos.items():
            self.assertEqual(precios_seo._nombre_visible(crudo), visible, crudo)
            self.assertEqual(precios_seo._nombre_visible(visible), visible, crudo)
            self.assertEqual(precios_seo._titulo(crudo), titulo, crudo)
            self.assertLessEqual(len(titulo), 60, titulo)
            self.assertTrue(titulo.endswith("| BaratoYa"), titulo)
            self.assertNotIn("1sachet", titulo)
            self.assertNotIn("25saq", titulo)
        # Taragui y Taragüí escriben la misma marca oficial.
        self.assertEqual(
            precios_seo._nombre_visible("Yerba Mate Taragüí 1 kg"),
            "Yerba Mate Taragüí 1 kg",
        )
        self.assertEqual(
            precios_seo._nombre_visible("Yerba Mate Taragui 1 Kg"),
            precios_seo._nombre_visible("Yerba Mate Taragüí 1 kg"),
        )
        # El dato guardado y el slug no cambian. El SEO usa el nombre visible.
        por_slug = {p["slug"]: p for p in self.productos}
        self.assertEqual(len(CATALOGO), 39)
        self.assertEqual(len(self.productos), 39)
        crudo = json.loads((precios_seo.RUTA).read_text(encoding="utf-8"))
        guardado = {p["slug"]: p["nombre"] for p in crudo["productos"]}
        for spec in CATALOGO:
            vista = por_slug[spec["slug"]]
            self.assertEqual(vista["slug"], spec["slug"])
            # El nombre de la vista es el de la captura (espacios ya colapsados).
            # La grafía prolija vive en nombre_visible, no en el dato.
            self.assertEqual(
                vista["nombre"],
                " ".join(guardado[spec["slug"]].split()),
                spec["slug"],
            )
            self.assertLessEqual(len(vista["title"]), 60, vista["title"])
            self.assertTrue(vista["title"].endswith("| BaratoYa"), vista["title"])
            self.assertEqual(vista["nombre_visible"], precios_seo._nombre_visible(vista["nombre"]))
            product = json.loads(vista["ld_product"])
            self.assertEqual(product["name"], vista["nombre_visible"])
            self.assertEqual(vista["h1"], f"Precio de {vista['nombre_visible']} hoy en supermercados")
            self.assertIn(vista["nombre_visible"], vista["description"])
        jabon = por_slug["jabon-en-polvo-ala-bicarbonato-800g"]
        self.assertEqual(jabon["nombre"], "Jabon en polvo ALA Bicarbonato 800 Gr.")
        self.assertEqual(jabon["title"], "Precio Jabón en polvo Ala Bicarbonato 800 g hoy | BaratoYa")
        self.assertNotIn("ALA", json.loads(jabon["ld_product"])["name"])
        self.assertIn(jabon["nombre_visible"], self.html)
        self.assertNotIn("Jabon en polvo ALA", self.html)
        te = por_slug["te-la-virginia-comun"]
        self.assertIn("Té", te["title"])
        self.assertIn("25 saquitos", te["title"])
        self.assertNotIn("25saq", te["h1"])
        serenisima = [
            por_slug["leche-la-serenisima-clasica-1l"],
            por_slug["leche-la-serenisima-descremada-1l"],
            por_slug["dulce-de-leche-la-serenisima-400g"],
            por_slug["queso-rallado-la-serenisima-130g"],
        ]
        for vista in serenisima:
            self.assertIn("La Serenísima", vista["title"], vista["slug"])
            self.assertNotIn("Serenisima", vista["title"], vista["slug"])
            self.assertNotIn("serenisima", vista["title"], vista["slug"])

    def test_resumen_sale_de_los_numeros(self) -> None:
        ofertas = [
            {"tienda": "Día", "precio": 1000.0},
            {"tienda": "Jumbo", "precio": 2000.0},
        ]
        self.assertEqual(
            resumen_precios(ofertas),
            "Hoy el más barato es Día a $1.000, 50% menos que el más caro.",
        )
        self.assertIn(
            "todas las cadenas",
            resumen_precios([{"tienda": "Día", "precio": 1500.0}, {"tienda": "Vea", "precio": 1500.0}]),
        )

    def test_slug_desconocido_404(self) -> None:
        self.assertIsNone(pagina_producto("no-existe"))
        self.assertEqual(self.client.get("/precios/no-existe").status_code, 404)
        self.assertEqual(self.client.get("/precios/../secret").status_code, 404)

    def test_hubs_de_categoria(self) -> None:
        esperados = {
            "lacteos": "Precios de lácteos hoy en supermercados | BaratoYa",
            "almacen": "Precios de almacén hoy en supermercados | BaratoYa",
            "bebidas": "Precios de bebidas hoy en supermercados | BaratoYa",
            "limpieza": "Precios de limpieza hoy en supermercados | BaratoYa",
        }
        publicadas = {p["href"].rsplit("/", 1)[-1]: p for p in precios_seo.paginas_categoria()}
        self.assertEqual(set(publicadas), set(esperados))
        for slug, titulo in esperados.items():
            vista = pagina_categoria(slug)
            self.assertIsNotNone(vista, slug)
            assert vista is not None
            self.assertEqual(vista["title"], titulo)
            self.assertGreaterEqual(len(vista["title"]), 45, vista["title"])
            self.assertLessEqual(len(vista["title"]), 60, vista["title"])
            self.assertTrue(vista["title"].endswith(" | BaratoYa"), vista["title"])
            self.assertGreaterEqual(len(vista["description"]), 120, vista["description"])
            self.assertLessEqual(len(vista["description"]), 158, vista["description"])
            self.assertIn(str(vista["n"]), vista["description"])
            self.assertIn(str(vista["n_cadenas"]), vista["description"])
            self.assertGreaterEqual(vista["n"], 1)
            self.assertGreaterEqual(vista["n_cadenas"], MIN_CADENAS)
            self.assertGreaterEqual(len(vista["faq"]), 3)
            self.assertLessEqual(len(vista["faq"]), 4)
            res = self.client.get(vista["href"])
            self.assertEqual(res.status_code, 200, slug)
            html = res.text
            self.assertNotIn("<script src=", html)
            self.assertNotIn('content="noindex"', html)
            self.assertIn(f"<title>{vista['title']}</title>", html)
            self.assertIn(f'<meta name="description" content="{vista["description"]}" />', html)
            self.assertIn(f'<link rel="canonical" href="{vista["canonical"]}" />', html)
            self.assertIn(f'property="og:title" content="{vista["title"]}"', html)
            self.assertIn(f'property="og:description" content="{vista["description"]}"', html)
            self.assertIn(f'property="og:url" content="{vista["canonical"]}"', html)
            self.assertIn('property="og:image"', html)
            self.assertIn('property="og:type" content="website"', html)
            parser = _H1()
            parser.feed(html)
            self.assertEqual(parser.h1, [vista["h1"]])
            for producto in vista["productos"]:
                self.assertIn(f'href="{producto["href"]}"', html)
                self.assertIn(producto["nombre_visible"], html)
                self.assertIn(producto["mas_barato"], html)
                self.assertIn(producto["resumen"], html)
                self.assertEqual(
                    producto["mas_barato"],
                    precios_seo.texto_mas_barato(producto["ofertas"]),
                )
                for oferta in producto["ofertas"]:
                    if oferta["barato"]:
                        self.assertIn(oferta["tienda"], producto["mas_barato"])
                        self.assertIn(oferta["precio_txt"], producto["mas_barato"])
            bloques = _ld_json(html)
            tipos = {b.get("@type") for b in bloques}
            self.assertEqual(tipos, {"FAQPage", "ItemList", "BreadcrumbList"})
            faq = next(b for b in bloques if b["@type"] == "FAQPage")
            self.assertEqual(
                [q["name"] for q in faq["mainEntity"]],
                [item["q"] for item in vista["faq"]],
            )
            for item in vista["faq"]:
                self.assertIn(item["q"], html)
                self.assertIn(item["a"], html)
            crumbs = next(b for b in bloques if b["@type"] == "BreadcrumbList")
            self.assertEqual(
                [(c["name"], c["item"]) for c in crumbs["itemListElement"]],
                [
                    ("Inicio", "https://baratoya.app/"),
                    ("Precios", "https://baratoya.app/precios"),
                    (vista["categoria"], vista["canonical"]),
                ],
            )
            items = next(b for b in bloques if b["@type"] == "ItemList")
            self.assertEqual(items["numberOfItems"], vista["n"])
            self.assertEqual(
                [el["url"] for el in items["itemListElement"]],
                [p["canonical"] for p in vista["productos"]],
            )
            self.assertEqual(
                [el["name"] for el in items["itemListElement"]],
                [p["nombre_visible"] for p in vista["productos"]],
            )

    def test_categoria_desconocida_404(self) -> None:
        self.assertIsNone(pagina_categoria("no-existe"))
        self.assertIsNone(pagina_categoria("Lacteos"))
        res = self.client.get("/precios/categoria/no-existe")
        self.assertEqual(res.status_code, 404)
        self.assertIn('name="robots" content="noindex"', res.text)
        self.assertIn("Esa página no está.", res.text)
        self.assertIn("BaratoYa", res.text)

    def test_hubs_de_commodity(self) -> None:
        esperados = {
            "leche": "Precio de la leche hoy en supermercados | BaratoYa",
            "yerba": "Precio de la yerba hoy en supermercados | BaratoYa",
            "aceite": "Precio del aceite hoy en supermercados | BaratoYa",
            "harina": "Precio de la harina hoy en supermercados | BaratoYa",
        }
        publicadas = {p["slug"]: p for p in precios_seo.paginas_commodity()}
        self.assertEqual(set(publicadas), set(esperados))
        publicados = {p["slug"] for p in self.productos}
        for slug, titulo in esperados.items():
            vista = pagina_commodity(slug)
            self.assertIsNotNone(vista, slug)
            assert vista is not None
            self.assertEqual(vista["title"], titulo)
            self.assertLessEqual(len(vista["title"]), 60, vista["title"])
            self.assertGreaterEqual(len(vista["title"]), 45, vista["title"])
            self.assertTrue(vista["title"].endswith(" | BaratoYa"), vista["title"])
            self.assertEqual(vista["h1"], titulo.removesuffix(" | BaratoYa"))
            self.assertEqual(
                vista["faq"][0]["q"],
                {
                    "leche": "¿Cuál es el precio de la leche hoy?",
                    "yerba": "¿Cuál es el precio de la yerba hoy?",
                    "aceite": "¿Cuál es el precio del aceite hoy?",
                    "harina": "¿Cuál es el precio de la harina hoy?",
                }[slug],
            )
            self.assertEqual(
                vista["faq"][1]["q"],
                {
                    "leche": "¿Dónde está más barata la leche?",
                    "yerba": "¿Dónde está más barata la yerba?",
                    "aceite": "¿Dónde está más barato el aceite?",
                    "harina": "¿Dónde está más barata la harina?",
                }[slug],
            )
            self.assertGreaterEqual(len(vista["description"]), 120, vista["description"])
            self.assertLessEqual(len(vista["description"]), 158, vista["description"])
            self.assertIn(str(vista["n"]), vista["description"])
            self.assertIn(str(vista["n_cadenas"]), vista["description"])
            self.assertEqual(vista["n"], len(vista["productos"]))
            self.assertEqual(vista["n_cadenas"], precios_seo._n_cadenas(vista["productos"]))
            self.assertGreaterEqual(vista["n"], precios_seo.MIN_SKUS_COMMODITY)
            self.assertGreaterEqual(vista["n_cadenas"], precios_seo.MIN_CADENAS_COMMODITY)
            spec = precios_seo._COMMODITY[slug]
            self.assertEqual(
                {p["slug"] for p in vista["productos"]},
                {
                    s for s in publicados
                    if precios_seo._producto_en_commodity(s, spec)
                    and next(v["n"] for v in self.productos if v["slug"] == s) >= precios_seo.MIN_CADENAS_COMMODITY
                },
            )
            prefijo = slug + "-"
            for producto in vista["productos"]:
                self.assertTrue(producto["slug"].startswith(prefijo), producto["slug"])
            res = self.client.get(vista["href"])
            self.assertEqual(res.status_code, 200, slug)
            html = res.text
            self.assertNotIn("<script src=", html)
            self.assertNotIn('content="noindex"', html)
            self.assertIn(f"<title>{vista['title']}</title>", html)
            self.assertIn(f'<meta name="description" content="{vista["description"]}" />', html)
            self.assertIn(f'<link rel="canonical" href="{vista["canonical"]}" />', html)
            self.assertIn(f'property="og:title" content="{vista["title"]}"', html)
            self.assertIn(f'property="og:description" content="{vista["description"]}"', html)
            self.assertIn(f'property="og:url" content="{vista["canonical"]}"', html)
            parser = _H1()
            parser.feed(html)
            self.assertEqual(parser.h1, [vista["h1"]])
            for producto in vista["productos"]:
                self.assertIn(f'href="{producto["href"]}"', html)
                self.assertIn(producto["nombre_visible"], html)
            low = min(o["precio"] for p in vista["productos"] for o in p["ofertas"])
            precio = precios_seo.peso(low)
            fechas_low = {
                p["capturado_texto"]
                for p in vista["productos"]
                if any(o["precio"] == low for o in p["ofertas"])
            }
            bloques = _ld_json(html)
            tipos = {b.get("@type") for b in bloques}
            self.assertEqual(tipos, {"FAQPage", "ItemList", "BreadcrumbList"})
            faq = next(b for b in bloques if b["@type"] == "FAQPage")
            self.assertEqual(
                [q["name"] for q in faq["mainEntity"]],
                [item["q"] for item in vista["faq"]],
            )
            preguntas = {item["q"]: item["a"] for item in vista["faq"]}
            self.assertIn(precio, preguntas[vista["faq"][0]["q"]])
            self.assertIn(precio, preguntas[vista["faq"][1]["q"]])
            for fecha in fechas_low:
                self.assertIn(fecha, preguntas[vista["faq"][0]["q"]])
                self.assertIn(fecha, preguntas[vista["faq"][1]["q"]])
            for producto in vista["productos"]:
                for oferta in producto["ofertas"]:
                    if oferta["precio"] != low:
                        continue
                    self.assertIn(oferta["tienda"], preguntas[vista["faq"][0]["q"]])
                    self.assertIn(oferta["tienda"], preguntas[vista["faq"][1]["q"]])
                    self.assertIn(producto["nombre_visible"].rstrip("."), preguntas[vista["faq"][1]["q"]])
            for item in vista["faq"]:
                self.assertIn(item["q"], html)
                self.assertIn(item["a"], html)
            crumbs = next(b for b in bloques if b["@type"] == "BreadcrumbList")
            self.assertEqual(
                [(c["name"], c["item"]) for c in crumbs["itemListElement"]],
                [
                    ("Inicio", "https://baratoya.app/"),
                    ("Precios", "https://baratoya.app/precios"),
                    (vista["categoria"], "https://baratoya.app" + vista["padre"]["href"]),
                    (vista["titulo_miga"], vista["canonical"]),
                ],
            )
            items = next(b for b in bloques if b["@type"] == "ItemList")
            self.assertEqual(items["numberOfItems"], vista["n"])
            self.assertEqual(
                [el["url"] for el in items["itemListElement"]],
                [p["canonical"] for p in vista["productos"]],
            )
            self.assertIn(f'href="{vista["padre"]["href"]}"', html)

    def test_leche_solo_lista_leche_liquida(self) -> None:
        vista = pagina_commodity("leche")
        self.assertIsNotNone(vista)
        assert vista is not None
        excluidos = {
            "manteca-la-serenisima-200g",
            "dulce-de-leche-la-serenisima-400g",
            "yogur-ser-frutilla-190g",
            "queso-rallado-la-serenisima-130g",
        }
        publicados = {p["slug"] for p in self.productos}
        self.assertTrue(excluidos <= publicados)
        hub = {p["slug"] for p in vista["productos"]}
        self.assertTrue(hub.isdisjoint(excluidos))
        self.assertGreaterEqual(len(hub), 4)
        html = self.client.get("/precios/leche").text
        for slug in excluidos:
            self.assertNotIn(f'href="/precios/{slug}"', html)
        self.assertIn("Manteca, yogur, queso y dulce de leche no forman parte de esta lista.", html)
        lacteos = self.client.get("/precios/categoria/lacteos").text
        self.assertIn('href="/precios/leche"', lacteos)
        self.assertIn("Precio de la leche hoy", lacteos)
        precios = self.client.get("/precios").text
        self.assertIn('href="/precios/leche"', precios)
        for slug in hub:
            ficha = self.client.get(f"/precios/{slug}").text
            self.assertIn('href="/precios/leche"', ficha)
        manteca = self.client.get("/precios/manteca-la-serenisima-200g").text
        self.assertNotIn('href="/precios/leche"', manteca)

    def test_aceite_solo_girasol(self) -> None:
        vista = pagina_commodity("aceite")
        self.assertIsNotNone(vista)
        assert vista is not None
        hub = {p["slug"] for p in vista["productos"]}
        self.assertEqual(
            hub,
            {
                "aceite-natura-girasol-1-5l",
                "aceite-cocinero-girasol-900ml",
                "aceite-canuelas-girasol-900ml",
            },
        )
        self.assertEqual(vista["n_cadenas"], 8)
        publicados = {p["slug"] for p in self.productos}
        self.assertIn("aceite-oliva-natura-500ml", publicados)
        self.assertNotIn("aceite-oliva-natura-500ml", hub)
        for cadena in vista["productos"]:
            self.assertGreaterEqual(cadena["n"], precios_seo.MIN_CADENAS_COMMODITY)
        spec = precios_seo._COMMODITY["aceite"]
        for slug in hub:
            self.assertTrue(precios_seo._producto_en_commodity(slug, spec))
        for slug in (
            "aceite-oliva-natura-500ml",
            "aceite-aceitunas-nucu",
            "aceite-en-aerosol-natura",
            "aceitunas-verdes",
        ):
            self.assertFalse(precios_seo._producto_en_commodity(slug, spec), slug)
        html = self.client.get("/precios/aceite").text
        self.assertNotIn('href="/precios/aceite-oliva-natura-500ml"', html)
        self.assertIn("Aceite de oliva, aceitunas y aceite en aerosol no forman parte de esta lista.", html)
        almacen = self.client.get("/precios/categoria/almacen").text
        self.assertIn('href="/precios/aceite"', almacen)
        self.assertIn("Precio del aceite hoy", almacen)
        for slug in hub:
            ficha = self.client.get(f"/precios/{slug}").text
            self.assertIn('href="/precios/aceite"', ficha)
            self.assertIn("Precio del aceite hoy", ficha)
        oliva = self.client.get("/precios/aceite-oliva-natura-500ml").text
        self.assertNotIn('href="/precios/aceite"', oliva)

    def test_harina_solo_trigo(self) -> None:
        vista = pagina_commodity("harina")
        self.assertIsNotNone(vista)
        assert vista is not None
        hub = {p["slug"] for p in vista["productos"]}
        self.assertEqual(
            hub,
            {
                "harina-pureza-0000-1kg",
                "harina-favorita-000-1kg",
                "harina-favorita-0000-1kg",
            },
        )
        self.assertEqual(vista["n_cadenas"], 7)
        for producto in vista["productos"]:
            self.assertGreaterEqual(producto["n"], precios_seo.MIN_CADENAS_COMMODITY)
        spec = precios_seo._COMMODITY["harina"]
        for slug in (
            "harina-leudante-pureza-1kg",
            "harina-integral-1kg",
            "harina-de-maiz-1kg",
            "premezcla-para-pizza",
        ):
            self.assertFalse(precios_seo._producto_en_commodity(slug, spec), slug)
        html = self.client.get("/precios/harina").text
        self.assertIn("Harina leudante, integral y de maíz no forman parte de esta lista.", html)
        almacen = self.client.get("/precios/categoria/almacen").text
        self.assertIn('href="/precios/harina"', almacen)
        self.assertIn("Precio de la harina hoy", almacen)
        for slug in hub:
            ficha = self.client.get(f"/precios/{slug}").text
            self.assertIn('href="/precios/harina"', ficha)
            self.assertIn("Precio de la harina hoy", ficha)

    def test_bloque_precio_hoy(self) -> None:
        self.assertIn('id="precio-hoy"', self.html)
        bloque = self.html.split('id="precio-hoy"', 1)[1].split("</p>", 1)[0]
        self.assertTrue(bloque.startswith(">Precio hoy de "), bloque)
        enlaces = precios_seo.enlaces_commodity()
        self.assertEqual([e["slug"] if "slug" in e else e["href"].rsplit("/", 1)[-1] for e in enlaces], ["leche", "yerba", "aceite", "harina"])
        for enlace in enlaces:
            self.assertIn(f'href="{enlace["href"]}">{enlace["etiqueta"]}</a>', bloque)
        for slug in ("azucar", "arroz", "fideos", "cafe", "gaseosa", "agua", "papel-higienico", "detergente"):
            self.assertNotIn(f'href="/precios/{slug}"', bloque)

    def test_commodity_desconocida_404(self) -> None:
        self.assertIsNone(pagina_commodity("no-existe"))
        self.assertIsNone(pagina_commodity("manteca"))
        self.assertIsNone(pagina_commodity("Leche"))
        self.assertIsNone(pagina_commodity("dulce-de-leche"))
        for slug in (
            "azucar",
            "arroz",
            "fideos",
            "cafe",
            "gaseosa",
            "agua",
            "papel-higienico",
            "detergente",
        ):
            self.assertIsNone(pagina_commodity(slug), slug)
        for path in (
            "/precios/manteca",
            "/precios/azucar",
            "/precios/arroz",
            "/precios/fideos",
            "/precios/cafe",
            "/precios/gaseosa",
            "/precios/agua",
            "/precios/papel-higienico",
            "/precios/detergente",
            "/precios/dulce-de-leche",
        ):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 404, path)
            self.assertIn('name="robots" content="noindex"', res.text)

    def test_sitemap_y_links(self) -> None:
        site = self.client.get("/sitemap.xml")
        self.assertEqual(site.status_code, 200)
        self.assertIn("application/xml", site.headers.get("content-type", ""))
        self.assertIn(
            f"<loc>https://baratoya.app/precios</loc><lastmod>{self.hub['lastmod']}</lastmod>",
            site.text,
        )
        self.assertGreaterEqual(
            self.hub["lastmod"],
            max(p["lastmod"] for p in self.productos),
        )
        self.assertRegex(
            site.text,
            r"<loc>https://baratoya.app/</loc><lastmod>\d{4}-\d{2}-\d{2}</lastmod>",
        )
        head = self.client.head("/sitemap.xml")
        self.assertEqual(head.status_code, 200)
        self.assertIn("xml", head.headers.get("content-type", ""))
        self.assertEqual(head.content, b"")
        for pagina in precios_seo.paginas_categoria():
            self.assertIn(
                f"<loc>{pagina['canonical']}</loc><lastmod>{pagina['lastmod']}</lastmod>",
                site.text,
            )
        for pagina in precios_seo.paginas_commodity():
            self.assertIn(
                f"<loc>{pagina['canonical']}</loc><lastmod>{pagina['lastmod']}</lastmod>",
                site.text,
            )
        self.assertIn("<loc>https://baratoya.app/precios/leche</loc>", site.text)
        self.assertIn("<loc>https://baratoya.app/precios/yerba</loc>", site.text)
        self.assertIn("<loc>https://baratoya.app/precios/aceite</loc>", site.text)
        self.assertIn("<loc>https://baratoya.app/precios/harina</loc>", site.text)
        self.assertNotIn("<loc>https://baratoya.app/precios/manteca</loc>", site.text)
        for slug in ("azucar", "arroz", "fideos", "cafe", "gaseosa", "agua", "papel-higienico", "detergente"):
            self.assertNotIn(f"<loc>https://baratoya.app/precios/{slug}</loc>", site.text)
        for vista in self.productos:
            self.assertIn(
                f"<loc>{vista['canonical']}</loc><lastmod>{vista['lastmod']}</lastmod>",
                site.text,
            )
        for path in ("/", "/planes", "/privacidad", "/terminos", "/aviso-precios", "/promos-bancarias-supermercados"):
            html = self.client.get(path).text
            self.assertIn('href="/precios"', html, path)
        home = self.client.get("/").text
        parser = _H1()
        parser.feed(home)
        self.assertEqual(parser.h1, ["Compará precios del súper, hoy por cadena"])
        self.assertIn('href="/precios">comparar precios de supermercados</a>', home)
        descuentos = self.client.get("/descuentos-supermercados").text
        self.assertIn('href="/precios">comparar precios de supermercados</a>', descuentos)
        for path in (
            "/",
            "/precios",
            "/planes",
            "/descuentos-supermercados",
            "/promos-bancarias-supermercados",
            "/promos-bancarias-supermercados/coto",
            "/promos-bancarias-supermercados/carrefour",
            "/robots.txt",
        ):
            head = self.client.head(path)
            self.assertEqual(head.status_code, 200, path)
            self.assertEqual(head.content, b"", path)
        for path in (self.productos[0]["href"], "/precios/categoria/lacteos", "/descuentos-supermercados/lunes"):
            head = self.client.head(path)
            self.assertEqual(head.status_code, 200, path)
            self.assertEqual(head.content, b"", path)
        self.assertEqual(self.client.head("/api/promos").status_code, 405)
        self.assertEqual(self.client.head("/health").status_code, 405)
        for enlace in precios_seo.enlaces_categoria():
            self.assertIn(f'href="{enlace["href"]}"', home)
            self.assertIn(f"Precios de {enlace['etiqueta']}", home)
        for enlace in precios_seo.enlaces_commodity():
            self.assertIn(f'href="{enlace["href"]}"', home)
            self.assertIn(enlace["anchor"], home)
        for item in precios_seo.muestra_home():
            self.assertIn(f'href="{item["href"]}"', home)


if __name__ == "__main__":
    unittest.main()
