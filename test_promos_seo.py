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
    cadenas_indexables,
    descripcion_cadena,
    fecha_datos_promos,
    fecha_larga,
    notas_honestidad,
    pagina_seo,
    pagina_seo_cadena,
    titulo_cadena,
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
        for nombre, slug in (("Día", "dia"), ("Carrefour", "carrefour"), ("Coto Digital", "coto")):
            self.assertIn(nombre, cadenas)
            self.assertIn(
                f'<h3><a href="/promos-bancarias-supermercados/{slug}">{nombre}</a></h3>',
                self.html,
            )
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
        self.assertIn("Promos por supermercado", home)
        for cadena in cadenas_indexables():
            self.assertIn(f'href="{cadena["href"]}"', home)
        for path in ("/", "/planes", "/privacidad", "/terminos", "/aviso-precios"):
            html = self.client.get(path).text
            self.assertIn('href="/promos-bancarias-supermercados"', html, path)

    def test_api_de_promos_sigue_pidiendo_sesion(self) -> None:
        r = self.client.get("/api/promos")
        self.assertEqual(r.status_code, 401)


class PromosPorCadenaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app_mod.app)
        cls.cadenas = cadenas_indexables()
        cls.fecha = fecha_datos_promos()

    def test_solo_cadenas_con_datos(self) -> None:
        slugs = [c["slug"] for c in self.cadenas]
        self.assertEqual(
            slugs,
            ["dia", "carrefour", "coto", "jumbo", "disco", "vea", "mas-online", "makro", "maxiconsumo"],
        )
        for ausente in ("cordiez", "toledo", "josimar", "laanonima", "cotodigital", "coto-digital"):
            self.assertIsNone(pagina_seo_cadena(ausente))
            self.assertEqual(self.client.get(f"{SEO_PATH}/{ausente}").status_code, 404)

    def test_cada_pagina_es_html_crawlable(self) -> None:
        hub = {item["q"]: item["a"] for item in notas_honestidad()}
        self.assertIn("tope", hub["¿Qué es el tope?"].casefold())
        self.assertIn("sucursal", hub["¿Cómo se calcula el descuento?"].casefold())
        self.assertIn("no se aplica", hub["¿Cómo se calcula el descuento?"].casefold())
        for cadena in self.cadenas:
            vista = pagina_seo_cadena(cadena["slug"])
            self.assertIsNotNone(vista)
            self.assertLessEqual(len(vista["title"]), 60)
            self.assertLessEqual(len(vista["description"]), 155)
            self.assertEqual(vista["title"], titulo_cadena(cadena["nombre"]))
            self.assertTrue(vista["title"].startswith("Promos bancarias "))
            self.assertIn(cadena["nombre"], vista["title"])
            self.assertLessEqual(len(descripcion_cadena(cadena["nombre"], "miércoles")), 155)
            self.assertEqual(vista["h1"], f"Promos bancarias en {cadena['nombre']} hoy")
            self.assertEqual(vista["canonical"], cadena["url"])
            res = self.client.get(cadena["href"])
            self.assertEqual(res.status_code, 200, cadena["slug"])
            self.assertIn("text/html", res.headers.get("content-type", ""))
            html = res.text
            self.assertNotIn("<script src=", html)
            self.assertIn(f"<title>{vista['title']}</title>", html)
            self.assertIn(f'<meta name="description" content="{vista["description"]}" />', html)
            self.assertIn(f'<link rel="canonical" href="{vista["canonical"]}" />', html)
            self.assertIn(f'property="og:title" content="{vista["title"]}"', html)
            self.assertIn(f'property="og:url" content="{vista["canonical"]}"', html)
            self.assertIn('property="og:image"', html)
            self.assertIn('name="viewport"', html)
            parser = _H1()
            parser.feed(html)
            self.assertEqual(parser.h1, [vista["h1"]])
            self.assertIn("Empezar 7d gratis", html)
            self.assertIn('href="/planes"', html)
            self.assertIn("7 días Plus gratis", html)
            self.assertIn(f'href="{SEO_PATH}"', html)
            for otra in vista["otras"]:
                self.assertIn(f'href="{otra["href"]}"', html)
            self.assertNotIn(f'href="{cadena["href"]}"', html.split("<footer>", 1)[-1])
            for fuente in vista["fuentes"]:
                self.assertIn(f'href="{fuente}"', html)
            self.assertIn("<table>", html)
            self.assertNotIn("Tope no publicado", html)
            self.assertNotIn("Sin mínimo publicado", html)
            self.assertNotIn("día no publicado", html)
            self.assertNotIn("Vigencia no publicada", html)
            if vista["nombre_archivo"] != vista["nombre"]:
                self.assertIn(vista["nombre_archivo"], html)
            if vista["n_hoy"]:
                self.assertIn(vista["hoy_promos"][0]["banco"], html)
            else:
                self.assertIn("No hay promos vigentes cargadas para hoy.", html)
            bloques = _ld_json(html)
            tipos = {b.get("@type") for b in bloques}
            self.assertEqual(tipos, {"FAQPage", "BreadcrumbList"})
            faq = next(b for b in bloques if b["@type"] == "FAQPage")
            self.assertEqual([q["name"] for q in faq["mainEntity"]], [item["q"] for item in vista["faq"]])
            for item in vista["faq"]:
                self.assertIn(item["q"], html)
                self.assertIn(item["a"], html)
                respuesta = next(q for q in faq["mainEntity"] if q["name"] == item["q"])
                self.assertEqual(respuesta["acceptedAnswer"]["text"], item["a"])
            for nota in vista["notas"]:
                self.assertIn(nota["q"], html)
                self.assertIn(nota["a"], html)
            crumbs = next(b for b in bloques if b["@type"] == "BreadcrumbList")
            self.assertEqual(
                [c["item"] for c in crumbs["itemListElement"]],
                ["https://baratoya.app/", SEO_URL, vista["canonical"]],
            )
            self.assertEqual(crumbs["itemListElement"][2]["name"], cadena["nombre"])

    def test_sitemap_incluye_cadenas_con_lastmod(self) -> None:
        site = self.client.get("/sitemap.xml")
        self.assertEqual(site.status_code, 200)
        self.assertIsNotNone(self.fecha)
        encontrados = re.findall(
            r"<loc>(https://baratoya.app/promos-bancarias-supermercados/[a-z0-9-]+)</loc><lastmod>([^<]+)</lastmod>",
            site.text,
        )
        self.assertEqual(
            encontrados,
            [(c["url"], self.fecha.isoformat()) for c in self.cadenas],
        )
        self.assertIn(SEO_URL, site.text)
        self.assertNotIn(f"{SEO_URL}</loc><lastmod>", site.text)

    def test_hub_conserva_titulo_y_h1(self) -> None:
        html = self.client.get(SEO_PATH).text
        self.assertIn(f"<title>{SEO_TITLE}</title>", html)
        parser = _H1()
        parser.feed(html)
        self.assertEqual(parser.h1, ["Promos bancarias supermercados hoy en CABA"])


if __name__ == "__main__":
    unittest.main()
