"""Config común de pytest.

Los tests no deben depender del reloj real ni de la semana cargada en
data/promos-semana.json: ese archivo se reemplaza cada semana y las promos
vencen, así que los tests fijados a una fecha vieja se rompían solos (visto
el 04/11/2026: la carga de la semana 02–08/11 faltaba y 8 tests fallaban; al
cargarla, otros 2 fijados al 06/10 y 20/10 dejaban de ver Naranja X y Carrefour).

Acá se fija:
  * el "hoy" por defecto (martes 27/10/2026, dentro de la semana del snapshot);
  * promos-semana.json = tests_fixtures/promos-semana-2026-10-26.json
    (snapshot congelado; el resto de data/ se lee tal cual).

La data real se valida aparte en test_data_promos_semana.py (esquema y que
Disco/Jumbo/Vea no queden vacíos). Para correr contra la data real y el reloj
real: BARATOYA_TESTS_REALES=1 pytest.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
FIXTURE_SEMANA = RAIZ / "tests_fixtures" / "promos-semana-2026-10-26.json"
HOY_FIJO = datetime(2026, 10, 27, 12, 0)  # martes


def _fijar_entorno() -> None:
    import promos_hoy

    tmp = Path(tempfile.mkdtemp(prefix="baratoya-data-"))
    for p in promos_hoy.DATA.iterdir():
        if p.name != "promos-semana.json":
            (tmp / p.name).symlink_to(p)
    (tmp / "promos-semana.json").symlink_to(FIXTURE_SEMANA)
    promos_hoy.DATA = tmp
    promos_hoy._CACHE = None
    promos_hoy._ITEMS_MEMO = None

    original = promos_hoy.ahora_art

    def ahora_art(momento: datetime | None = None) -> datetime:
        return original(momento if momento is not None else HOY_FIJO)

    promos_hoy.ahora_art = ahora_art
    try:
        import precios_seo

        if hasattr(precios_seo, "ahora_art"):
            precios_seo.ahora_art = ahora_art
    except Exception:  # noqa: BLE001 - si precios_seo no importa, que falle su test
        pass


if not os.environ.get("BARATOYA_TESTS_REALES"):
    _fijar_entorno()


# Tests que verifican una fecha concreta del pasado (06/10 y 20/10) contra el snapshot semanal.
# Con BARATOYA_TESTS_REALES=1 se corre contra la data de la semana vigente, donde esas fechas
# ya no existen: se saltean en vez de fallar. Siguen corriendo en la suite normal.
FECHA_FIJA = (
    "test_match.py::PreciosLogosTypoTest::test_aplicar_oferta_con_banco_preferido_y_banco_inexistente",
    "test_cadena_resumen_semana.py::MetaCadenaHoyTest::test_coto_y_carrefour_conservan_title_h1",
)


def pytest_collection_modifyitems(config, items):
    if not os.environ.get("BARATOYA_TESTS_REALES"):
        return
    import pytest

    marca = pytest.mark.skip(reason="fijado a una fecha pasada: sólo corre contra el snapshot (suite normal)")
    for it in items:
        if it.nodeid in FECHA_FIJA:
            it.add_marker(marca)
