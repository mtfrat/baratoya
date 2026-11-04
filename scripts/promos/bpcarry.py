"""Carry de overrides de las cards VTEX (Mas Online, Carrefour) de la semana anterior.

Solo se reusa un override si la card es idéntica o cambió sólo en fechas/redacción sin tocar un número.
Cualquier otro caso queda pendiente para revisión manual. Portado de la versión del pipeline manual.
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import re

IGN = {"updatedAt", "createdAt", "img_card", "order", "validText", "active_to", "active_from"}
MON = r"(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)"


def sel(cards: list[dict], w0: str, w1: str) -> list[dict]:
    return [x for x in cards if x.get("active") and (x.get("active_from") or "9")[:10] <= w1 and (x.get("active_to") or "")[:19] > w0 + "T03:00:00"]


def nums(x: dict) -> list[str]:
    t = " ".join(str(x.get(k) or "") for k in ("title", "sub_title", "discounts_text_installments"))
    t = re.sub(r"\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}\s+de\s+" + MON + r"(?:\s+de\s+\d{4})?", " ", t, flags=re.I)
    t = re.sub(r"\(\(?[A-Z0-9\-\)]{1,12}\)\*?", " ", t)
    base = set(re.findall(r"\d+(?:[\.,]\d+)*", t))
    lg = str(x.get("legal") or "")
    base |= {"$" + m for m in re.findall(r"\$\s?(\d[\d\.]*\d)", lg)} | {m + "%" for m in re.findall(r"(\d+)\s?%", lg)}
    return sorted(base)


def _dayf(x: dict) -> tuple:
    return tuple(bool(x.get(k)) for k in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))


def _txt(x: dict) -> str:
    return re.sub(r"[^a-z0-9 ]", "", " ".join(str(x.get(k) or "") for k in ("title", "sub_title")).lower())


def fuzzy(x: dict, prev: list[dict]) -> dict | None:
    best = None
    for p in prev:
        if (p.get("discount_percentage"), p.get("discounts_amount_installments"), x.get("idBank")) != (x.get("discount_percentage"), x.get("discounts_amount_installments"), p.get("idBank")):
            continue
        if p.get("idBank") != x.get("idBank") or _dayf(p) != _dayf(x):
            continue
        r = difflib.SequenceMatcher(None, _txt(p), _txt(x)).ratio()
        if r > 0.85 and (best is None or r > best[0]):
            best = (r, p)
    return best[1] if best else None


def carry(cur: list[dict], prev: list[dict], ovr: dict, skip: set, w0: str):
    """Devuelve (R por índice, S índices omitidos, manual [(j, card, motivo)])."""
    prev_end = (dt.date.fromisoformat(w0) - dt.timedelta(days=1)).isoformat()
    pm = {x["id"]: x for x in prev}
    R: dict[int, dict] = {}
    S: set[int] = set()
    manual: list[tuple[int, dict, str]] = []
    for j, x in enumerate(cur):
        p = pm.get(x["id"])
        if p is None:
            p = fuzzy(x, prev)
            if p is None:
                manual.append((j, x, "NEW"))
                continue
        if p["id"] in skip and all(p.get(k) == x.get(k) for k in x if k not in IGN):
            S.add(j)
            continue
        if p["id"] not in ovr:
            manual.append((j, x, "no prev override"))
            continue
        diffk = [k for k in set(x) | set(p) if x.get(k) != p.get(k) and k not in IGN | {"id"}]
        if diffk and nums(x) != nums(p):
            manual.append((j, x, f"numbers changed: {nums(p)} -> {nums(x)}"))
            continue
        if diffk and any(k not in ("title", "sub_title", "legal") for k in diffk):
            manual.append((j, x, f"structural change: {diffk}"))
            continue
        if re.search(r"\d", x.get("validText") or ""):
            manual.append((j, x, f"validText has digits: {x.get('validText')!r} (was {p.get('validText')!r})"))
            continue
        o = dict(ovr[p["id"]])
        for k in ("vf", "vt"):
            if o.get(k) and (o[k] <= w0 or (k == "vt" and o[k] <= prev_end)):
                o.pop(k)  # fecha de un período anterior: se usan las fechas frescas de la card
        R[j] = o
    return R, S, manual
