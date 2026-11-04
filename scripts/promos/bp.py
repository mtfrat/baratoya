"""Mas Online y Carrefour: entidad pública BP de VTEX (cards de descuentos bancarios)."""
from __future__ import annotations

import datetime as dt
import json
import re

from . import bpcarry
from .common import Ctx, clean

DAYK = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
EXRE = re.compile(r"(?i)no incluye|excluid|excluye|exclusiones|no v[aá]lid[oa] para|productos seleccionados|art[ií]culos seleccionados")
CFG = {
    "masonline": dict(pref="mas", src="https://www.masonline.com.ar/promociones-bancarias"),
    "carrefour": dict(pref="car", src="https://www.carrefour.com.ar/descuentos-bancarios"),
}


def _bpdates(x: dict) -> tuple[str, str]:
    f = x["active_from"][:10]
    t = x["active_to"][:10]
    td = dt.date.fromisoformat(t)
    if td.day == 1:
        td -= dt.timedelta(days=1)
    return f, td.isoformat()


def _rows(ctx: Ctx, chain: str, cards: list[dict], fb: list[dict], fc: dict, src: str, T: dict, skip: set) -> None:
    banks = {b["id"]: b["name"] for b in fb}
    for i, x in enumerate(cards):
        if i in skip:
            continue
        t = T.get(i, {})
        days = [n + 1 for n, k in enumerate(DAYK) if x.get(k)]
        kind = "percent" if x.get("discount_percentage") else "installments"
        val = x.get("discount_percentage") or x.get("discounts_amount_installments")
        if not val and kind == "installments":
            m = re.search(r"(\d+)", str(x.get("discounts_text_installments") or ""))
            val = int(m.group(1)) if m else None
        f, to = _bpdates(x)
        f = t.get("vf", f)
        to = t.get("vt", to)
        bank = t.get("bank") or banks.get(x.get("idBank")) or fc.get(x.get("idCard")) or clean(x.get("title"))
        text = " | ".join(filter(None, [clean(x.get("title")), clean(x.get("sub_title")), clean(x.get("validText")), t.get("note"), "LEGAL: " + clean(x.get("legal"))]))
        cap, mn, ch = t.get("cap"), t.get("min"), t["ch"]
        dna = []
        if t.get("dna"):
            dna.append(t["dna"])
        if kind == "percent":
            if EXRE.search(text) and not t.get("noex"):
                dna.append("Excluye rubros/productos (ver legales)")
            if cap is None:
                dna.append("Sin tope o tope no informado")
        elif t.get("dna") is None and re.search(r"(?i)productos seleccionados|solo (en )?electro|en electro", text):
            dna.append("Solo productos/rubros seleccionados")
        ctx.add(chain, bank, kind, val, days or t.get("days"), ch, cap, mn, f, to, text, src, "; ".join(dict.fromkeys(dna)) or None, f"{chain[:1].upper()}:{x['id'][:8]}")


def build(ctx: Ctx) -> None:
    state = ctx.load_state("bp.json")
    fc = {c["id"]: c["name"] for c in json.loads((ctx.raw / "car_fc.json").read_text(encoding="utf-8"))}  # igual que el pipeline manual
    new_state = {}
    for chain, cfg in CFG.items():
        allc = json.loads((ctx.raw / f"{cfg['pref']}_bp_all.json").read_text(encoding="utf-8"))
        fb = json.loads((ctx.raw / f"{cfg['pref']}_fb.json").read_text(encoding="utf-8"))
        cur = sorted(bpcarry.sel(allc, ctx.W0, ctx.W1), key=lambda x: x["id"])  # orden estable: no depender del orden de la API
        st = state[chain]
        R, S, manual = bpcarry.carry(cur, st["cards"], st["ovr"], set(st["skip"]), ctx.W0)
        for j, x, why in manual:
            ov = ctx.override(f"bp:{chain}:{x['id']}")
            if ov is None:
                ctx.pendiente(chain, f"bp:{chain}:{x['id']}", why[:160], f'{x.get("title")} | {x.get("sub_title")}',
                              stub=st["ovr"].get(x["id"]) or {"ch": "online|store|both", "cap": None, "note": "condición leída del legal", "vf": None, "vt": None})
            elif ov.get("skip"):
                S.add(j)
            else:
                R[j] = ov
        # los pendientes quedan fuera de R y S: no se arman filas con datos inventados
        pend_ids = {x["id"] for j, x, _ in manual if j not in R and j not in S}
        _rows(ctx, chain, [x for j, x in enumerate(cur)], fb, fc, cfg["src"], R, S | {j for j, x in enumerate(cur) if x["id"] in pend_ids})
        new_state[chain] = {"cards": cur, "ovr": {cur[j]["id"]: R[j] for j in R}, "skip": [cur[j]["id"] for j in sorted(S)]}
        ctx.log(f"{chain}: {len(cur)} cards activas en la semana, {len(S)} omitidas, {len(pend_ids)} pendientes")
    ctx.new_state["bp"] = new_state
