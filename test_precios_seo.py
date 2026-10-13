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
        self.assertEqual(HUB_TITLE, "Comparar precios de supermercados hoy | BaratoYa")
        self.assertLessEqual(len(HUB_TITLE), 60)
        self.assertLessEqual(len(self.hub["description"]), 155)
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
        self.assertIn("Captura más reciente:", self.html)
        for vista in self.productos:
            self.assertIn(f'href="{vista["href"]}"', self.html)
            self.assertIn(vista["resumen"], self.html)

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
            self.assertEqual(
                [c["item"] for c in crumbs["itemListElement"]],
                ["https://baratoya.app/", "https://baratoya.app/precios", vista["canonical"]],
            )
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
        self.assertEqual(HUB_TITLE, "Comparar precios de supermercados hoy | BaratoYa")
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

    def test_sitemap_y_links(self) -> None:
        site = self.client.get("/sitemap.xml")
        self.assertEqual(site.status_code, 200)
        self.assertIn("application/xml", site.headers.get("content-type", ""))
        self.assertIn("<loc>https://baratoya.app/precios</loc>", site.text)
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
        self.assertIn('href="/precios"', home)
        for item in precios_seo.muestra_home():
            self.assertIn(f'href="{item["href"]}"', home)


if __name__ == "__main__":
    unittest.main()
