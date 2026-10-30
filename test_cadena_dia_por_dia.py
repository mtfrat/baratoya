"""Páginas de cadena (30/10): descuentos bancarios día por día que puede usar cualquiera.

GSC 29/10 (28 días): "disco promociones bancarias" 0/43 @9, "disco descuentos bancarios"
0/13 @8,9, "disco promociones bancarias jueves" 0/5 @7,6, "disco descuentos miercoles"
0/3 @7,7; /promos-bancarias-supermercados/disco 0/203 @8,8. Todo sale de las tarjetas
publicadas (misma regla que el bloque "para todos" de las páginas por día). Sin red.
"""
from __future__ import annotations

import json
import os
import re
import unittest
from datetime import timedelta

os.environ["BARATOYA_PRECIOS_OFFLINE"] = "1"

from fastapi.testclient import TestClient

import app as app_mod
import promos_hoy as ph


def _it(banco, percent=None, tope=None, tope_num=None, nota=None, days=(3,), canal="online y sucursal"):
    it = {"chain_id": "disco", "cadena": "Disco", "banco": banco,
          "oferta": f"{percent}%" if percent else "3 cuotas sin interés",
          "day_ids": list(days), "canal": canal}
    if percent is not None:
        it["percent"] = float(percent)
    if tope:
        it["tope"] = tope
    if tope_num is not None:
        it["tope_num"] = float(tope_num)
    if nota:
        it["nota"] = nota
    return it


class ParaTodosCadenaTest(unittest.TestCase):
    def test_un_dia_por_fila_con_rinde_hasta(self):
        hoy = ph.hoy_art()
        items = [
            _it("Banco Patagonia", 30, "tope $20.000", 20000, days=(5,)),
            _it("CencoPay Cuenta", 40, "tope $15.000", 15000, "Solo galletitas, cervezas y conservas", days=(4, 5)),
            _it("MODO", 20, "tope $25.000", 25000, days=(4, 5)),
            _it("CencoPay", 20, nota="Sin tope informado; excluye electro", days=(2,)),
            _it("Visa y Master", days=(0, 1, 2)),
        ]
        filas = ph.para_todos_cadena(items, hoy)
        self.assertEqual([f["slug"] for f in filas],
                         ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"])
        por = {f["slug"]: f for f in filas}
        self.assertEqual(por["sabado"]["mejor"]["pct"], 30.0)
        self.assertEqual(por["sabado"]["mejor"]["compra_txt"], "$66.667")
        # El 40% con productos seleccionados no entra, pero se muestra con su condición.
        self.assertEqual(por["viernes"]["mejor"]["bancos_txt"], "MODO")
        self.assertEqual(por["viernes"]["otra"]["pct_txt"], "40")
        self.assertIn("Solo galletitas", por["viernes"]["otra"]["motivo"])
        self.assertIsNone(por["miercoles"]["mejor"])
        self.assertEqual(por["miercoles"]["otra"]["motivo"], "tope no informado")
        self.assertIsNone(por["lunes"]["mejor"])
        self.assertEqual(por["lunes"]["cuotas_n"], 1)
        self.assertEqual(por["domingo"]["n"], 0)
        self.assertEqual(por[ph._DIAS_SEO[hoy.weekday()]["slug"]]["hoy"], True)

    def test_sin_ninguna_promo_para_todos_no_hay_bloque(self):
        items = [_it("CencoPay", 25, nota="Solo productos seleccionados"), _it("Visa y Master")]
        self.assertEqual(ph.para_todos_cadena(items, ph.hoy_art()), [])
        self.assertEqual(ph._faq_cadena_para_todos("Disco", []), [])

    def test_faq_nombra_los_dias(self):
        items = [
            _it("Banco Patagonia", 30, "tope $20.000", 20000, days=(5,)),
            _it("CencoPay", 25, nota="Solo productos seleccionados", days=(3,)),
        ]
        faq = ph._faq_cadena_para_todos("Disco", ph.para_todos_cadena(items, ph.hoy_art()))
        self.assertEqual(len(faq), 2)
        self.assertIn("el sábado 30% con Banco Patagonia, tope $20.000", faq[0]["a"])
        self.assertIn("El jueves solo tiene promos con condiciones", faq[0]["a"])
        self.assertIn("$66.667", faq[1]["a"])


class CadenaVivaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app_mod.app)

    def test_disco_tiene_el_bloque_y_la_faq(self):
        r = self.client.get("/promos-bancarias-supermercados/disco")
        self.assertEqual(r.status_code, 200)
        html = r.text
        v = ph.pagina_seo_cadena("disco")
        if not v["por_dia_todos"]:
            self.skipTest("esta semana Disco no publica promos para cualquiera")
        self.assertIn('<h2 id="dia-por-dia">Descuentos bancarios en Disco día por día', html)
        self.assertEqual(html.count("<h1"), 1)
        for d in ph._DIAS_SEO:
            self.assertIn(f'id="dia-{d["slug"]}"', html)
            self.assertIn(f'href="/descuentos-supermercados/{d["slug"]}"', html)
        self.assertIn('href="#dia-por-dia"', html)
        # El bloque va después de "Qué día conviene" y antes de la tabla completa.
        self.assertLess(html.index("Qué día conviene comprar en Disco"), html.index('id="dia-por-dia"'))
        self.assertLess(html.index('id="dia-por-dia"'), html.index("<h2>Por día de la semana</h2>"))
        lds = [json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]
        faq = next(l for l in lds if l.get("@type") == "FAQPage")
        qs = [q["name"] for q in faq["mainEntity"]]
        self.assertIn("¿Qué descuentos bancarios de Disco puede usar cualquiera, día por día?", qs)
        self.assertEqual(len(qs), len(set(qs)))
        # Las preguntas de la FAQ visible y del JSON-LD son las mismas.
        for q in qs:
            self.assertIn(q, html)

    def test_toda_la_semana_y_todas_las_cadenas(self):
        base = ph.hoy_art()
        for k in range(7):
            dia = base + timedelta(days=k)
            for c in ph.cadenas_indexables(dia):
                v = ph.pagina_seo_cadena(c["href"].rsplit("/", 1)[-1], dia)
                if v is None:
                    continue
                self.assertLessEqual(len(v["title"]), 60)
                self.assertLessEqual(len(v["description"]), 155)
                qs = [q["q"] for q in v["faq"]]
                self.assertEqual(len(qs), len(set(qs)), (c, dia))
                for f in v["por_dia_todos"]:
                    if f["mejor"] and f["mejor"]["compra_tope"]:
                        m = f["mejor"]
                        self.assertAlmostEqual(m["compra_tope"], m["tope_num"] * 100 / m["pct"])
                    if f["otra"] and f["mejor"]:
                        self.assertGreater(float(f["otra"]["pct_txt"].replace(",", ".")), f["mejor"]["pct"])


if __name__ == "__main__":
    unittest.main()
