"""/descuentos-supermercados/<día>: resumen por cadena, por banco y comparación de días. Sin red."""
from __future__ import annotations

import json
import os
import re
import unittest

os.environ.setdefault("BARATOYA_PRECIOS_OFFLINE", "1")

from fastapi.testclient import TestClient

import app as app_mod
import promos_hoy as ph


class BancoCanonicoTest(unittest.TestCase):
    def test_alias(self) -> None:
        casos = {
            "BNA+ MODO": "Banco Nación",
            "banco Nacion": "Banco Nación",
            "Nacion": "Banco Nación",
            "Banco Nación BNA": "Banco Nación",
            "Club La Nación": None,
            "Cuenta DNI (NFC Visa)": "Cuenta DNI (Banco Provincia)",
            "Banco Provincia - Cuenta DNI": "Cuenta DNI (Banco Provincia)",
            "Banco Credicoop (MODO)": "Banco Credicoop",
            "Galicia": "Banco Galicia",
            "Comafi Único": "Banco Comafi",
            "Buepp Banco Ciudad": "Banco Ciudad",
            "BANCOR": "Bancor (Banco de Córdoba)",
            "Banco Córdoba": "Bancor (Banco de Córdoba)",
            "Tarjeta Naranja X": "Naranja X",
            "Mercado Pago (tarjeta de crédito, QR)": "Mercado Pago",
            "CencoPay Cuenta": "CencoPay",
            "MODO": "MODO",
            "Visa, Mastercard, MODO": None,
            "Visa y Master": None,
            "Medios de Pago": None,
            "": None,
        }
        for raw, esperado in casos.items():
            self.assertEqual(ph.banco_canonico(raw), esperado, raw)


class ResumenDiaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app_mod.app)
        cls.hoy = ph.hoy_art()
        cls.items = ph._items_publicos(cls.hoy)

    def _dia_items(self, idx: int) -> list[dict]:
        return ph._items_de(self.items, idx)

    def test_por_cadena_sale_de_los_mismos_items(self) -> None:
        for spec in ph._DIAS_SEO:
            vista = ph.pagina_seo_dia(spec["slug"])
            items = self._dia_items(spec["idx"])
            self.assertEqual(sum(f["n"] for f in vista["por_cadena"]), len(items), spec["slug"])
            for f in vista["por_cadena"]:
                propios = [it for it in items if it["chain_id"] == f["chain_id"]]
                pcts = [float(it["percent"]) for it in propios if isinstance(it.get("percent"), (int, float)) and it["percent"] > 0]
                self.assertEqual(f["top_pct"], max(pcts) if pcts else None, (spec["slug"], f["cadena"]))
                for banco in f["bancos"]:
                    self.assertTrue(any(it["banco"] == banco and float(it.get("percent") or 0) == f["top_pct"] for it in propios))
            if vista["top_txt"]:
                self.assertEqual(vista["por_cadena"][0]["top_txt"], vista["top_txt"])

    def test_por_banco_sale_de_los_mismos_items(self) -> None:
        for spec in ph._DIAS_SEO:
            vista = ph.pagina_seo_dia(spec["slug"])
            items = self._dia_items(spec["idx"])
            for b in vista["por_banco"]:
                for c in b["cadenas"]:
                    propios = [
                        it for it in items
                        if it["chain_id"] == c["chain_id"] and ph.banco_canonico(it["banco"]) == b["banco"]
                    ]
                    self.assertTrue(propios, (spec["slug"], b["banco"], c["cadena"]))
                    pcts = [float(it["percent"]) for it in propios if isinstance(it.get("percent"), (int, float)) and it["percent"] > 0]
                    self.assertEqual(c["pct"], max(pcts) if pcts else None)

    def test_html_faq_y_meta(self) -> None:
        for spec in ph._DIAS_SEO:
            vista = ph.pagina_seo_dia(spec["slug"])
            self.assertGreaterEqual(len(vista["description"]), 120)
            self.assertLessEqual(len(vista["description"]), 155)
            html = self.client.get(f"{ph.DESCUENTOS_PATH}/{spec['slug']}").text
            self.assertIn(f"Resumen del {spec['nombre']}: el mayor descuento en cada supermercado", html)
            self.assertIn(f"Descuentos de los {spec['plural']} por banco o billetera", html)
            self.assertIn(f"Los {spec['plural']} comparados con los otros días", html)
            for otro in ph._DIAS_SEO:
                if otro["slug"] != spec["slug"]:
                    self.assertIn(f'href="{ph.DESCUENTOS_PATH}/{otro["slug"]}"', html)
            ld = [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]
            faq = next(b for b in ld if b["@type"] == "FAQPage")
            self.assertEqual(len(faq["mainEntity"]), len(vista["faq"]))
            preguntas = [q["q"] for q in vista["faq"]]
            if vista["top_txt"]:
                self.assertIn(f"¿Qué bancos tienen descuento en supermercados los {spec['plural']}?", preguntas)
                self.assertIn(f"¿Qué descuento da cada supermercado los {spec['plural']}?", preguntas)
            publicados = {ph._pct_publico(float(it["percent"])) for it in self._dia_items(spec["idx"]) if isinstance(it.get("percent"), (int, float))}
            for q in vista["faq"]:
                for pct in re.findall(r"(\d+(?:,\d+)?)%", q["a"]):
                    self.assertIn(pct, publicados, (spec["slug"], q["q"], pct))
            for pct in re.findall(r"(\d+(?:,\d+)?)%", vista["description"]):
                self.assertIn(pct, publicados, (spec["slug"], vista["description"]))


if __name__ == "__main__":
    unittest.main()
