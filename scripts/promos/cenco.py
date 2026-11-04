"""Jumbo / Disco / Vea. Fuente pública: endpoint bankDiscount del Jumbo (el host de Disco/Vea devuelve vacío).

Cada card se resuelve contra el estado de la semana anterior (state/cenco.json): si la card es
idéntica (mismo medio, % o cuotas, días y texto sin fechas) se reusa su especificación (canal, tope,
mínimo, notas, vigencia). Si es nueva o cambió el texto, queda PENDIENTE: no se inventa nada.
"""
from __future__ import annotations

import datetime as dt
import difflib
import hashlib
import json
import re
from typing import Any

from .common import Ctx

TZ = dt.timezone(dt.timedelta(hours=-3))
SRC = {
    "jumbo": "https://www.jumbo.com.ar/descuentos-del-dia",
    "disco": "https://www.disco.com.ar/descuentos-del-dia",
    "vea": "https://www.vea.com.ar/descuentos-del-dia",
}


def _d(t: Any) -> str:  # fin de vigencia: el epoch es 23:59:59 del último día
    return dt.datetime.fromtimestamp(int(t) - 1, TZ).date().isoformat()


def _ds(t: Any) -> str:
    return dt.datetime.fromtimestamp(int(t), TZ).date().isoformat()


def _key(x: dict) -> tuple:
    return (tuple(b["name"].strip() for b in x["banks"]), x["discount"], tuple(x["days"]), x.get("discountText"), x.get("installmentsText"))


def _norm(x: dict) -> str:
    s = re.sub(r"\s+", " ", (x.get("info") or "") + " || " + (x.get("legals") or "")).lower()
    s = re.sub(r"\d{1,2}/\d{1,2}(/\d{2,4})?", "D", s)
    return s.replace("septiembre y octubre", "OCT").replace("octubre y noviembre", "OCT")


def card_id(x: dict) -> str:
    return "|".join([" ".join(b["name"].strip() for b in x["banks"]), str(x["discount"]), ",".join(x["days"]), str(x.get("discountText") or ""),
                     str(x.get("installmentsText") or ""), str(x["dateStart"])])


def build(ctx: Ctx) -> None:
    w0 = dt.datetime(ctx.w0.year, ctx.w0.month, ctx.w0.day, tzinfo=TZ).timestamp()
    w1 = (dt.datetime(ctx.w1.year, ctx.w1.month, ctx.w1.day, tzinfo=TZ) + dt.timedelta(days=1)).timestamp()
    allc = json.loads(json.loads((ctx.raw / "cenco_jn.json").read_text(encoding="utf-8"))["value"])
    cards = [x for x in allc if int(x["dateStart"]) < w1 and int(x["dateEnd"]) > w0]
    state = ctx.load_state("cenco.json")
    pool: dict[tuple, list[dict]] = {}
    for e in state:
        pool.setdefault(_key(e["card"]), []).append(e)
    nuevo: list[dict] = []
    n_skip = 0
    for x in cards:
        cid = card_id(x)
        spec = ctx.override("cenco:" + cid)
        if spec is None:
            cand = pool.get(_key(x))
            if cand:
                best = max(cand, key=lambda e: difflib.SequenceMatcher(None, _norm(e["card"]), _norm(x)).ratio())
                if difflib.SequenceMatcher(None, _norm(best["card"]), _norm(x)).ratio() >= 0.999:
                    spec = best["spec"]
        titulo = f'{" ".join(b["name"].strip() for b in x["banks"])} {x["discount"]} días {x["days"]}'
        if spec is None:
            ctx.pendiente("cencosud", "cenco:" + cid, "card nueva o con texto cambiado: falta especificación manual", titulo,
                          stub={"kind": "percent|installments", "value": None, "channel": "online|store|both", "cap": None, "minimum": None,
                                "vf": None, "vt": None, "note": "condición/exclusión leída de info+legals", "capnote": None})
            continue
        nuevo.append({"card": x, "spec": spec})
        if "skip" in spec:
            n_skip += 1
            ctx.log(f"cencosud: se omite «{titulo}» ({spec['skip']})")
            continue
        vt0 = spec.get("vt")
        if vt0 and vt0 < ctx.W0:
            ctx.pendiente("cencosud", "cenco:" + cid, f"la card sigue publicada pero la especificación vence el {vt0}: renovar fechas/texto", titulo, stub=spec)
            continue
        kind, val, ch, cap, mn = spec["kind"], spec["value"], spec["channel"], spec.get("cap"), spec.get("minimum")
        note, capnote = spec.get("note"), spec.get("capnote")
        vf = spec.get("vf") or _ds(x["dateStart"])
        vt = vt0 or _d(x["dateEnd"])
        days = sorted({7 if dd in ("0", "7") else int(dd) for dd in x["days"]})
        bank = " ".join(b["name"].strip() for b in x["banks"])
        dna = None
        if kind == "percent":
            reasons = []
            if note:
                reasons.append(note)
            if cap is None and not (note and "sin tope" in note):
                reasons.append("sin tope informado")
            dna = "; ".join(reasons) or None
        else:
            dna = note if note and ("Solo" in note or "Excluye" in note) else None
        legal = " | ".join(filter(None, [
            (x["discount"] + " " + (x["discountText"] or "") + " " + (x.get("installmentsText") or "")).strip(), capnote,
            "INFO: " + re.sub(r"\s+", " ", x["info"] or "").strip(), "LEGAL: " + re.sub(r"\s+", " ", x["legals"] or "").strip()]))
        sites = spec.get("sites") or sorted({"jumbo" if w.startswith("jumbo") else "disco" if w.startswith("disco") else "vea" if w.startswith("vea") else None
                                             for w in x["websites"]} - {None})
        for s in sites:
            ctx.add(s, bank, kind, val, days, ch, cap, mn, vf, vt, legal, SRC[s], dna, spec.get("ref") or "JN:" + hashlib.sha1(cid.encode()).hexdigest()[:8])
    ctx.new_state["cenco"] = nuevo
    ctx.log(f"cencosud: {len(cards)} cards en la semana, {n_skip} omitidas")
