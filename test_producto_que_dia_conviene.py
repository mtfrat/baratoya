"""Fichas /precios/<producto>: "qué día conviene comprar" sale de las mismas tarjetas que el hub. Sin red."""
from __future__ import annotations

import json
import os
import re
import unittest
from datetime import date

os.environ["BARATOYA_PRECIOS_OFFLINE"] = "1"

from fastapi.testclient import TestClient

import app as app_mod
import precios_seo
import promos_hoy


def _hoy_con_datos() -> date:
    hoy = promos_hoy.hoy_art()
    if promos_hoy.mejor_dia_por_cadena(hoy):
        return hoy
    return date(2026, 10, 26)


class MejorDiaPorCadenaTests(unittest.TestCase):
    def setUp(self):
        self.hoy = _hoy_con_datos()
        self.por = promos_hoy.mejor_dia_por_cadena(self.hoy)
        if not self.por:
            self.skipTest("sin promos vigentes en el archivo")

    def test_es_el_maximo_de_la_tabla_de_la_semana(self):
        items = promos_hoy._items_publicos(self.hoy)
        matriz = promos_hoy._matriz_semana(items, self.hoy.weekday())
        filas = {f["chain_id"]: f for f in matriz["filas"]}
        for cid, info in self.por.items():
            fila = filas[cid]
            self.assertEqual(info["pct"], fila["mejor_pct"], cid)
            self.assertEqual([d["nombre"] for d in info["dias"]], fila["mejores_dias"], cid)

    def test_bancos_dan_ese_porcentaje_ese_dia(self):
        items = promos_hoy._items_publicos(self.hoy)
        for cid, info in self.por.items():
            for d in info["dias"]:
                del_dia = [it for it in items if it["chain_id"] == cid and d["idx"] in it["day_ids"]
                           and isinstance(it.get("percent"), (int, float)) and float(it["percent"]) == info["pct"]]
                self.assertTrue(del_dia, (cid, d["nombre"]))
                crudos = {str(it.get("banco") or "").strip() for it in del_dia}
                canon = {promos_hoy.banco_canonico(b) or b for b in crudos}
                for b in d["bancos"]:
                    self.assertIn(b, canon, (cid, d["nombre"], b))
                self.assertTrue(d["href"].startswith("/descuentos-supermercados/"))

    def test_solo_cadenas_con_pagina(self):
        indexables = {c["chain_id"] for c in promos_hoy.cadenas_indexables(self.hoy)}
        self.assertTrue(set(self.por) <= indexables)


class FichaConvieneTests(unittest.TestCase):
    def setUp(self):
        self.hoy = _hoy_con_datos()
        self.vistas = [precios_seo.pagina_producto(v["slug"], self.hoy) for v in precios_seo.vistas_publicadas()]
        if not any(v["conviene"] for v in self.vistas):
            self.skipTest("sin fichas con promo en % esta semana")

    def test_filas_son_cadenas_de_la_tabla_ordenadas_por_precio(self):
        por = promos_hoy.mejor_dia_por_cadena(self.hoy)
        por_nombre = {i["nombre"]: i for i in por.values()}
        for v in self.vistas:
            precios = {}
            for o in v["ofertas"]:
                precios.setdefault(o["tienda_id"], o["precio"])
            ids = [por_nombre[f["nombre"]]["chain_id"] for f in v["conviene"]]
            self.assertTrue(set(ids) <= set(precios), v["slug"])
            self.assertEqual([precios[i] for i in ids], sorted(precios[i] for i in ids), v["slug"])
            for f in v["conviene"]:
                info = por_nombre[f["nombre"]]
                self.assertEqual(f["pct_txt"], info["pct_txt"])
                self.assertEqual(f["precio_txt"], precios_seo.peso(precios[info["chain_id"]]))

    def test_faq_visible_igual_a_json_ld_y_pregunta_nueva(self):
        for v in self.vistas:
            ld = json.loads(v["ld_faq"])
            self.assertEqual([q["name"] for q in ld["mainEntity"]], [q["q"] for q in v["faq"]])
            nombre = v.get("nombre_visible") or v["nombre"]
            tiene = any(q["q"] == f"¿Qué día conviene comprar {nombre}?" for q in v["faq"])
            self.assertEqual(tiene, bool(v["conviene"]), v["slug"])
            if v["conviene"]:
                resp = next(q["a"] for q in v["faq"] if q["q"].startswith("¿Qué día conviene"))
                for f in v["conviene"]:
                    self.assertIn(f"{f['nombre']}: ", resp)
                    self.assertIn(f"hasta {f['pct_txt']}%", resp)
                self.assertIn("no está restada del precio", resp)

    def test_meta_largo_y_datos(self):
        for v in self.vistas:
            d = v["description"]
            self.assertLessEqual(len(d), 158, v["slug"])
            if "Qué día conviene" in d:
                self.assertGreaterEqual(len(d), 110)
                low = min(o["precio"] for o in v["ofertas"])
                self.assertIn(precios_seo.peso(low), d)
                pct = re.search(r"hasta (\d+(?:,\d+)?)%", d).group(1)
                self.assertEqual(pct, max((f["pct_txt"] for f in v["conviene"]),
                                          key=lambda t: float(t.replace(",", "."))))

    def test_html(self):
        v = next(v for v in self.vistas if v["conviene"])
        with TestClient(app_mod.app) as c:
            r = c.get(v["href"])
        self.assertEqual(r.status_code, 200)
        html = r.text
        nombre = v.get("nombre_visible") or v["nombre"]
        self.assertIn(f"<h2>Qué día conviene comprar {nombre}</h2>", html)
        self.assertIn('<table class="conviene">', html)
        self.assertEqual(html.count("<h1"), 1)
        self.assertIn(f'<meta name="description" content="{v["description"]}"', html.replace("&#39;", "'"))
        for f in v["conviene"]:
            for d in f["dias"]:
                self.assertIn(f'href="{d["href"]}"', html)
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
        tipos = [json.loads(b)["@type"] for b in blocks]
        self.assertIn("FAQPage", tipos)
        faq = next(json.loads(b) for b in blocks if json.loads(b)["@type"] == "FAQPage")
        self.assertTrue(any(q["name"].startswith("¿Qué día conviene comprar") for q in faq["mainEntity"]))


if __name__ == "__main__":
    unittest.main()
