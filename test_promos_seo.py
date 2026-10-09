"""Página pública de promos bancarias: HTML del archivo, sin precio de producto."""
from __future__ import annotations

import json
import re
import unittest
from html.parser import HTMLParser

from fastapi.testclient import TestClient

import app as app_mod
from promos_hoy import (
    DESCUENTOS_H1,
    DESCUENTOS_PATH,
    DESCUENTOS_TITLE,
    DESCUENTOS_URL,
    SEO_DESCRIPTION,
    SEO_PATH,
    SEO_TITLE,
    SEO_URL,
    cadenas_indexables,
    descripcion_cadena,
    fecha_datos_promos,
    fecha_larga,
    nav_dias,
    notas_honestidad,
    pagina_seo,
    pagina_seo_cadena,
    pagina_seo_dia,
    pagina_seo_dias,
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


def _claves_grupos(grupos: list[dict]) -> list:
    return [
        (
            g["chain_id"],
            [
                (p["banco"], p["oferta"], p.get("tope"), p.get("canal"), p.get("vigencia"), p.get("fuente"))
                for p in g["promos"]
            ],
        )
        for g in grupos
    ]


class DescuentosPorDiaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app_mod.app)
        cls.nav = nav_dias()
        cls.hub = pagina_seo_dias()
        cls.fecha = fecha_datos_promos()

    def test_siete_dias_200_y_slug_desconocido_404(self) -> None:
        self.assertEqual([d["slug"] for d in self.nav], [
            "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo",
        ])
        self.assertEqual(sum(1 for d in self.nav if d["hoy"]), 1)
        for dia in self.nav:
            res = self.client.get(dia["href"])
            self.assertEqual(res.status_code, 200, dia["slug"])
            self.assertIn("text/html", res.headers.get("content-type", ""))
        for malo in ("dia", "hoy", "miércoles", "sábado", "Miercoles", "lunes-2", "miercolesx"):
            res = self.client.get(f"{DESCUENTOS_PATH}/{malo}")
            self.assertEqual(res.status_code, 404, malo)
        self.assertEqual(self.client.get(f"{SEO_PATH}/dia").status_code, 200)
        hub = self.client.get(DESCUENTOS_PATH)
        self.assertEqual(hub.status_code, 200)
        self.assertIn("text/html", hub.headers.get("content-type", ""))

    def test_mismo_filtro_que_el_hub_de_promos(self) -> None:
        bloques = {b["dia"]: b for b in pagina_seo()["por_dia"]}
        for dia in self.nav:
            vista = pagina_seo_dia(dia["slug"])
            self.assertIsNotNone(vista)
            bloque = bloques.get(dia["nombre"])
            self.assertIsNotNone(bloque, dia["slug"])
            self.assertEqual(_claves_grupos(vista["cadenas"]), _claves_grupos(bloque["cadenas"]))
            self.assertGreater(vista["n"], 0, dia["slug"])
            self.assertGreater(vista["cadenas_n"], 0, dia["slug"])

    def test_seo_de_cada_dia(self) -> None:
        titulos = []
        for dia in self.nav:
            vista = pagina_seo_dia(dia["slug"])
            self.assertLessEqual(len(vista["title"]), 60)
            self.assertGreaterEqual(len(vista["description"]), 120)
            self.assertLessEqual(len(vista["description"]), 155)
            self.assertTrue(vista["title"].startswith("Descuentos en supermercados los "))
            self.assertIn("| BaratoYa", vista["title"])
            self.assertEqual(vista["h1"], f"Descuentos en supermercados los {dia['plural']} en CABA")
            self.assertTrue(vista["h1"].endswith("en CABA"))
            self.assertEqual(vista["canonical"], dia["url"])
            self.assertTrue(vista["canonical"].startswith("https://baratoya.app/descuentos-supermercados/"))
            titulos.append(vista["title"])
            html = self.client.get(dia["href"]).text
            self.assertIn(f"<title>{vista['title']}</title>", html)
            self.assertIn(f'<meta name="description" content="{vista["description"]}" />', html)
            self.assertIn(f'<link rel="canonical" href="{vista["canonical"]}" />', html)
            self.assertIn(f'property="og:title" content="{vista["title"]}"', html)
            self.assertIn(f'property="og:description" content="{vista["description"]}"', html)
            self.assertIn(f'property="og:url" content="{vista["canonical"]}"', html)
            self.assertIn('property="og:image" content="https://baratoya.app/static/baratoya-hero-landing.jpg"', html)
            parser = _H1()
            parser.feed(html)
            self.assertEqual(parser.h1, [vista["h1"]])
            self.assertIn(vista["linea"], html)
            self.assertIn("precio final estimado", html)
            self.assertIn("no acumula", html)
            self.assertIn(f'href="{SEO_PATH}"', html)
            self.assertIn(f'href="{DESCUENTOS_PATH}"', html)
            for cadena in vista["otras_cadenas"]:
                self.assertIn(f'href="{cadena["href"]}"', html)
            for otro in self.nav:
                self.assertIn(f'href="{otro["href"]}"', html)
            if self.fecha:
                self.assertIn(f"Actualizado el {fecha_larga(self.fecha)}.", html)
            self.assertNotIn("Tope no publicado", html)
            self.assertNotIn("Sin mínimo publicado", html)
            self.assertNotIn("día no publicado", html)
            self.assertNotIn("Vigencia no publicada", html)
            for fuera in ("Cordiez", "Toledo", "La Anónima", "Super Mami", "Comodín"):
                self.assertNotIn(f"<h3>{fuera}</h3>", html)
            fuente = next(
                (it["fuente"] for grupo in vista["cadenas"] for it in grupo["promos"] if it.get("fuente")),
                "",
            )
            self.assertTrue(fuente, dia["slug"])
            self.assertIn(f'href="{fuente}"', html)
            bloques = _ld_json(html)
            tipos = {b.get("@type") for b in bloques}
            self.assertEqual(tipos, {"FAQPage", "BreadcrumbList"})
            faq = next(b for b in bloques if b["@type"] == "FAQPage")
            self.assertEqual([q["name"] for q in faq["mainEntity"]], [item["q"] for item in vista["faq"]])
            self.assertTrue(any(q.startswith("¿Qué supermercado tiene más descuento los ") for q in (item["q"] for item in vista["faq"])))
            for item in vista["faq"]:
                self.assertIn(item["q"], html)
                self.assertIn(item["a"], html)
                respuesta = next(q for q in faq["mainEntity"] if q["name"] == item["q"])
                self.assertEqual(respuesta["acceptedAnswer"]["text"], item["a"])
            crumbs = next(b for b in bloques if b["@type"] == "BreadcrumbList")
            self.assertEqual(
                [c["item"] for c in crumbs["itemListElement"]],
                ["https://baratoya.app/", DESCUENTOS_URL, vista["canonical"]],
            )
            self.assertEqual(crumbs["itemListElement"][2]["name"], dia["nombre"])
            self.assertIn("Migas de pan", html)
        self.assertEqual(len(titulos), len(set(titulos)))

    def test_hub_marca_hoy_y_enlaza_los_siete(self) -> None:
        self.assertLessEqual(len(DESCUENTOS_TITLE), 60)
        self.assertGreaterEqual(len(self.hub["description"]), 120)
        self.assertLessEqual(len(self.hub["description"]), 155)
        self.assertEqual(self.hub["h1"], DESCUENTOS_H1)
        html = self.client.get(DESCUENTOS_PATH).text
        self.assertIn(f"<title>{self.hub['title']}</title>", html)
        self.assertIn(f'<link rel="canonical" href="{DESCUENTOS_URL}" />', html)
        parser = _H1()
        parser.feed(html)
        self.assertEqual(parser.h1, [DESCUENTOS_H1])
        nav = html.split('id="por-dia"', 1)[1].split("</ul>", 1)[0]
        self.assertEqual(nav.count("(hoy)"), 1)
        hoy = next(d for d in self.nav if d["hoy"])
        self.assertIn(f'href="{hoy["href"]}"', nav)
        self.assertIn('aria-current="date"', nav)
        for dia in self.nav:
            self.assertIn(f'href="{dia["href"]}"', nav)
        for bloque in self.hub["dias"]:
            self.assertIn(bloque["linea"], html)
        for cadena in cadenas_indexables():
            self.assertIn(f'href="{cadena["href"]}"', html)
        self.assertIn(f'href="{SEO_PATH}"', html)
        bloques = _ld_json(html)
        tipos = {b.get("@type") for b in bloques}
        self.assertEqual(tipos, {"FAQPage", "BreadcrumbList"})
        faq = next(b for b in bloques if b["@type"] == "FAQPage")
        self.assertEqual([q["name"] for q in faq["mainEntity"]], [item["q"] for item in self.hub["faq"]])
        crumbs = next(b for b in bloques if b["@type"] == "BreadcrumbList")
        self.assertEqual(
            [c["item"] for c in crumbs["itemListElement"]],
            ["https://baratoya.app/", DESCUENTOS_URL],
        )

    def test_links_internos_y_sitemap(self) -> None:
        hub_promos = self.client.get(SEO_PATH).text
        for dia in self.nav:
            self.assertIn(f'href="{dia["href"]}"', hub_promos)
        for cadena in cadenas_indexables():
            html = self.client.get(cadena["href"]).text
            for dia in self.nav:
                self.assertIn(f'href="{dia["href"]}"', html, cadena["slug"])
        home = self.client.get("/").text
        self.assertIn('href="/descuentos-supermercados"', home)
        site = self.client.get("/sitemap.xml")
        self.assertEqual(site.status_code, 200)
        self.assertIsNotNone(self.fecha)
        fecha = self.fecha.isoformat()
        self.assertIn(f"<loc>{DESCUENTOS_URL}</loc><lastmod>{fecha}</lastmod>", site.text)
        for dia in self.nav:
            self.assertIn(f"<loc>{dia['url']}</loc><lastmod>{fecha}</lastmod>", site.text)
        for cadena in cadenas_indexables():
            self.assertIn(f"<loc>{cadena['url']}</loc>", site.text)
        for url in (
            "https://baratoya.app/",
            SEO_URL,
            "https://baratoya.app/planes",
            "https://baratoya.app/aviso-precios",
            "https://baratoya.app/privacidad",
            "https://baratoya.app/terminos",
        ):
            self.assertIn(f"<loc>{url}</loc>", site.text)

    def test_planes_y_admin_nofollow(self) -> None:
        titulo = "BaratoYa Plus: planes y prueba gratis 7 días"
        h1 = "BaratoYa Plus: probalo gratis 7 días"
        desc = (
            "Planes de BaratoYa: probá Plus gratis 7 días, sin tarjeta. "
            "Después seguís gratis o te suscribís. Compará precios del súper en CABA."
        )
        self.assertLessEqual(len(titulo), 60)
        self.assertGreaterEqual(len(desc), 120)
        self.assertLessEqual(len(desc), 155)
        html = self.client.get("/planes").text
        self.assertIn(f"<title>{titulo}</title>", html)
        self.assertIn(f'<meta name="description" content="{desc}" />', html)
        self.assertIn(f'property="og:title" content="{titulo}"', html)
        self.assertIn(f'property="og:description" content="{desc}"', html)
        parser = _H1()
        parser.feed(html)
        self.assertEqual(parser.h1, [h1])
        self.assertIn("Empezar 7d gratis", html)
        self.assertIn('id="planes-cta-trial"', html)
        self.assertIn("7 días Plus gratis", html)
        with open("templates/index.html", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('<a href="/admin" id="nav-admin" hidden rel="nofollow">', src)


if __name__ == "__main__":
    unittest.main()
