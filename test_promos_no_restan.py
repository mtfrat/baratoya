"""Regla BaratoYa: las promos bancarias se muestran APARTE del precio de góndola.

El precio publicado no se toca por defecto; sólo se calcula un "total con promo" en el caso acotado y
documentado de `promos_hoy.puede_restar` (porcentaje, canal online, tope en pesos publicado, sin
`do_not_apply`, sin "no acumula", producto no excluido y mínimo cumplido). Estos tests recorren la data
semanal completa (la del snapshot en la suite normal; la real con BARATOYA_TESTS_REALES=1) y fallan si
alguna fila fuera de ese caso llegara a restar, o si el pipeline cargara un campo de precio.
"""
from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from pathlib import Path

import promos_hoy

PRECIO = 10000.0
CAMPOS_PIPELINE = {
    "chain", "bank", "kind", "value", "days", "channel", "cap", "minimum",
    "valid_from", "valid_to", "legal", "source_url", "do_not_apply", "ref",
}


def _filas() -> list[dict]:
    return json.loads((promos_hoy.DATA / "promos-semana.json").read_text(encoding="utf-8"))


def _fechas(rec: dict) -> list[date]:
    """Días a probar para una promo: su ventana de vigencia (máx. 45 días) o, si no tiene, una semana."""
    ini, fin = rec.get("inicio"), rec.get("fin")
    ini = ini or ((fin - timedelta(days=13)) if fin else date(2026, 10, 26))
    fin = min(fin or ini + timedelta(days=13), ini + timedelta(days=44))
    return [ini + timedelta(days=i) for i in range((fin - ini).days + 1)]


class PromosBancariasNoRestanTest(unittest.TestCase):
    def test_la_data_semanal_no_trae_precios(self) -> None:
        # El pipeline sólo carga la promo (valor, días, tope, condiciones); nunca un precio ni un "precio con descuento".
        for r in _filas():
            self.assertEqual(set(r), CAMPOS_PIPELINE, r["ref"])

    def test_cuotas_y_do_not_apply_nunca_restan(self) -> None:
        recs = [r for r in promos_hoy.cargar() if r.get("cuotas") or r.get("do_not_apply")]
        self.assertTrue(recs)
        for rec in recs:
            for hoy in _fechas(rec):
                ok, _motivo, total = promos_hoy.puede_restar(rec, "Producto cualquiera", PRECIO, hoy)
                if ok:
                    # Sólo puede restar un porcentaje sin cuotas ni condición vedada.
                    self.assertFalse(rec.get("do_not_apply"), rec.get("banco"))
                    self.assertFalse(rec.get("cuotas") and not rec.get("percent"), rec.get("banco"))
                self.assertGreaterEqual(total, 0)
                self.assertLessEqual(total, PRECIO)

    def test_solo_resta_en_el_caso_documentado(self) -> None:
        restaron = 0
        for rec in promos_hoy.cargar():
            for hoy in _fechas(rec):
                ok, _motivo, total = promos_hoy.puede_restar(rec, "Producto cualquiera", PRECIO, hoy)
                if not ok:
                    self.assertEqual(total, PRECIO, (rec.get("banco"), hoy))
                    continue
                restaron += 1
                self.assertTrue(rec.get("percent"), rec.get("banco"))
                self.assertIn(rec.get("canal"), {"online", "online y sucursal"}, rec.get("banco"))
                self.assertTrue(rec.get("cap"), f"{rec.get('banco')}: restó sin tope en pesos")
                self.assertFalse(rec.get("sin_tope"), rec.get("banco"))
                self.assertFalse(rec.get("do_not_apply"), rec.get("banco"))
                self.assertFalse(rec.get("cuotas"), rec.get("banco"))
                # Nunca más que el porcentaje ni que el tope publicado.
                dto = PRECIO - total
                self.assertLessEqual(dto, PRECIO * float(rec["percent"]) / 100 + 0.01)
                self.assertLessEqual(dto, float(rec["cap"]) + 0.01)
        self.assertGreater(restaron, 0, "el caso documentado debería existir en la data (si no, el test no prueba nada)")

    def test_tienda_sin_banco_no_resta_nada(self) -> None:
        # Sin promos aplicables el total es exactamente el precio de góndola.
        res = promos_hoy.aplicar_oferta("cadena-inexistente", "Yerba", PRECIO, date(2026, 10, 27))
        self.assertEqual(res["total"], PRECIO)
        self.assertIsNone(res["promo"])


if __name__ == "__main__":
    unittest.main()
