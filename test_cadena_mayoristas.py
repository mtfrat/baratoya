"""Páginas de cadena (27/10): mayor % de la semana en la meta + bloque mayoristas.

GSC 26/10: /promos-bancarias-supermercados/maxiconsumo 1/98 @7,3 y la consulta
"maxiconsumo promociones bancarias" 0/19 @8,6. La meta decía "hasta 5%" y el 30% del
miércoles estaba solo en la tabla. Todo sale de las tarjetas publicadas. Sin red.
"""
from __future__ import annotations

import json
import os
import re
import unittest
from datetime import date, timedelta

os.environ["BARATOYA_PRECIOS_OFFLINE"] = "1"

from fastapi.testclient import TestClient

import app as app_mod
import promos_hoy as ph

MARTES = date(2026, 10, 27)


def _it(banco, days, percent=None, tope=None, tope_num=None, nota=None, chain="maxiconsumo"):
    it = {"chain_id": chain, "cadena": "Maxiconsumo", "banco": banco, "oferta": f"{percent}%" if percent else "3 cuotas sin interés",
          "dias": "", "day_ids": list(days), "canal": "sucursal"}
    if percent is not None:
        it["percent"] = float(percent)
    if tope:
        it["tope"] = tope
    if tope_num is not None:
        it["tope_num"] = float(tope_num)
    if nota:
        it["nota"] = nota
    return it


class MejorSemanaTest(unittest.TestCase):
    def test_nota_solo_dato_no_restringe(self):
        self.assertFalse(ph._restringe_comprador(_it("X", [2], 30, "tope $12.000", 12000, "Vigencia no informada en el legal")))
        self.assertFalse(ph._restringe_comprador(_it("X", [2], 30, "tope $12.000", 12000, "Sin tope informado")))
        self.assertTrue(ph._restringe_comprador(_it("X", [2], 30, "tope $12.000", 12000, "Solo sucursales de Chaco")))
        self.assertTrue(ph._restringe_comprador(_it("X", [2], 30, "tope $12.000", 12000, "Solo jubilados")))

    def test_elige_mayor_sin_condicion_y_con_tope(self):
        items = [
            _it("Mercado Pago", range(7), 5, "sin tope", nota="Sin tope de reintegro"),
            _it("BNA+ MODO (crédito Visa/Mastercard BNA)", [2], 30, "tope $12.000", 12000, "Vigencia no informada en el legal"),
            _it("Club X", [4], 40, "tope $5.000", 5000, "Solo socios Club X"),
            _it("Sin Tope SA", [5], 35, nota="Sin tope o tope no informado"),
        ]
        m = ph.mejor_semana_cadena(items, MARTES)
        self.assertEqual(m["pct"], 30.0)
        self.assertEqual(m["banco"], "BNA+ MODO")
        self.assertEqual(m["dias"], "el miércoles")
        self.assertEqual(m["tope"], "tope $12.000")
        self.assertEqual(m["nota"], "Vigencia no informada en el legal")

    def test_sin_aptos(self):
        self.assertIsNone(ph.mejor_semana_cadena([_it("Club", [1], 40, "tope $1", 1, "Solo socios")], MARTES))


