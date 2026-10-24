"""Hubs de producto (leche, yerba, aceite, harina): por supermercado, diferencias, FAQ y meta.

Todo sale de las mismas ofertas que la lista de productos. Sin red: leen la captura.
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
from precios_seo import pagina_commodity, peso

SLUGS = ("leche", "yerba", "aceite", "harina")
HOY = date(2026, 10, 24)


def _ld(html: str) -> list[dict]:
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


class CommodityPorCadenaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        precios_seo.reiniciar_cache()
        cls.client = TestClient(app_mod.app)
        cls.vistas = {s: pagina_commodity(s, HOY) for s in SLUGS}

    def test_por_cadena_sale_de_las_ofertas(self) -> None:
        for slug, vista in self.vistas.items():
            assert vista is not None
            filas = vista["por_cadena"]
            tiendas = {o["tienda_id"] for p in vista["productos"] for o in p["ofertas"]}
            self.assertEqual({f["tienda_id"] for f in filas}, tiendas, slug)
            self.assertEqual(len(filas), vista["n_cadenas"], slug)
            medidas = precios_seo._medidas_commodity(vista["productos"])
            for f in filas:
                propias = [
                    (o["precio"] / (medidas[p["slug"]][1] if medidas else 1.0), o["precio"], p["nombre_visible"])
                    for p in vista["productos"] for o in p["ofertas"] if o["tienda_id"] == f["tienda_id"]
                ]
                self.assertEqual(f["n"], len(propias))
                mejor = min(propias)
                self.assertEqual(f["precio"], mejor[1], (slug, f["tienda"]))
                self.assertIn((f["precio"], f["producto"]), [(x[1], x[2]) for x in propias if x[0] == mejor[0]])
            claves = [f["unidad_valor"] if f["unidad_valor"] is not None else f["precio"] for f in filas]
            self.assertEqual(claves, sorted(claves), slug)
            self.assertTrue(filas[0]["barato"])

    def test_aceite_compara_por_litro(self) -> None:
        vista = self.vistas["aceite"]
        assert vista is not None
        self.assertEqual(vista["unidad"], "litro")
        self.assertTrue(vista["unidad_col"])
        for f in vista["por_cadena"]:
            self.assertTrue(f["unidad_txt"].startswith("$"))
        leche = self.vistas["leche"]
        assert leche is not None
        self.assertEqual(leche["unidad"], "litro")
        self.assertFalse(leche["unidad_col"])  # todo 1 L: la columna repetiría el precio

    def test_promo_de_hoy_es_la_del_hub(self) -> None:
        por_cadena = precios_seo.promos_de_hoy_por_cadena(HOY)
        for vista in self.vistas.values():
            assert vista is not None
            for f in vista["por_cadena"]:
                info = por_cadena.get(f["tienda_id"])
                if info is None:
                    self.assertIsNone(f["promo"])
                    continue
                self.assertEqual(f["promo"]["href"], info["href"])
                if info["top_txt"]:
                    self.assertIn(f"hasta {info['top_txt']}%", f["promo"]["linea"])

    def test_diferencias(self) -> None:
        for vista in self.vistas.values():
            assert vista is not None
            self.assertEqual(len(vista["diferencias"]), vista["n"])
            for d, p in zip(vista["diferencias"], vista["productos"]):
                self.assertEqual(d["low_txt"], peso(p["low"]))
                self.assertEqual(d["high_txt"], peso(p["high"]))
                self.assertEqual(d["dif"], p["high"] - p["low"])

    def test_faq_seis_con_numeros_de_la_tabla(self) -> None:
        for slug, vista in self.vistas.items():
            assert vista is not None
            qs = [q["q"] for q in vista["faq"]]
            self.assertEqual(len(qs), 6, slug)
            etiqueta = precios_seo._COMMODITY[slug]["etiqueta"]
            unidad = vista["unidad"]
            self.assertEqual(qs[2], f"¿Cuánto sale el {unidad} de {etiqueta} hoy?")
            self.assertTrue(qs[3].startswith("¿Cuánto cambia el precio "), qs[3])
            # Cada $ de las respuestas nuevas está en las ofertas (envase) o es litro/kilo o diferencia.
            permitidos = set()
            medidas = precios_seo._medidas_commodity(vista["productos"])
            for p in vista["productos"]:
                permitidos.add(peso(p["high"] - p["low"]))
                for o in p["ofertas"]:
                    permitidos.add(peso(o["precio"]))
                    if medidas:
                        permitidos.add(peso(precios_seo._precio_unidad(o["precio"], medidas[p["slug"]][1])))
            for q in vista["faq"][2:4]:
                for monto in re.findall(r"\$[\d.,]+\d", q["a"]):
                    self.assertIn(monto, permitidos, (slug, q["a"]))

    def test_meta_con_el_dato(self) -> None:
        for slug, vista in self.vistas.items():
            assert vista is not None
            d = vista["description"]
            self.assertGreaterEqual(len(d), 120, d)
            self.assertLessEqual(len(d), 158, d)
            top = vista["por_cadena"][0]
            self.assertIn(top["unidad_txt"], d)
            self.assertIn(top["tienda"], d)
            self.assertIn(f"{vista['n']} productos", d)

    def test_html(self) -> None:
        for slug in SLUGS:
            res = self.client.get(f"/precios/{slug}")
            self.assertEqual(res.status_code, 200)
            html = res.text
            vista = pagina_commodity(slug)
            assert vista is not None
            self.assertIn(f"<h2>{vista['anchor']} por supermercado</h2>", html)
            self.assertIn(f"Cuánto cambia el precio {vista['de_la']} entre supermercados", unescape(html))
            self.assertEqual(html.count('<table class="tabla">'), 2)
            self.assertIn('href="/promos-bancarias-supermercados"', html)
            for f in vista["por_cadena"]:
                self.assertIn(f'href="{f["href"]}"', html)
            ld = _ld(html)
            faq = next(x for x in ld if x["@type"] == "FAQPage")
            self.assertEqual(len(faq["mainEntity"]), 6)
            visible = unescape(html)
            for q in faq["mainEntity"]:
                self.assertIn(q["name"], visible)
            self.assertEqual(len(re.findall(r"<h1[ >]", html)), 1)
            self.assertIn(f'content="{vista["description"]}"', unescape(html))


if __name__ == "__main__":
    unittest.main()
