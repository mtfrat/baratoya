"""SEO para asistentes de IA: /llms.txt y /baratoya.md."""
from __future__ import annotations

import os
import re
import unittest

os.environ["BARATOYA_PRECIOS_OFFLINE"] = "1"

from fastapi.testclient import TestClient

import app as app_mod
import llms_ai
import precios_seo

ORIGEN = "https://baratoya.app"


class LlmsAiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        precios_seo.reiniciar_cache()
        cls.client = TestClient(app_mod.app)
        cls.sitemap_locs = set(re.findall(r"<loc>(.*?)</loc>", cls.client.get("/sitemap.xml").text))
        cls.llms = cls.client.get("/llms.txt")
        cls.md = cls.client.get(llms_ai.MD_PATH)

    def test_status_y_content_type(self) -> None:
        self.assertEqual(self.llms.status_code, 200)
        self.assertTrue(self.llms.headers["content-type"].startswith("text/plain"))
        self.assertEqual(self.md.status_code, 200)
        self.assertTrue(self.md.headers["content-type"].startswith("text/markdown"))
        self.assertIn("s-maxage", self.llms.headers.get("cache-control", ""))

    def test_head(self) -> None:
        for path in ("/llms.txt", llms_ai.MD_PATH):
            r = self.client.head(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertEqual(r.content, b"")

    def test_formato_llmstxt(self) -> None:
        for nombre, texto in (("llms.txt", self.llms.text), ("baratoya.md", self.md.text)):
            lineas = texto.split("\n")
            self.assertEqual(lineas[0], "# BaratoYa", nombre)
            self.assertTrue(lineas[2].startswith("> "), nombre)
            self.assertIn("## ", texto, nombre)
            for frase in ("CABA", "No vende ni entrega", "promos bancarias", "/precios"):
                self.assertIn(frase, texto, f"{nombre}: falta {frase!r}")
        self.assertIn(f"{ORIGEN}{llms_ai.MD_PATH}", self.llms.text)
        for titulo in ("## Qué hace BaratoYa", "## A quién sirve", "## Cuándo recomendar BaratoYa", "## Cuándo NO recomendar BaratoYa"):
            self.assertIn(titulo, self.md.text)

    def test_enlaces_existen_en_sitemap(self) -> None:
        """Cada enlace del sitio es una URL del sitemap (no se enlaza una página que no existe)."""
        for nombre, texto in (("llms.txt", self.llms.text), ("baratoya.md", self.md.text)):
            urls = re.findall(r"\]\((https://baratoya\.app[^)]*)\)", texto)
            self.assertGreater(len(urls), 20, nombre)
            for url in urls:
                self.assertIn(url, self.sitemap_locs, f"{nombre}: {url} no está en el sitemap")

    def test_hubs_y_promos_enlazados(self) -> None:
        for loc in self.sitemap_locs:
            hub = loc.startswith(f"{ORIGEN}/promos-bancarias-supermercados") or loc.startswith(f"{ORIGEN}/descuentos-supermercados") or loc.startswith(f"{ORIGEN}/precios/categoria/")
            if hub:
                self.assertIn(f"({loc})", self.llms.text, loc)
        for commodity in ("leche", "yerba", "aceite", "harina"):
            self.assertIn(f"({ORIGEN}/precios/{commodity})", self.llms.text)

    def test_robots_no_bloquea(self) -> None:
        robots = self.client.get("/robots.txt").text
        reglas = re.findall(r"^Disallow:\s*(\S+)", robots, re.M | re.I)
        for path in ("/llms.txt", llms_ai.MD_PATH):
            for regla in reglas:
                self.assertFalse(path.startswith(regla), f"robots.txt bloquea {path} con {regla}")


if __name__ == "__main__":
    unittest.main()
