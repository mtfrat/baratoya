"""/promos-bancarias-supermercados: resumen de hoy, por banco, qué día conviene, FAQ y meta. Sin red."""
from __future__ import annotations

import json
import os
import re
import unittest
from datetime import date, timedelta

os.environ.setdefault("BARATOYA_PRECIOS_OFFLINE", "1")

from fastapi.testclient import TestClient

import app as app_mod
import promos_hoy as ph


def _ld(html: str) -> list[dict]:
    return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, flags=re.S)]


def _it(cid: str, cadena: str, banco: str, dias: list[int], pct: float | None = None, tope: str = "") -> dict:
    it = {"chain_id": cid, "cadena": cadena, "banco": banco, "oferta": "x", "day_ids": dias}
    if pct is not None:
        it["percent"] = pct
    if tope:
        it["tope"] = tope
    return it


class MatrizTest(unittest.TestCase):
    def test_mejor_dia_y_cuotas(self) -> None:
        items = [
            _it("coto", "Coto Digital", "Banco Nación", [0], 20),
            _it("coto", "Coto Digital", "Galicia", [2, 5], 30),
            _it("coto", "Coto Digital", "Naranja X", [3]),
        ]
        m = ph._matriz_semana(items, 2)
        self.assertEqual([d["nombre"] for d in m["dias"]], ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"])
        self.assertTrue(m["dias"][2]["hoy"])
        fila = m["filas"][0]
        self.assertEqual([c["txt"] for c in fila["celdas"]], ["20%", "—", "30%", "cuotas", "—", "30%", "—"])
        self.assertEqual(fila["mejores_dias"], ["miércoles", "sábado"])
        self.assertEqual(fila["mejor_txt"], "30")

    def test_top_y_meta(self) -> None:
        por = ph._resumen_por_cadena([
            _it("jumbo", "Jumbo", "CencoPay Cuenta", [4], 40),
            _it("disco", "Disco", "CencoPay", [4], 40),
            _it("coto", "Coto Digital", "Mercado Pago", [4], 25),
        ])
        top = ph._top_hub(por)
        self.assertEqual(top["txt"], "40")
        self.assertEqual(sorted(top["cadenas"]), ["Disco", "Jumbo"])
        self.assertEqual(top["banco"], "CencoPay")
        for n_hoy, cad in ((1, 1), (114, 8), (9999, 40)):
            texto = ph.descripcion_hub_hoy("miércoles", n_hoy, cad, top)
            self.assertTrue(120 <= len(texto) <= 155, (len(texto), texto))
            self.assertIn("40%", texto)
        self.assertEqual(ph.descripcion_hub_hoy("lunes", 5, 2, None), "")
        self.assertEqual(ph.descripcion_hub_hoy("lunes", 0, 0, top), "")
        # Bancos distintos en el empate: no se nombra ninguno.
        por2 = ph._resumen_por_cadena([
            _it("jumbo", "Jumbo", "Galicia", [4], 30),
            _it("coto", "Coto Digital", "BBVA", [4], 30),
        ])
        self.assertEqual(ph._top_hub(por2)["banco"], "")


class HubVivoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app_mod.app)

    def test_cada_dia_de_la_semana(self) -> None:
        base = ph.hoy_art()
        for k in range(7):
            dia = base + timedelta(days=k)
            v = ph.pagina_seo(dia)
            self.assertLessEqual(len(v["description"]), 155, dia)
            self.assertNotIn('"', v["description"])
            items = ph._items_publicos(dia)
            hoy = [it for it in items if dia.weekday() in it["day_ids"]]
            # El resumen sale de las mismas tarjetas que la lista de hoy.
            self.assertEqual(sum(f["n"] for f in v["por_cadena_hoy"]), len(hoy))
            for f in v["por_cadena_hoy"]:
                if f["top_pct"] is not None:
                    propios = [it for it in hoy if it["chain_id"] == f["chain_id"] and "percent" in it]
                    self.assertEqual(f["top_pct"], max(it["percent"] for it in propios))
            if v["top_hoy"]:
                self.assertIn(f"hasta {v['top_hoy']['txt']}%", v["description"])
            # La tabla de la semana coincide con el resumen de cada día.
            for fila in v["matriz"]["filas"]:
                for c in fila["celdas"]:
                    propios = [it for it in items if it["chain_id"] == fila["chain_id"] and c["idx"] in it["day_ids"]]
                    pcts = [it["percent"] for it in propios if "percent" in it]
                    self.assertEqual(c["pct"], max(pcts) if pcts else None)
            qs = [f["q"] for f in v["faq"]]
            self.assertEqual(len(qs), len(set(qs)))
            self.assertGreaterEqual(len(qs), 8)

    def test_html(self) -> None:
        res = self.client.get(ph.SEO_PATH)
        self.assertEqual(res.status_code, 200)
        html = res.text
        v = ph.pagina_seo()
        self.assertEqual(html.count("<h1>"), 1)
        self.assertIn("<h1>Promos bancarias supermercados hoy en CABA</h1>", html)
        self.assertIn(f"<title>{ph.SEO_TITLE}</title>", html)
        self.assertIn('id="resumen-hoy"', html)
        self.assertIn('id="por-banco"', html)
        self.assertIn('<h2 id="semana">Qué día conviene en cada supermercado</h2>', html)
        for d in ph.nav_dias():
            self.assertIn(f'href="{d["href"]}"', html)
        # La lista completa de la semana vive en las páginas por día: el hub no la duplica.
        self.assertNotIn("<h2>Por día de la semana</h2>", html)
        self.assertNotIn("<h4>", html)
        self.assertLess(len(res.content), 150_000)
        ld = _ld(html)
        faq = next(b for b in ld if b["@type"] == "FAQPage")
        nombres = [q["name"] for q in faq["mainEntity"]]
        self.assertEqual(nombres, [f["q"] for f in v["faq"]])
        for q in (
            "¿Qué supermercado tiene el mayor descuento bancario hoy?",
            "¿Qué bancos tienen descuento en supermercados hoy?",
            "¿Qué día conviene ir a cada supermercado?",
        ):
            self.assertIn(q, nombres)
            self.assertIn(f"<h3>{q}</h3>", html)
        self.assertIn(f'content="{v["description"]}"', html)


if __name__ == "__main__":
    unittest.main()
