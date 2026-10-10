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
