"""La Anónima: cards `div.promo-card` de la página pública, convertidas con el loader de promos_hoy."""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from .common import NOVIG, Ctx, clean

SRC = "https://super.laanonima.com.ar/empresa/promociones-y-descuentos"
RAIZ = Path(__file__).resolve().parents[2]
DAYS = {"lunes": 1, "martes": 2, "miércoles": 3, "jueves": 4, "viernes": 5, "sábado": 6, "domingo": 7}


def _conv(html: str) -> list[dict]:
    from bs4 import BeautifulSoup  # dependencia sólo del pipeline (scripts/promos/requirements.txt)

    b = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for c in b.select("div.promo-card"):
        h = c.select_one("h3")
        bank = re.sub(r"\s+", " ", h.get_text(" ")).strip() if h else None
        lg = c.select_one(".promo-card-legal")
        legal = re.sub(r"\s+", " ", lg.get_text(" ")).strip() if lg else None
        img = c.select_one("img")
        days = [re.sub(r"\s+", " ", d.get_text()).strip() for d in c.select("div.rounded-btn")]
        key = (bank, legal, tuple(days), c.get("data-day"), c.get("data-bank"))
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(bank=bank, days=days, day_codes=c.get("data-day"), bank_codes=c.get("data-bank"), legal=legal, image_alt=img.get("alt") if img else None))
    return out


def _sent(txt: str, pat: str):
    for s in re.split(r"(?<=[\.\)])\s+(?=[A-ZÁÉÍÓÚ])", txt):
        if re.search(pat, s, re.I):
            return s.strip()
    return None


def _parse(c: dict) -> dict:
    L = c["legal"] or ""
    bank = c["bank"]
    st = re.match(r"Válido (.*?)\. Días: (.*?)\. Beneficio: (.*?)\. (?:Tope/condiciones: (.*?)\. )?(?:Medio de pago|CFT|Promoción|Válido|Ciudades|Minimo)", L)
    validity = tope = None
    ben = bank
    if st:
        validity, ben, tope = st.group(1), st.group(3), st.group(4)
    else:
        m = re.search(r"(?:desde el|del|Desde el|Válida desde el)\s+(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+(?:hasta el|al|hasta)\s+(\d{1,2}/\d{1,2}/\d{2,4})", L)
        if m:
            validity = m.group(1) + " al " + m.group(2)
        tope = _sent(L, r"\btope\b")
    pct = [p.replace(" ", "") for p in re.findall(r"\d+\s?%", ben if st else bank)]
    inst = re.findall(r"(?:hasta\s+)?\d+\s*(?:cuotas|CSI)[^.,+]*", ben if st else bank, re.I)
    return dict(kind="banco", bank=bank, days=c["days"], day_codes=c["day_codes"], percent=pct or None, installments=inst or None,
                channel="sucursal" if re.search(r"sucursal", L, re.I) else None, tope=tope, minimum_purchase=_sent(L, r"m[ií]nimo|compra m[ií]nima"),
                validity=validity, exclusion=_sent(L, r"^Excluye|\bExcluye (?!sucursales)"), legal=L, image_alt=c["image_alt"])


def parse_cards(html: str) -> list[dict]:
    seen, out = set(), []
    for c in _conv(html):
        if not c["day_codes"]:
            continue
        k = (c["bank"], c["legal"])
        if k in seen:
            continue
        seen.add(k)
        out.append(_parse(c))
    return out


def build(ctx: Ctx) -> None:
    sys.path.insert(0, str(RAIZ))
    import promos_hoy

    cards = parse_cards((ctx.raw / "laanonima.html").read_text(encoding="utf-8", errors="replace"))
    if len(cards) < 5:
        ctx.pendiente("laanonima", "laanonima:cards", f"sólo {len(cards)} cards parseadas: cambió la estructura de la página")
        return
    plantilla = json.loads((RAIZ / "data" / "la-anonima-promos.json").read_text(encoding="utf-8"))
    plantilla["promos"] = cards
    tmp = Path(tempfile.mkdtemp(prefix="promos-la-"))
    try:
        (tmp / "la-anonima-promos.json").write_text(json.dumps(plantilla, ensure_ascii=False), encoding="utf-8")
        viejo = promos_hoy.DATA
        promos_hoy.DATA = tmp
        try:
            recs = promos_hoy._cargar_la_anonima()
        finally:
            promos_hoy.DATA = viejo
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    n = 0
    for i, r in enumerate(recs):
        if r.get("oculta"):
            continue
        fe = r.get("fechas_especificas") or []
        if fe and not any(ctx.w0 <= f <= ctx.w1 for f in fe):
            continue
        if r["fin"] and r["fin"] < ctx.w0:
            continue
        if r["inicio"] and r["inicio"] > ctx.w1:
            continue
        if r["percent"]:
            kind, val = "percent", r["percent"]
        else:
            m = re.findall(r"(\d+)\s*cuotas", str(r["cuotas"]) + " " + str(r["texto"]), re.I)
            if not m:
                continue
            kind, val = "installments", max(int(x) for x in m)
            if val < 2:
                continue
        days = [d + 1 for d in r["days"]]
        if not days:
            ctx.log(f"laanonima: se omite {r['banco']} (sin días publicados)")
            continue
        cs = (r["canal"] or "").lower()
        ch = "both" if ("online" in cs or "domicilio" in cs) and "sucursal" in cs else "online" if "online" in cs else "store" if "sucursal" in cs else "both"
        dna = []
        if ch == "both" and not ("online" in cs and "sucursal" in cs):
            dna.append("Canal no indicado")
        if r.get("conflicto"):
            dna.append("Conflicto: " + clean(r["conflicto"]))
        ex = clean(r.get("exclusion"))
        if kind == "percent":
            if r["cap"] is None or r["sin_tope"] or not r["cap_conocido"]:
                dna.append("Sin tope o tope no informado")
            if re.search(r"(?i)no incluye|exclu|restricci|seleccionad|no v[aá]lid", ex + " " + clean(r.get("legal"))):
                dna.append("Exclusiones o restricciones (ver legales)")
        elif re.search(r"(?i)seleccionad|electro|no tradicional", ex + " " + clean(r.get("texto"))):
            dna.append("Solo productos seleccionados")
        vf = (r["inicio"] or ctx.w0).isoformat()
        vt = (r["fin"] or ctx.w1).isoformat()
        if fe:
            inwk = [f for f in fe if ctx.w0 <= f <= ctx.w1]
            vf, vt = min(inwk).isoformat(), max(inwk).isoformat()
        note = "" if r["fin"] else NOVIG
        if ctx.add("laanonima", r["banco"] or "", kind, val, days, ch,
                   int(r["cap"]) if r["cap"] and r["cap_conocido"] and not r["sin_tope"] else None, int(r["minimo"]) if r["minimo"] else None, vf, vt,
                   " | ".join(filter(None, [clean(r["texto"]), clean(r.get("legal")), "Condición: " + ex if ex else "", note])), SRC,
                   "; ".join(dict.fromkeys(dna)) or None, f"L{i}"):
            n += 1
    ctx.log(f"laanonima: {len(cards)} cards, {n} filas")
