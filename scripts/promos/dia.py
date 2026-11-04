"""Día: cards del CMS embebidas en la página pública de medios de pago.

El HTML trae el JSON de cada card (`{"__editorItemTitle": ...}`) más de una vez y con un bloque viejo.
Cada card única se resuelve por hash de (título + términos) contra state/dia.json. Una card nueva o con
términos cambiados queda PENDIENTE. Las cards inactivas (active:false) no se cargan nunca.
"""
from __future__ import annotations

import hashlib
import json
import re

from .common import NOVIG, Ctx, clean

SRC = "https://diaonline.supermercadosdia.com.ar/medios-de-pago-y-promociones"


def extract(html: str) -> list[dict]:
    dec = json.JSONDecoder()
    out: list[dict] = []
    for m in re.finditer(r'\{"__editorItemTitle"', html):
        try:
            o, _ = dec.raw_decode(html[m.start():])
        except ValueError:
            continue
        if o not in out:
            out.append(o)
    return out


def card_hash(c: dict) -> str:
    return hashlib.sha1(re.sub(r"\s+", " ", c["__editorItemTitle"] + "|" + (c.get("terms") or "")).strip().encode()).hexdigest()[:16]


def build(ctx: Ctx) -> None:
    cards = extract((ctx.raw / "dia.html").read_text(encoding="utf-8", errors="replace"))
    if len(cards) < 20:
        ctx.pendiente("dia", "dia:extract", f"sólo {len(cards)} cards en el HTML: cambió la estructura de la página")
        return
    state = ctx.load_state("dia.json")
    vistos: set[str] = set()
    n_ok = 0
    for c in cards:
        if not c.get("terms"):
            continue  # entradas de banco sin términos: no son promos
        h = card_hash(c)
        if h in vistos:
            continue
        vistos.add(h)
        titulo = clean(c["__editorItemTitle"])
        if not c.get("active"):
            continue
        spec = ctx.override("dia:" + h) or state.get(h)
        if spec is None:
            ctx.pendiente("dia", "dia:" + h, "card activa nueva o con términos cambiados", f"{titulo}: {clean(c['terms'])[:140]}",
                          stub={"bank": titulo, "kind": "percent|installments", "value": None, "days": [], "channel": "online|store|both", "cap": None,
                                "minimum": None, "vf": None, "vt": None, "note": "tope/condición leídos de los términos", "dna": None, "ref": "D?"})
            continue
        if "skip" in spec:
            continue
        vf = ctx.W0 if spec["vf"] == "W0" else spec["vf"]
        vt = ctx.W1 if spec["vt"] == "W1" else spec["vt"]
        if spec["vt"] != "W1" and vt < ctx.W0:
            ctx.pendiente("dia", "dia:" + h, f"la card sigue activa pero la especificación vence el {vt}: renovar fechas", titulo, stub=spec)
            continue
        note = spec["note"]
        if "{NOVIG}" in note:
            note = note.replace("{NOVIG}", NOVIG)
        if ctx.add("dia", spec["bank"], spec["kind"], spec["value"], spec["days"], spec["channel"], spec.get("cap"), spec.get("minimum"), vf, vt,
                   note + " | " + clean(c["terms"]), SRC, spec.get("dna"), spec["ref"]):
            n_ok += 1
    ctx.new_state["dia"] = {h: (ctx.override("dia:" + h) or state[h]) for h in vistos if h in state or ("dia:" + h) in ctx.overrides}
    ctx.log(f"dia: {len(vistos)} cards únicas con términos, {n_ok} filas")
