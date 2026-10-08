"""Página pública de promos bancarias: HTML del archivo, sin precio de producto."""
from __future__ import annotations

import json
import re
import unittest
from html.parser import HTMLParser

from fastapi.testclient import TestClient

import app as app_mod
from promos_hoy import (
    SEO_DESCRIPTION,
    SEO_PATH,
    SEO_TITLE,
    SEO_URL,
    fecha_datos_promos,
    fecha_larga,
    pagina_seo,
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


class PromosPublicasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app_mod.app)
        cls.vista = pagina_seo()
        cls.res = cls.client.get(SEO_PATH)
        cls.html = cls.res.text

    def test_200_sin_sesion_y_sin_js(self) -> None:
        self.assertEqual(self.res.status_code, 200)
        self.assertIn("text/html", self.res.headers.get("content-type", ""))
        self.assertGreater(self.vista["n"], 0)
        self.assertGreater(self.vista["n_hoy"], 0)
        self.assertGreater(self.vista["cadenas_n"], 0)
        banco = self.vista["hoy_cadenas"][0]["promos"][0]["banco"]
        self.assertIn(banco, self.html)
        self.assertNotIn("Tope no publicado", self.html)
        self.assertNotIn("Sin mínimo publicado", self.html)
        self.assertNotIn("día no publicado", self.html)
        self.assertNotIn("Vigencia no publicada", self.html)

    def test_seo_basico(self) -> None:
        self.assertLessEqual(len(SEO_TITLE), 60)
        self.assertTrue(SEO_TITLE.lower().startswith("promos bancarias supermercados"))
        self.assertLessEqual(len(SEO_DESCRIPTION), 155)
        self.assertIn(f"<title>{SEO_TITLE}</title>", self.html)
        self.assertIn(f'<meta name="description" content="{SEO_DESCRIPTION}" />', self.html)
        self.assertIn(f'<link rel="canonical" href="{SEO_URL}" />', self.html)
        self.assertIn(f'property="og:title" content="{SEO_TITLE}"', self.html)
        self.assertIn(f'property="og:description" content="{SEO_DESCRIPTION}"', self.html)
        self.assertIn(f'property="og:url" content="{SEO_URL}"', self.html)
        self.assertIn('property="og:image"', self.html)
        parser = _H1()
        parser.feed(self.html)
        self.assertEqual(parser.h1, ["Promos bancarias supermercados hoy en CABA"])
        self.assertIn("promos bancarias supermercados", parser.h1[0].casefold())

    def test_fecha_sale_del_archivo(self) -> None:
        fecha = fecha_datos_promos()
        self.assertIsNotNone(fecha)
        texto = fecha_larga(fecha)
        self.assertEqual(self.vista["actualizado"], texto)
        self.assertIn(f"Actualizado el {texto}.", self.html)

    def test_cadenas_de_caba_en_el_html(self) -> None:
        cadenas = {g["cadena"] for dia in self.vista["por_dia"] for g in dia["cadenas"]}
        for nombre in ("Día", "Carrefour", "Coto Digital"):
            self.assertIn(nombre, cadenas)
            self.assertIn(f"<h3>{nombre}</h3>", self.html)
        for fuera in ("Cordiez", "Toledo", "La Anónima", "Super Mami", "Comodín"):
            self.assertNotIn(f"<h3>{fuera}</h3>", self.html)
            self.assertNotIn(f"<h4>{fuera}</h4>", self.html)

    def test_omite_tope_si_no_esta(self) -> None:
        vistos = 0
        for dia in self.vista["por_dia"]:
            for grupo in dia["cadenas"]:
                for item in grupo["promos"]:
                    self.assertTrue(item["banco"])
                    self.assertTrue(item["oferta"])
                    self.assertNotEqual(item.get("tope"), "Tope no publicado")
                    if "tope" not in item:
                        vistos += 1
        self.assertGreater(vistos, 0)

    def test_json_ld(self) -> None:
        bloques = _ld_json(self.html)
        tipos = {b.get("@type") for b in bloques}
        self.assertIn("FAQPage", tipos)
        self.assertIn("BreadcrumbList", tipos)
        faq = next(b for b in bloques if b["@type"] == "FAQPage")
        preguntas = [q["name"] for q in faq["mainEntity"]]
        self.assertEqual(preguntas, [item["q"] for item in self.vista["faq"]])
        for item in self.vista["faq"]:
            self.assertIn(item["q"], self.html)
            self.assertIn(item["a"], self.html)
            respuesta = next(q for q in faq["mainEntity"] if q["name"] == item["q"])
            self.assertEqual(respuesta["acceptedAnswer"]["text"], item["a"])
        crumbs = next(b for b in bloques if b["@type"] == "BreadcrumbList")
        self.assertEqual(crumbs["itemListElement"][0]["item"], "https://baratoya.app/")
        self.assertEqual(crumbs["itemListElement"][1]["item"], SEO_URL)
        self.assertIn("Migas de pan", self.html)

    def test_sitemap_y_links(self) -> None:
        site = self.client.get("/sitemap.xml")
        self.assertEqual(site.status_code, 200)
        self.assertIn(SEO_URL, site.text)
        home = self.client.get("/").text
        self.assertIn('href="/promos-bancarias-supermercados"', home)
        self.assertIn("Promos de banco, juntas.", home)
        parser = _H1()
        parser.feed(home)
        self.assertEqual(parser.h1, ["Compará precios del súper, hoy por cadena"])
        self.assertIn("Probar 7d Plus gratis", home)
        self.assertIn('id="hero-cta-trial"', home)
        for path in ("/", "/planes", "/privacidad", "/terminos", "/aviso-precios"):
            html = self.client.get(path).text
            self.assertIn('href="/promos-bancarias-supermercados"', html, path)

    def test_api_de_promos_sigue_pidiendo_sesion(self) -> None:
        r = self.client.get("/api/promos")
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