class MetaTest(unittest.TestCase):
    sem = {"pct": 30.0, "pct_txt": "30%", "banco": "BNA+ MODO", "dias": "el miércoles", "day_ids": [2], "tope": "tope $12.000"}

    def test_semana_mayor_que_hoy(self):
        d = ph.descripcion_cadena_hoy("Maxiconsumo", "martes", 1, {"pct": "5%", "bancos": "Mercado Pago"}, self.sem, 1)
        self.assertTrue(d.startswith("Promociones bancarias Maxiconsumo hoy (martes)"))
        self.assertIn("hasta 5% con Mercado Pago", d)
        self.assertIn("En la semana, hasta 30% el miércoles con BNA+ MODO (tope $12.000)", d)
        self.assertLessEqual(len(d), 155)

    def test_hoy_es_el_mejor_dia(self):
        d = ph.descripcion_cadena_hoy("Maxiconsumo", "miércoles", 2, {"pct": "5%", "bancos": "Mercado Pago"}, self.sem, 2)
        self.assertIn("hoy (miércoles) en CABA: hasta 30% con BNA+ MODO (tope $12.000)", d)
        self.assertNotIn("En la semana", d)

    def test_hoy_igual_a_semana_no_cambia(self):
        sem = dict(self.sem, pct=5.0, pct_txt="5%")
        antes = ph.descripcion_cadena_hoy("Maxiconsumo", "martes", 1, {"pct": "5%", "bancos": "Mercado Pago"})
        self.assertEqual(ph.descripcion_cadena_hoy("Maxiconsumo", "martes", 1, {"pct": "5%", "bancos": "Mercado Pago"}, sem, 1), antes)

    def test_semana_real_todas_las_cadenas(self):
        hoy = ph.hoy_art()
        for c in ph.cadenas_indexables(hoy):
            for k in range(7):
                v = ph.pagina_seo_cadena(c["slug"], hoy + timedelta(days=k))
                if not v:
                    continue
                desc = v["description"]
                self.assertLessEqual(len(desc), 155, (c["slug"], k, desc))
                self.assertGreaterEqual(len(desc), 110, (c["slug"], k, desc))
                self.assertNotIn('"', desc)
                m = re.search(r"En la semana, hasta (\d+(?:,\d+)?)%", desc)
                if m:
                    pct = float(m.group(1).replace(",", "."))
                    items = [it for it in ph._items_publicos(hoy + timedelta(days=k)) if it["chain_id"] == c["chain_id"]]
                    self.assertIn(pct, [it.get("percent") for it in items])


class MayoristasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app_mod.app)

    def test_solo_en_mayoristas(self):
        hoy = ph.hoy_art()
        for c in ph.cadenas_indexables(hoy):
            filas = ph.mayoristas_semana(c["chain_id"], hoy)
            if c["chain_id"] not in ph._MAYORISTAS:
                self.assertEqual(filas, [])

    def test_pagina_maxiconsumo(self):
        v = ph.pagina_seo_cadena("maxiconsumo")
        if not v or not v["mayoristas"]:
            self.skipTest("sin dos mayoristas con promos esta semana")
        r = self.client.get(f"{ph.SEO_PATH}/maxiconsumo")
        self.assertEqual(r.status_code, 200)
        html = r.text
        self.assertIn('<h2 id="mayoristas">Promociones bancarias en mayoristas: Maxiconsumo y Makro</h2>', html)
        sec = html.split('id="mayoristas"', 1)[1].split("</ul>", 1)[0]
        self.assertIn(f'href="{ph.SEO_PATH}/makro"', sec)
        self.assertIn("<strong>Maxiconsumo</strong> (esta página)", sec)
        self.assertNotIn(f'href="{ph.SEO_PATH}/maxiconsumo"', sec)
        for m in v["mayoristas"]:
            self.assertEqual(m["n"], len([it for it in ph._items_publicos(ph.hoy_art()) if it["chain_id"] == m["chain_id"] and ph._es_nombre_banco(it["banco"])]))
        qs = [f["q"] for f in v["faq"]]
        self.assertEqual(len(qs), len(set(qs)))
        self.assertIn("¿Qué mayorista tiene más promociones bancarias esta semana: Maxiconsumo o Makro?", qs)
        self.assertIn("¿Qué día conviene comprar en Maxiconsumo?", qs)
        ld = [json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]
        faq = next(x for x in ld if x.get("@type") == "FAQPage")
        self.assertEqual([q["name"] for q in faq["mainEntity"]], qs)
        self.assertEqual(html.count("<h1"), 1)

    def test_otras_cadenas_sin_bloque(self):
        r = self.client.get(f"{ph.SEO_PATH}/jumbo")
        if r.status_code == 200:
            self.assertNotIn('id="mayoristas"', r.text)


if __name__ == "__main__":
    unittest.main()
