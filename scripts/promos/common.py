"""Contexto de armado, filas y utilidades compartidas. Sin red, sin Supabase, sin secretos."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

NOVIG = "Vigencia no informada en la fuente; se carga solo para la semana relevada."
CADENAS = (
    "dia", "masonline", "carrefour", "jumbo", "disco", "vea", "cotodigital",
    "cordiez", "toledo", "laanonima", "makro", "maxiconsumo", "supermami",
)
# Mismo orden que el archivo histórico: así el diff semanal es legible.
ORDEN = {c: i for i, c in enumerate(CADENAS)}
CAMPOS_FILA = (
    "chain", "bank", "kind", "value", "days", "channel", "cap", "minimum",
    "valid_from", "valid_to", "legal", "source_url", "do_not_apply", "ref",
)


def clean(s: Any) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def lunes_de(d: date) -> date:
    return d - timedelta(days=d.weekday())


@dataclass
class Ctx:
    w0: date
    w1: date
    raw: Path
    state: Path
    overrides: dict[str, Any] = field(default_factory=dict)
    aprobar_paginas: set[str] = field(default_factory=set)
    rows: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    new_state: dict[str, Any] = field(default_factory=dict)
    usados: set[str] = field(default_factory=set)

    @property
    def W0(self) -> str:
        return self.w0.isoformat()

    @property
    def W1(self) -> str:
        return self.w1.isoformat()

    def log(self, msg: str) -> None:
        self.info.append(msg)
        print(f"  · {msg}")

    def override(self, key: str) -> Any:
        if key in self.overrides:
            self.usados.add(key)
            return self.overrides[key]
        return None

    def pendiente(self, chain: str, key: str, reason: str, detalle: str = "", stub: Any = None) -> None:
        self.unresolved.append({"chain": chain, "key": key, "reason": reason, "detalle": detalle[:300], "stub": stub})

    def add(self, chain, bank, kind, value, days, channel, cap, minimum, vf, vt, legal, src, dna, ref) -> bool:
        assert kind in ("percent", "installments") and value and days and channel in ("online", "store", "both"), (chain, bank, ref)
        if vt < self.W0 or vf > self.W1:
            return False  # fuera de la semana (vencida o futura): no es una fila de esta carga
        self.rows.append(dict(
            chain=chain, bank=clean(bank), kind=kind, value=value, days=sorted(set(days)), channel=channel,
            cap=cap, minimum=minimum, valid_from=vf, valid_to=vt, legal=clean(legal), source_url=src,
            do_not_apply=dna, ref=ref,
        ))
        return True

    def load_state(self, name: str) -> Any:
        return json.loads((self.state / name).read_text(encoding="utf-8"))
