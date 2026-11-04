"""Pruebas del pipeline semanal (scripts/promos): alarmas, carry verificado y extracción. Sin red."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.promos import dia, pages, validate
from scripts.promos.common import CADENAS, NOVIG, Ctx

W0 = date(2026, 11, 9)


def fila(chain: str, dias: list[int], vf: str = "2026-11-09", vt: str = "2026-11-15", **kw) -> dict:
    return dict(chain=chain, bank="Banco", kind="percent", value=10, days=dias, channel="both", cap=None, minimum=None,
                valid_from=vf, valid_to=vt, legal="", source_url="https://x", do_not_apply=None, ref="r") | kw


def semana(n_cenco: int = 12) -> list[dict]:
    rows = [fila(c, [1, 2, 3, 4, 5, 6, 7]) for c in CADENAS if c not in ("jumbo", "disco", "vea")]
    for c in ("jumbo", "disco", "vea"):
        rows += [fila(c, [1, 2, 3, 4, 5, 6]) for _ in range(n_cenco)]
    return rows


class AlarmasTest(unittest.TestCase):
    def prev(self) -> list[dict]:
        return [dict(r, valid_from="2026-11-02", valid_to="2026-11-08") for r in semana()]

    def test_semana_normal_sin_alarmas(self) -> None:
        al, _ = validate.alarmas(semana(), self.prev(), W0, date(2026, 11, 2))
        self.assertEqual(al, [])

    def test_cadena_vacia_es_alarma(self) -> None:
        rows = [r for r in semana() if r["chain"] != "cotodigital"]
        al, _ = validate.alarmas(rows, self.prev(), W0, date(2026, 11, 2))
        self.assertTrue(any(a.startswith("cotodigital: VACÍA") for a in al), al)

    def test_caida_fuerte_es_alarma(self) -> None:
        prev = self.prev() + [dict(fila("dia", [1, 2, 3, 4, 5, 6, 7]), valid_from="2026-11-02", valid_to="2026-11-08") for _ in range(9)]
        al, _ = validate.alarmas(semana(), prev, W0, date(2026, 11, 2))
        self.assertTrue(any(a.startswith("dia: cae") for a in al), al)

    def test_cencosud_flaco_un_dia_es_alarma(self) -> None:
        al, _ = validate.alarmas(semana(n_cenco=3), self.prev(), W0, date(2026, 11, 2))
        self.assertTrue(any("jumbo: sólo 3 promos" in a for a in al), al)

    def test_semana_de(self) -> None:
        self.assertEqual(validate.semana_de(self.prev()), date(2026, 11, 2))


class CtxTest(unittest.TestCase):
    def ctx(self) -> Ctx:
        return Ctx(w0=W0, w1=date(2026, 11, 15), raw=Path("."), state=Path("."))

    def test_filas_fuera_de_la_semana_no_se_cargan(self) -> None:
        c = self.ctx()
        self.assertFalse(c.add("dia", "B", "percent", 10, [1], "both", None, None, "2026-10-01", "2026-11-08", "", "u", None, "a"))
        self.assertFalse(c.add("dia", "B", "percent", 10, [1], "both", None, None, "2026-11-16", "2026-11-30", "", "u", None, "b"))
        self.assertTrue(c.add("dia", "B", "percent", 10, [1], "both", None, None, "2026-11-01", "2026-11-30", "", "u", None, "c"))
        self.assertEqual(len(c.rows), 1)

    def test_no_se_cargan_filas_sin_valor_ni_dias(self) -> None:
        with self.assertRaises(AssertionError):
            self.ctx().add("dia", "B", "percent", None, [1], "both", None, None, "2026-11-09", "2026-11-15", "", "u", None, "a")
        with self.assertRaises(AssertionError):
            self.ctx().add("dia", "B", "percent", 10, [], "both", None, None, "2026-11-09", "2026-11-15", "", "u", None, "a")


class PaginasTest(unittest.TestCase):
    HTML = "<p>10% de descuento los martes</p><p>Hasta 12 cuotas sin interés</p><p>Tope de reintegro $10.000</p><script>var x='50% fuera'</script>"

    def armar(self, html: str, fp: dict, aprobar: set[str] | None = None):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "state").mkdir()
        (tmp / "state" / "fingerprints.json").write_text(json.dumps(fp), encoding="utf-8")
        for fn in pages.PAGINAS.values():
            (tmp / fn).write_text(html, encoding="utf-8")
        ctx = Ctx(w0=W0, w1=date(2026, 11, 15), raw=tmp, state=tmp / "state", aprobar_paginas=aprobar or set())
        base = [fila("makro", [2], vf="2026-11-02", vt="2026-11-08", legal=f"x | {NOVIG}")]
        pages.build(ctx, base)
        return ctx

    def huellas(self) -> list[str]:
        return sorted(pages.huella(x) for x in pages.lineas(self.HTML))

    def test_pagina_igual_lleva_filas_y_corre_novig_a_la_semana_nueva(self) -> None:
        ctx = self.armar(self.HTML, {c: self.huellas() for c in pages.PAGINAS})
        self.assertEqual(ctx.unresolved, [])
        self.assertEqual([(r["valid_from"], r["valid_to"]) for r in ctx.rows], [("2026-11-09", "2026-11-15")])

    def test_pagina_cambiada_queda_pendiente_y_no_carga_filas(self) -> None:
        ctx = self.armar(self.HTML + "<p>Nuevo 25% de descuento</p>", {c: self.huellas() for c in pages.PAGINAS})
        self.assertEqual({u["chain"] for u in ctx.unresolved}, set(pages.PAGINAS))
        self.assertEqual(ctx.rows, [])

    def test_aprobar_paginas_mantiene_filas(self) -> None:
        ctx = self.armar(self.HTML + "<p>Nuevo 25% de descuento</p>", {c: self.huellas() for c in pages.PAGINAS}, {"makro"})
        self.assertNotIn("makro", {u["chain"] for u in ctx.unresolved})
        self.assertEqual(len(ctx.rows), 1)

    def test_script_y_lineas_volatiles_no_cuentan(self) -> None:
        self.assertEqual(pages.lineas(self.HTML), pages.lineas(self.HTML.replace("fuera", "otra cosa") + "<p>cookie 10% expires=Tue</p>"))


class DiaTest(unittest.TestCase):
    def test_extract_dedupe_y_hash_estable(self) -> None:
        c = {"__editorItemTitle": "Banco X", "terms": "10% los martes", "active": True}
        html = "<x>" + json.dumps(c) + "</x><y>" + json.dumps(c) + "</y>"
        cards = dia.extract(html)
        self.assertEqual(len(cards), 1)
        self.assertEqual(dia.card_hash(cards[0]), dia.card_hash(dict(c, terms="10%  los   martes")))
        self.assertNotEqual(dia.card_hash(cards[0]), dia.card_hash(dict(c, terms="20% los martes")))

    def test_card_nueva_activa_queda_pendiente(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        (tmp / "state").mkdir()
        (tmp / "state" / "dia.json").write_text("{}", encoding="utf-8")
        cards = [{"__editorItemTitle": f"Banco {i}", "terms": f"{i}% los martes", "active": True} for i in range(25)]
        (tmp / "dia.html").write_text("".join(json.dumps(c) for c in cards), encoding="utf-8")
        ctx = Ctx(w0=W0, w1=date(2026, 11, 15), raw=tmp, state=tmp / "state")
        dia.build(ctx)
        self.assertEqual(len(ctx.unresolved), 25)
        self.assertEqual(ctx.rows, [])


if __name__ == "__main__":
    unittest.main()
