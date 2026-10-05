"""Mapa de marcas (bancos / billeteras) para filtros con logo.

No inventa precios ni promos: solo normaliza textos ya publicados.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).parent / "data" / "brand-logos.json"

# Preferir entidad emisora / billetera antes que red de tarjeta al armar etiqueta.
_PRIORIDAD = {
    "modo": 10,
    "mercado_pago": 10,
    "naranja_x": 20,
    "cuenta_dni": 20,
    "personal_pay": 20,
    "prex": 20,
    "uala": 20,
    "carrefour": 25,
    "galicia": 30,
    "bbva": 30,
    "santander": 30,
    "icbc": 30,
    "nacion": 30,
    "bna": 30,
    "provincia": 30,
    "patagonia": 30,
    "patagonia_365": 30,
    "ciudad": 30,
    "macro": 30,
    "supervielle": 30,
    "comafi": 30,
    "credicoop": 30,
    "hipotecario": 30,
    "visa": 80,
    "mastercard": 80,
    "amex": 80,
    "cabal": 80,
}


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.casefold().replace("_", " ")).strip()


@lru_cache(maxsize=1)
def catalogo_marcas() -> dict[str, Any]:
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    keywords = [(_fold(k), bid) for k, bid in raw.get("keywords") or []]
    keywords.sort(key=lambda par: len(par[0]), reverse=True)
    return {
        "version": raw.get("version") or 1,
        "logo_base": raw.get("logo_base") or "",
        "pins": list(raw.get("pins") or []),
        "brands": dict(raw.get("brands") or {}),
        "groups": dict(raw.get("groups") or {}),
        "keywords": keywords,
    }


def _etiqueta_corta(texto: str) -> str:
    t = re.sub(r"(?i)^(banco|tarjeta de cr[eé]dito)\s+", "", (texto or "").strip())
    t = re.sub(r"(?i)\btarjeta de cr[eé]dito\b", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -/|,")
    return t or (texto or "").strip()


def resolver_marcas(texto: str) -> dict[str, Any]:
    """Devuelve brand_ids, etiqueta corta y variante (sin prefijo Banco)."""
    crudo = str(texto or "").strip()
    cat = catalogo_marcas()
    brands = cat["brands"]
    fold = _fold(crudo)
    if not fold:
        return {"brand_ids": [], "brand_label": "", "variant_label": "", "group_ids": []}

    ids: list[str] = []
    ocupados: list[tuple[int, int]] = []
    for clave, bid in cat["keywords"]:
        start = 0
        while True:
            i = fold.find(clave, start)
            if i < 0:
                break
            j = i + len(clave)
            if i > 0 and fold[i - 1].isalnum():
                start = i + 1
                continue
            if j < len(fold) and fold[j].isalnum() and not clave.endswith("+"):
                start = i + 1
                continue
            if any(not (j <= a or i >= b) for a, b in ocupados):
                start = i + 1
                continue
            ocupados.append((i, j))
            if bid not in ids:
                ids.append(bid)
            start = j

    ids_ord = sorted(ids, key=lambda b: (_PRIORIDAD.get(b, 50), brands.get(b, {}).get("label", b)))
    if ids_ord:
        # Si es "Banco X vía MODO", la etiqueta corta es el banco; MODO queda en brand_ids.
        principales = [b for b in ids_ord if b not in {"modo", "visa", "mastercard", "amex", "cabal"}]
        if "modo" in ids_ord and principales:
            label = brands.get(principales[0], {}).get("label") or _etiqueta_corta(crudo)
        elif len(principales) >= 1 and set(ids_ord) - set(principales):
            label = brands.get(principales[0], {}).get("label") or _etiqueta_corta(crudo)
        else:
            label = brands.get(ids_ord[0], {}).get("label") or _etiqueta_corta(crudo)
    else:
        label = _etiqueta_corta(crudo)

    variante = crudo
    # Quitar nombres de marca conocidos y prefijos ruidosos.
    for bid in ids:
        lab = brands.get(bid, {}).get("label") or ""
        if lab:
            variante = re.sub(re.escape(lab), " ", variante, flags=re.I)
        # formas largas frecuentes
        if bid == "amex":
            variante = re.sub(r"(?i)american express?", " ", variante)
        if bid == "nacion":
            variante = re.sub(r"(?i)\bbna\+?\b", " ", variante)
        if bid == "sol":
            variante = re.sub(r"(?i)\btarjeta sol\b", " ", variante)
        if bid == "la_anonima":
            variante = re.sub(r"(?i)\btarjeta la an[oó]nima\b", " ", variante)
    variante = re.sub(r"(?i)\bbanco\b", " ", variante)
    variante = re.sub(r"(?i)\btarjeta de cr[eé]dito\b", " ", variante)
    variante = re.sub(r"(?i)\bv[ií]a\b", " ", variante)
    variante = re.sub(r"[\s,;/|++-]+", " ", variante).strip(" -/|,()")
    if _fold(variante) in {"", _fold(label)}:
        variante = ""
    # Si la variante es solo otra marca ya listada, vaciar.
    if variante and _fold(variante) in {_fold(brands.get(b, {}).get("label") or "") for b in ids}:
        variante = ""

    groups: list[str] = []
    for bid in ids_ord:
        g = (brands.get(bid) or {}).get("group")
        if g and g not in groups:
            groups.append(g)
        # MODO en brand_ids implica grupo modo
        if bid == "modo" and "modo" not in groups:
            groups.append("modo")

    return {
        "brand_ids": ids_ord,
        "brand_label": label,
        "variant_label": variante,
        "group_ids": groups,
    }


def enriquecer_tarjeta(card: dict[str, Any]) -> dict[str, Any]:
    fuente = card.get("banco_filtro") or card.get("banco") or ""
    meta = resolver_marcas(str(fuente))
    out = dict(card)
    out["brand_ids"] = meta["brand_ids"]
    out["brand_label"] = meta["brand_label"] or _etiqueta_corta(str(card.get("banco") or ""))
    out["variant_label"] = meta["variant_label"]
    out["group_ids"] = meta["group_ids"]
    return out


def meta_publica() -> dict[str, Any]:
    cat = catalogo_marcas()
    brands_out = {}
    for bid, row in cat["brands"].items():
        brands_out[bid] = {
            "id": bid,
            "label": row.get("label") or bid,
            "color": row.get("color") or "#666",
            "initials": row.get("initials") or (row.get("label") or bid)[:2],
            "group": row.get("group"),
            "logo": row.get("logo") or "",
        }
    return {
        "version": cat["version"],
        "logo_base": cat["logo_base"],
        "pins": cat["pins"],
        "brands": brands_out,
        "groups": cat["groups"],
    }
