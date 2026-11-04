"""Valida la data REAL (data/promos-semana.json), no el snapshot de conftest.py.

Caso 04/11/2026: Disco mostraba 3 promos porque la carga de la semana
02–08/11 no se había hecho (las promos Cencosud del 31/10 vencían) y Disco, que
sale de la misma fuente que Jumbo/Vea, quedaba casi vacío. Estos tests no usan
el reloj: toman como "semana de la data" la del valid_from más nuevo del
archivo, así siguen valiendo cada semana que se recarga.
"""
from __future__ import annotations

import json
import os
import unittest
from datetime import date, timedelta
from pathlib import Path

REAL = Path(__file__).resolve().parent / "data" / "promos-semana.json"
CAMPOS = {"chain", "bank", "kind", "value", "days", "channel", "valid_from", "valid_to", "source_url"}
CENCOSUD = ("disco", "jumbo", "vea")


def _filas() -> list[dict]:
    return json.loads(REAL.read_text(encoding="utf-8"))


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _vigente(r: dict, dia: date) -> bool:
    return _d(r["valid_from"]) <= dia <= _d(r["valid_to"]) and dia.isoweekday() in r["days"]


def _semana_de_la_data(filas: list[dict]) -> list[date]:
    """Lunes a domingo de la semana del valid_from más nuevo (la que se cargó)."""
    ultimo = max(_d(r["valid_from"]) for r in filas)
    lunes = ultimo - timedelta(days=ultimo.weekday())
    return [lunes + timedelta(days=i) for i in range(7)]


class DataPromosSemanaTest(unittest.TestCase):
    def test_esquema(self):
        filas = _filas()
        self.assertGreater(len(filas), 100)
        for r in filas:
            self.assertTrue(CAMPOS <= set(r), r)
            self.assertIn(r["kind"], ("percent", "installments"), r)
            self.assertIn(r["channel"], ("online", "store", "both"), r)
            self.assertTrue(r["days"] and all(1 <= d <= 7 for d in r["days"]), r)
            self.assertLessEqual(_d(r["valid_from"]), _d(r["valid_to"]), r)
            self.assertTrue(str(r["source_url"]).startswith("https://"), r)

    def test_disco_no_queda_casi_vacio_en_la_semana_de_la_data(self):
        """Disco, Jumbo y Vea comparten fuente: de lunes a sábado ninguno puede quedar casi vacío.

        Se cuentan todas las filas (% y cuotas) y por separado que haya al menos
        un % cada día: Disco publica pocos % (1 a 5 por día) y mucha cuota.
        """
        filas = _filas()
        semana = _semana_de_la_data(filas)
        for dia in semana[:6]:
            tot = {c: sum(1 for r in filas if r["chain"] == c and _vigente(r, dia)) for c in CENCOSUD}
            pct = sum(1 for r in filas if r["chain"] == "disco" and r["kind"] == "percent" and _vigente(r, dia))
            self.assertGreaterEqual(tot["disco"], 15, (dia, tot))
            self.assertGreaterEqual(tot["disco"], 0.6 * tot["jumbo"], (dia, tot))
            self.assertGreaterEqual(tot["vea"], 15, (dia, tot))
            self.assertGreaterEqual(pct, 1, (dia, "sin ningún % de Disco"))

    def test_disco_miercoles_trae_mas_de_los_3_casos_de_condicion(self):
        """Antes del fix el miércoles 04/11 sólo vencían 3 filas (jubilados Córdoba/Buenos Aires, Club la voz)."""
        filas = _filas()
        miercoles = [d for d in _semana_de_la_data(filas) if d.isoweekday() == 3][0]
        disco = [r for r in filas if r["chain"] == "disco" and _vigente(r, miercoles)]
        self.assertGreater(len(disco), 3)
        self.assertTrue(all(r["source_url"] for r in disco))

    @unittest.skipUnless(
        os.environ.get("BARATOYA_TESTS_REALES"),
        "alarma de frescura: sólo con reloj real (BARATOYA_TESTS_REALES=1); rompería cada semana en el CI",
    )
    def test_la_data_cubre_hoy(self):
        """Alarma: si hoy no hay promos de Disco, la carga semanal no se hizo (caso 04/11/2026)."""
        import promos_hoy

        hoy = promos_hoy.hoy_art()
        n = sum(1 for r in _filas() if r["chain"] == "disco" and r["kind"] == "percent" and _vigente(r, hoy))
        self.assertGreaterEqual(n, 1, f"Disco sin % vigentes el {hoy}: falta cargar la semana")


if __name__ == "__main__":
    unittest.main()
