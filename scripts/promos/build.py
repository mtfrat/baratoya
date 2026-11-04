"""Orquesta el armado de la semana: cada módulo agrega filas a un Ctx; nada se escribe acá."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from . import bp, cenco, coto, dia, laanonima, pages
from .common import ORDEN, Ctx


def armar(w0: date, raw: Path, state: Path, overrides: dict, baseline: list[dict], aprobar_paginas: set[str]) -> Ctx:
    ctx = Ctx(w0=w0, w1=w0 + timedelta(days=6), raw=raw, state=state, overrides=overrides, aprobar_paginas=aprobar_paginas)
    for nombre, mod in (("Día", dia), ("Mas Online / Carrefour", bp), ("Cencosud (Jumbo/Disco/Vea)", cenco), ("Coto", coto), ("La Anónima", laanonima)):
        print(f"[{nombre}]")
        mod.build(ctx)
    print("[Makro / Maxiconsumo / Super Mami / Cordiez / Toledo]")
    pages.build(ctx, baseline)
    ctx.rows.sort(key=lambda r: ORDEN[r["chain"]])  # estable: dentro de cada cadena queda el orden de armado
    sin_usar = set(ctx.overrides) - ctx.usados
    if sin_usar:
        ctx.log(f"{len(sin_usar)} override(s) sin usar (clave de otra semana o ya no hace falta), p. ej. {sorted(sin_usar)[0]}")
    return ctx
