"""Hubs de producto: precio por marca (tabla + FAQ) con los números de la lista.

Sin red: leen la captura.
"""
from __future__ import annotations

import json
import os
import re
import unittest
from datetime import date
from html import unescape

os.environ["BARATOYA_PRECIOS_OFFLINE"] = "1"

from fastapi.testclient import TestClient

import app as app_mod
import precios_seo
from precios_seo import pagina_commodity

SLUGS = ("leche", "yerba", "aceite", "harina")
HOY = date(2026, 10, 24)


def _ld(html: str) -> list[dict]:
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


class CommodityPorMarcaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        precios_seo.reiniciar_cache()
        cls.client = TestClient(app_mod.app)
        cls.vistas = {s: pagina_commodity(s, HOY) for s in SLUGS}

    def test_por_marca_sale_de_las_ofertas(self) -> None:
        for slug, vista in self.vistas.items():
            assert vista is not None
            filas = vista["por_marca"]
            self.assertGreaterEqual(len(filas), 2, slug)
            productos = vista["productos"]
            medidas = precios_seo._medidas_commodity(productos)
            marcas = {precios_seo._fold(precios_seo._marca_visible(p)) for p in productos}
            self.assertEqual({precios_seo._fold(f["marca"]) for f in filas}, marcas, slug)
            self.assertEqual(sum(f["n"] for f in filas), len(productos), slug)
            claves = []
            for f in filas:
                propios = [
                    (min(o["precio"] for o in p["ofertas"]) / (medidas[p["slug"]][1] if medidas else 1.0), p)
                    for p in productos
                    if precios_seo._fold(precios_seo._marca_visible(p)) == precios_seo._fold(f["marca"])
                ]
                mejor = min(v for v, _ in propios)
                claves.append(mejor)
                self.assertIn(f["producto"], [p["nombre_visible"] for v, p in propios if v == mejor])
                prod = next(p for _, p in propios if p["nombre_visible"] == f["producto"])
                self.assertEqual(f["precio"], prod["low"], (slug, f["marca"]))
                for tienda in re.split(r", | y ", f["tiendas_txt"].removesuffix(" y otras")):
                    self.assertIn(tienda, [o["tienda"] for o in prod["ofertas"] if o["precio"] == prod["low"]])
            self.assertEqual(claves, sorted(claves), slug)
            self.assertTrue(filas[0]["barata"])

    def test_marca_con_grafia_oficial(self) -> None:
        leche = self.vistas["leche"]
        assert leche is not None
        self.assertIn("La Serenísima", [f["marca"] for f in leche["por_marca"]])
        yerba = self.vistas["yerba"]
        assert yerba is not None
        self.assertIn("Taragüí", [f["marca"] for f in yerba["por_marca"]])
        harina = self.vistas["harina"]
        assert harina is not None
        favorita = [f for f in harina["por_marca"] if f["marca"] == "Favorita"]
        self.assertEqual(len(favorita), 1)  # FAVORITA y Favorita son la misma marca
        self.assertEqual(favorita[0]["n"], 2)

    def test_una_sola_marca_no_compara(self) -> None:
        leche = self.vistas["leche"]
        assert leche is not None
        solo = [p for p in leche["productos"] if precios_seo._marca_visible(p) == "La Serenísima"]
        self.assertEqual(precios_seo._por_marca_commodity(solo, None), [])
        sin_marca = [dict(leche["productos"][0], marca="")] + leche["productos"][1:]
        self.assertEqual(precios_seo._por_marca_commodity(sin_marca, None), [])

    def test_faq_marca_visible_y_en_ld(self) -> None:
        for slug in SLUGS:
            res = self.client.get(f"/precios/{slug}")
            self.assertEqual(res.status_code, 200, slug)
            html = res.text
            vista = pagina_commodity(slug)
            assert vista is not None
            q = f"¿Cuál es la marca de {slug} más barata hoy?"
            faq = next(i for i in vista["faq"] if i["q"] == q)
            self.assertEqual([i["q"] for i in vista["faq"]].index(q), 2)
            primera = vista["por_marca"][0]
            self.assertIn(primera["marca"], faq["a"])
            self.assertIn(primera["precio_txt"], faq["a"])
            self.assertIn("marcas propias", faq["a"])
            texto = unescape(html)
            self.assertIn(q, texto)
            self.assertIn(f'id="marcas"', html)
            self.assertIn(f"Precio {vista['de_la']} por marca", texto)
            self.assertEqual(texto.count("<h1"), 1)
            ld = [b for b in _ld(html) if b.get("@type") == "FAQPage"]
            self.assertEqual(len(ld), 1)
            nombres = [e["name"] for e in ld[0]["mainEntity"]]
            self.assertIn(q, nombres)
            self.assertEqual(len(nombres), len(vista["faq"]))

    def test_aceite_marca_por_litro(self) -> None:
        aceite = self.vistas["aceite"]
        assert aceite is not None
        faq = next(i for i in aceite["faq"] if i["q"].startswith("¿Cuál es la marca"))
        self.assertIn("por litro", faq["a"])
        self.assertIn("el envase", faq["a"])  # 900 ml y 1,5 L: muestra los dos números
        html = self.client.get("/precios/aceite").text
        self.assertIn("<th>Marca</th>", html)
        self.assertIn('<th class="num">Por litro</th>', html)

    def test_faq_precio_sin_captura_repetida(self) -> None:
        for slug, vista in self.vistas.items():
            assert vista is not None
            a = vista["faq"][0]["a"]
            fechas = re.findall(r"\d{1,2} \w{3} \d{4}, \d{2}:\d{2}", a)
            self.assertEqual(len(fechas), len(set(fechas)), (slug, a))

    def test_categoria_no_muestra_marcas(self) -> None:
        html = self.client.get("/precios/categoria/lacteos").text
        self.assertNotIn('id="marcas"', html)


if __name__ == "__main__":
    unittest.main()
