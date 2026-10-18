"""Enlazado interno: cada URL del sitemap tiene un camino rastreable en el HTML del servidor."""
from __future__ import annotations

import os
import re
import unittest
from collections import Counter

os.environ["BARATOYA_PRECIOS_OFFLINE"] = "1"

from fastapi.testclient import TestClient

import app as app_mod
import precios_seo
from precios_seo import vistas_publicadas

ORIGEN = "https://baratoya.app"

# Páginas con autoridad (home, hubs) y una de cada familia.
PAGINAS = (
    "/",
    "/promos-bancarias-supermercados",
    "/descuentos-supermercados",
    "/precios",
    "/planes",
    "/terminos",
)


def _hrefs(html: str) -> set[str]:
    return set(re.findall(r'href="(/[^"#?]*)"', html))


class ExplorarEnlacesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        precios_seo.reiniciar_cache()
        cls.client = TestClient(app_mod.app)
        cls.sitemap = cls.client.get("/sitemap.xml").text
        cls.locs = re.findall(r"<loc>(.*?)</loc>", cls.sitemap)
        cls.enlaces = app_mod.explorar_enlaces()

    def _familias(self) -> set[str]:
        """Cadenas, días y hubs de precio: las páginas del bloque Explorar."""
        return {e["href"] for grupo in self.enlaces.values() for e in grupo}

    def test_explorar_cubre_las_familias_del_sitemap(self) -> None:
        self.assertTrue(self.enlaces["cadenas"])
        self.assertEqual(len(self.enlaces["dias"]), 7)
        self.assertTrue(self.enlaces["precios"])
        paths = {loc.replace(ORIGEN, "") for loc in self.locs}
        for href in self._familias():
            self.assertIn(href, paths, href)
        for path in paths:
            if path.startswith(("/promos-bancarias-supermercados/", "/descuentos-supermercados/",
                                "/precios/categoria/")):
                self.assertIn(path, self._familias(), path)

    def test_hubs_y_familias_enlazan_todo_explorar(self) -> None:
        cadena = self.enlaces["cadenas"][0]["href"]
        dia = self.enlaces["dias"][0]["href"]
        cat = next(e["href"] for e in self.enlaces["precios"] if "/categoria/" in e["href"])
        ficha = vistas_publicadas()[-1]["href"]
        for path in (*PAGINAS, cadena, dia, cat, ficha):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, path)
            footer = res.text.split("<footer>", 1)[-1]
            self.assertIn('class="explorar"', footer, path)
            hrefs = _hrefs(footer)
            for href in self._familias() - {path}:
                self.assertIn(href, hrefs, f"{path} -> {href}")
            self.assertIn("/precios", hrefs, path)
            self.assertIn("/promos-bancarias-supermercados", hrefs, path)
            self.assertIn("/descuentos-supermercados", hrefs, path)
            self.assertNotIn(f'<li><a href="{path}">', footer, path)

    def test_404_tambien_tiene_explorar(self) -> None:
        res = self.client.get("/no-existe-esta-pagina")
        self.assertEqual(res.status_code, 404)
        self.assertIn('class="explorar"', res.text)

    def test_precios_hub_enlaza_cada_ficha(self) -> None:
        html = self.client.get("/precios").text
        for vista in vistas_publicadas():
            self.assertIn(f'href="{vista["href"]}"', html, vista["slug"])

    def test_cada_ficha_recibe_enlaces_de_otras_fichas(self) -> None:
        """La ventana circular de 'Otros productos' no deja fichas sin enlaces entre fichas."""
        productos = vistas_publicadas()
        entrantes: Counter[str] = Counter()
        for vista in productos:
            body = self.client.get(vista["href"]).text.split("<footer>", 1)[0]
            for href in _hrefs(body):
                if href != vista["href"]:
                    entrantes[href] += 1
        por_categoria = Counter(p["categoria"] for p in productos)
        for vista in productos:
            esperado = min(precios_seo.OTROS_MAX, por_categoria[vista["categoria"]] - 1)
            self.assertGreaterEqual(entrantes[vista["href"]], esperado, vista["slug"])

    def test_sitemap_todas_con_lastmod(self) -> None:
        urls = re.findall(r"<url>(.*?)</url>", self.sitemap, flags=re.S)
        self.assertEqual(len(urls), len(self.locs))
        self.assertEqual(len(self.locs), len(set(self.locs)))
        for url in urls:
            self.assertRegex(url, r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>", url)


if __name__ == "__main__":
    unittest.main()
