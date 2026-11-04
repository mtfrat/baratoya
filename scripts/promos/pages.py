"""Cadenas cuyas promos no se pueden leer como datos estructurados: Makro, Maxiconsumo, Super Mami, Cordiez, Toledo.

Política de carry verificado: las filas de la semana anterior se mantienen SOLO si el texto relevante de la
página pública (líneas con %, cuotas, tope, vigencia…) es idéntico al de la última carga (huella en
state/fingerprints.json). Si cambió, la cadena queda PENDIENTE: alguien tiene que leer la página y cargar las
filas. Con --aprobar-paginas <cadena> se confirma que ya se revisó el cambio y se mantienen las filas.
Las filas sin vigencia publicada (texto NOVIG) se corren a la semana nueva.
"""
from __future__ import annotations

import hashlib
import html as _html
import re

from .common import NOVIG, Ctx, clean

PAGINAS = {c: f"{c}.html" for c in ("makro", "maxiconsumo", "supermami", "cordiez", "toledo")}
KW = re.compile(r"(?i)%|cuota|tope|reintegro|descuento|vigen|v[aá]lid")
VOLATIL = re.compile(r"(?i)expires=|samesite=|nonce|csrf|__cf_bm")


def lineas(html: str) -> set[str]:
    s = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", "", html)
    t = _html.unescape(re.sub(r"<[^>]+>", "\n", s))
    return {re.sub(r"\s+", " ", ln).strip() for ln in t.split("\n")
            if KW.search(ln) and len(ln.strip()) > 3 and not VOLATIL.search(ln)}


def huella(ln: str) -> str:
    return hashlib.sha1(ln.encode()).hexdigest()[:12]


def build(ctx: Ctx, baseline: list[dict]) -> None:
    fps = ctx.load_state("fingerprints.json")
    nuevo: dict[str, list[str]] = {}
    for chain, fn in PAGINAS.items():
        ls = lineas((ctx.raw / fn).read_text(encoding="utf-8", errors="replace"))
        hs = {huella(x): x for x in ls}
        nuevo[chain] = sorted(hs)
        previas = set(fps.get(chain, []))
        if len(ls) < 3:
            ctx.pendiente(chain, f"page:{chain}", "la página no trae texto de promos (¿cambió o cayó?)")
            continue
        if set(hs) != previas and chain not in ctx.aprobar_paginas:
            solo_nuevas = [hs[h] for h in sorted(set(hs) - previas)][:4]
            faltan = len(previas - set(hs))
            ctx.pendiente(chain, f"page:{chain}", f"la página cambió desde la última carga ({len(set(hs) - previas)} líneas nuevas, {faltan} que ya no están): "
                          "revisar y cargar filas, o confirmar con --aprobar-paginas " + chain, " || ".join(x[:120] for x in solo_nuevas))
            continue
        n = 0
        for r in (x for x in baseline if x["chain"] == chain):
            vf, vt = r["valid_from"], r["valid_to"]
            if NOVIG in (r.get("legal") or ""):
                vf, vt = ctx.W0, ctx.W1
            if ctx.add(chain, r["bank"], r["kind"], r["value"], r["days"], r["channel"], r["cap"], r["minimum"], vf, vt, r["legal"], r["source_url"],
                       r["do_not_apply"], r["ref"]):
                n += 1
            else:
                ctx.log(f"{chain}: fila fuera de la semana (vigencia {vf}..{vt}): {r['bank'][:50]}")
        ctx.log(f"{chain}: página sin cambios ({len(ls)} líneas); {n} filas llevadas desde la carga anterior")
    ctx.new_state["fingerprints"] = nuevo
