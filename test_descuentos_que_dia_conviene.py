"""/descuentos-supermercados: qué día conviene ir al supermercado + qué día descuenta cada banco. Sin red."""
from __future__ import annotations

import html as html_mod
import json
import os
import re
import unittest
from datetime import timedelta

os.environ.setdefault("BARATOYA_PRECIOS_OFFLINE", "1")

from fastapi.testclient import TestClient

import app as app_mod
import promos_hoy as ph


class QueDiaConvieneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app_mod.app)
        cls.vista = ph.pagina_seo_dias()
        cls.hoy = ph.hoy_art()
        cls.items = ph._items_publicos(cls.hoy)

    def test_dia_con_mas_promos_y_mayor_pct_salen_de_los_dias(self) -> None:
        dias = self.vista["dias"]
        conv = self.vista["conviene"]
        self.assertIsNotNone(conv)
        self.assertEqual(conv["mas_n"], max(d["n"] for d in dias))
        self.assertEqual({d["idx"] for d in conv["mas"]}, {d["idx"] for d in dias if d["n"] == conv["mas_n"]})
        pcts = [float(d["top_pct"]) for d in dias if d["top_pct"] is not None]
        self.assertEqual(conv["top_pct"], max(pcts))
        self.assertEqual(sum(1 for d in dias if d["mas"]), len(conv["mas"]))
        self.assertEqual(sum(1 for d in dias if d["top"]), len(conv["top"]))

    def test_calendario_bancos_coincide_con_las_promos(self) -> None:
        for b in self.vista["bancos"]:
            propios = [it for it in self.items if ph.banco_canonico(str(it.get("banco") or "")) == b["banco"]]
            self.assertTrue(propios, b["banco"])
            pcts = [ph._pct_de(it) for it in propios if ph._pct_de(it) is not None]
            self.assertEqual(b["mejor_pct"], max(pcts) if pcts else None, b["banco"])
            for nombre in b["mejores_dias"]:
                idx = next(s["idx"] for s in ph._DIAS_SEO if s["nombre"] == nombre)
                del_dia = [ph._pct_de(it) for it in propios if idx in it["day_ids"]]
                self.assertIn(b["mejor_pct"], del_dia, (b["banco"], nombre))
                cadenas = {str(it.get("cadena")) for it in propios if idx in it["day_ids"] and ph._pct_de(it) == b["mejor_pct"]}
                self.assertTrue(set(b["cadenas_mejor"]) <= cadenas | set(b["cadenas_mejor"]))
            dias = {s["nombre"] for s in ph._DIAS_SEO if any(s["idx"] in it["day_ids"] for it in propios)}
            self.assertEqual(set(b["dias"]), dias, b["banco"])
        orden = [-(b["mejor_pct"] or 0) for b in self.vista["bancos"]]
        self.assertEqual(orden, sorted(orden))

    def test_meta_con_el_dato_y_titulo(self) -> None:
        d = self.vista["description"]
        self.assertTrue(120 <= len(d) <= 155, d)
        if self.vista["conviene"] and self.vista["conviene"]["top_txt"]:
            self.assertIn(f"{self.vista['conviene']['top_txt']}%", d)
        self.assertLessEqual(len(self.vista["title"]), 60)

    def test_porcentajes_del_faq_estan_en_las_promos(self) -> None:
        pcts = {ph._pct_publico(ph._pct_de(it)) for it in self.items if ph._pct_de(it) is not None}
        for item in self.vista["faq"]:
            for p in re.findall(r"(\d+(?:,\d+)?)%", item["a"]):
                self.assertIn(p, pcts, item["q"])

    def test_html_tabla_bancos_y_faqpage(self) -> None:
        r = self.client.get("/descuentos-supermercados")
        self.assertEqual(r.status_code, 200)
        h = r.text
        self.assertEqual(len(re.findall(r"<h1[\s>]", h)), 1)
        self.assertIn('id="que-dia-conviene"', h)
        self.assertIn('id="por-banco"', h)
        self.assertIn('id="hoy"', h)
        filas = re.findall(r'<tr id="(lunes|martes|miercoles|jueves|viernes|sabado|domingo)"', h)
        self.assertEqual(len(filas), 7)
        for spec in ph._DIAS_SEO:
            self.assertIn(f'href="{ph.DESCUENTOS_PATH}/{spec["slug"]}"', h)
        bloques = re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S)
        faq = next(json.loads(b) for b in bloques if '"FAQPage"' in b)
        self.assertEqual(len(faq["mainEntity"]), len(self.vista["faq"]))
        self.assertGreaterEqual(len(faq["mainEntity"]), 5)
        visible = html_mod.unescape(h)
        for q in faq["mainEntity"]:
            self.assertIn(q["name"], visible)
            self.assertIn(q["acceptedAnswer"]["text"], visible)
        self.assertIn(html_mod.escape(self.vista["description"], quote=True), h)

    def test_otros_dias_de_la_semana(self) -> None:
        # Cualquier día de la semana de datos: meta en 120-155 (con el dato o la de respaldo).
        for k in range(7):
            v = ph.pagina_seo_dias(self.hoy - timedelta(days=k))
            self.assertTrue(120 <= len(v["description"]) <= 155, v["description"])


if __name__ == "__main__":
    unittest.main()
