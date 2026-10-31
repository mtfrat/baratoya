"""Fichas /precios/<producto>: precio promedio de la tabla y diferencia de cada cadena. Sin red."""
from __future__ import annotations

import json
import os
import re
import unittest

os.environ["BARATOYA_PRECIOS_OFFLINE"] = "1"

from fastapi.testclient import TestClient

import app as app_mod
import precios_seo


def _of(tienda: str, precio: float) -> dict:
    return {"tienda": tienda, "tienda_id": tienda.lower(), "precio": precio}


class PrecioPromedioTests(unittest.TestCase):
    def test_promedio_y_diferencias(self):
        r = precios_seo.precio_promedio("Cerveza Quilmes Botella 1 L", [
            _of("A", 3940), _of("B", 4590), _of("C", 4650), _of("D", 4650),
        ])
        self.assertEqual(r["promedio"], round((3940 + 4590 + 4650 + 4650) / 4))
        self.assertIn("El precio promedio de Cerveza Quilmes Botella 1 L hoy es $4.458, entre 4 supermercados.", r["promedio_txt"])
        self.assertIn("En A sale $518 menos que el promedio (12% menos).", r["promedio_txt"])
        self.assertIn("En C y D sale $192 más.", r["promedio_txt"])
        self.assertEqual([f["tienda"] for f in r["promedio_filas"]], ["A", "B", "C", "D"])
        self.assertEqual(r["promedio_filas"][0]["dif_txt"], "$518 menos que el promedio")
        self.assertEqual(r["promedio_filas"][1]["dif_txt"], "$132 más que el promedio")
        self.assertEqual(r["promedio_faq"]["q"], "¿Cuál es el precio promedio de Cerveza Quilmes Botella 1 L hoy?")
        self.assertTrue(r["promedio_faq"]["a"].endswith("sin promo bancaria."))

    def test_sin_promedio_con_dos_cadenas_o_mismo_precio(self):
        self.assertIsNone(precios_seo.precio_promedio("X", [_of("A", 100), _of("B", 200)])["promedio"])
        r = precios_seo.precio_promedio("X", [_of("A", 100), _of("B", 100), _of("C", 100)])
        self.assertEqual(r["promedio_txt"], "")
        self.assertIsNone(r["promedio_faq"])


class FichaPromedioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app_mod.app)

    def test_cada_ficha_con_3_cadenas_muestra_el_promedio_en_pagina_y_faq(self):
        vistas = [precios_seo.pagina_producto(v["slug"]) for v in precios_seo.vistas_publicadas()]
        con = [v for v in vistas if v and v["n"] >= 3 and v["high"] > v["low"]]
        self.assertTrue(con)
        for v in con:
            precios = [o["precio"] for o in v["ofertas"]]
            self.assertEqual(v["promedio"], round(sum(precios) / len(precios)), v["slug"])
            self.assertGreaterEqual(v["promedio"], v["low"])
            self.assertLessEqual(v["promedio"], v["high"])
            qs = [f["q"] for f in v["faq"]]
            self.assertIn(f"¿Cuál es el precio promedio de {v['nombre_visible']} hoy?", qs, v["slug"])
            self.assertEqual(len(qs), len(set(qs)), v["slug"])

    def test_html_promedio_y_faqpage_literal(self):
        v = precios_seo.pagina_producto("cerveza-quilmes-1l")
        if not v or not v["promedio_txt"]:
            self.skipTest("cerveza sin 3 cadenas en la foto")
        r = self.client.get("/precios/cerveza-quilmes-1l")
        self.assertEqual(r.status_code, 200)
        html = r.text
        self.assertEqual(html.count("<h1"), 1)
        self.assertIn('id="promedio"', html)
        self.assertIn("1 litro (1 L)", html)
        bloques = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
        faq = [json.loads(b) for b in bloques if '"FAQPage"' in b][0]
        nombres = [q["name"] for q in faq["mainEntity"]]
        self.assertIn(f"¿Cuál es el precio promedio de {v['nombre_visible']} hoy?", nombres)
        for q in faq["mainEntity"]:
            self.assertIn(q["name"], html.replace("&#39;", "'"))


if __name__ == "__main__":
    unittest.main()
