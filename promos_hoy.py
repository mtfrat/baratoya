"""Promos bancarias guardadas. No se inventa una tarjeta.

El precio comparable es el de venta (el que se paga ahora). Una promo
solo se resta si la tarjeta de hoy está visible, vigente, sin fechas
contradictorias, con un tope en pesos, canal online y sin excluir el producto.
"Sin tope" no se resta. Si la letra dice que no acumula con otros descuentos,
tampoco. Cuotas no son un porcentaje. America/Buenos_Aires es UTC−3 todo el año.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from baratoya.brand_logos import enriquecer_tarjeta, meta_publica as marcas_meta
except ImportError:
    from brand_logos import enriquecer_tarjeta, meta_publica as marcas_meta

ART = timezone(timedelta(hours=-3))
DATA = Path(__file__).resolve().parent / "data"

DIAS = (
    (0, "lunes"),
    (1, "martes"),
    (2, "miércoles"),
    (3, "jueves"),
    (4, "viernes"),
    (5, "sábado"),
    (6, "domingo"),
)
NOMBRE_DIA = {i: n for i, n in DIAS}
DIA_NUM = {n: i for i, n in DIAS}
DIA_NUM["miercoles"] = 2
DIA_NUM["sabado"] = 5

_ABREV = {"l": 0, "ma": 1, "mi": 2, "j": 3, "v": 4, "s": 5, "d": 6}

def _dia_idx(token: str) -> int | None:
    t = _fold(token).strip(" .")
    if t in _ABREV:
        return _ABREV[t]
    if t in DIA_NUM:
        return DIA_NUM[t]
    if t.endswith("s") and t[:-1] in DIA_NUM:
        return DIA_NUM[t[:-1]]
    return None
MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
CHAIN_ID = {
    "día": "dia", "dia": "dia",
    "carrefour": "carrefour",
    "mas online": "masonline", "mas online (changomás)": "masonline",
    "jumbo": "jumbo", "disco": "disco", "vea": "vea",
    "cordiez": "cordiez", "toledo": "toledo", "josimar": "josimar",
    "la anónima": "laanonima", "la anonima": "laanonima",
    "coto": "cotodigital", "coto digital": "cotodigital",
    "makro": "makro",
    "maxiconsumo": "maxiconsumo",
    "supermami": "supermami", "super mami": "supermami",
}
CHAIN_NOMBRE = {
    "dia": "Día", "carrefour": "Carrefour", "masonline": "Mas Online",
    "jumbo": "Jumbo", "disco": "Disco", "vea": "Vea", "cordiez": "Cordiez",
    "toledo": "Toledo", "josimar": "Josimar", "laanonima": "La Anónima",
    "cotodigital": "Coto Digital", "makro": "Makro",
    "supermami": "Super Mami", "abastecedor": "El Abastecedor", "comodin": "Comodín",
    "maxiconsumo": "Maxiconsumo",
}

_CACHE: list[dict[str, Any]] | None = None


def ahora_art(momento: datetime | None = None) -> datetime:
    if momento is None:
        return datetime.now(ART)
    if momento.tzinfo is None:
        return momento.replace(tzinfo=ART)
    return momento.astimezone(ART)


def hoy_art(momento: datetime | None = None) -> date:
    return ahora_art(momento).date()


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.casefold()


def _limpia(s: str) -> str:
    return " ".join((s or "").split())


def _num_peso(raw: str) -> float | None:
    s = (raw or "").strip().replace("$", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        n = float(s)
    except ValueError:
        return None
    if n <= 0:
        return None
    return n


def _pesos_en(texto: str) -> list[float]:
    out: list[float] = []
    for raw in re.findall(r"\$\s*(\d[\d.]*(?:,\d{1,2})?)", texto or ""):
        n = _num_peso(raw)
        if n is not None and n not in out:
            out.append(n)
    return out


def _pcts(texto: str) -> list[float]:
    out: list[float] = []
    for raw in re.findall(r"(\d+(?:[.,]\d+)?)\s*%", texto or ""):
        try:
            n = float(raw.replace(",", "."))
        except ValueError:
            continue
        if n <= 0 or n > 90 or n in out:
            continue
        out.append(n)
    return out


def _fecha_token(texto: str, anio: int | None = 2026) -> date | None:
    t = _fold(texto)
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})\s+de\s+([a-z]+)(?:\s+de(?:l)?\s+(\d{4}))?", t)
    if m and m.group(2) in MESES:
        y = int(m.group(3)) if m.group(3) else anio
        if not y:
            return None
        try:
            return date(y, MESES[m.group(2)], int(m.group(1)))
        except ValueError:
            return None
    return None


def _rangos(texto: str) -> list[tuple[date, date]]:
    """Pares desde/hasta. Más de un par distinto es un conflicto de fechas."""
    found: list[tuple[date, date]] = []
    blob = texto or ""
    patron = re.compile(
        r"(?:desde|del|vigencia)\s+(.{4,48}?)\s+(?:hasta|al)\s+(.{4,48}?)(?=[.,;\n]|$)",
        re.I,
    )
    for m in patron.finditer(blob):
        a = _fecha_token(m.group(1))
        b = _fecha_token(m.group(2), anio=(a.year if a else None))
        if a and b:
            if b < a:
                continue
            par = (a, b)
            if par not in found:
                found.append(par)
    if not found:
        sueltos = []
        for m in re.finditer(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+de\s+[a-záéíóú]+(?:\s+de\s+\d{4})?", _fold(blob)):
            f = _fecha_token(m.group(0))
            if f and f not in sueltos:
                sueltos.append(f)
        if len(sueltos) >= 2:
            found.append((min(sueltos), max(sueltos)))
        elif len(sueltos) == 1 and re.search(r"hasta|al\s", _fold(blob)):
            found.append((date(sueltos[0].year, 1, 1), sueltos[0]))
    # "octubre 2026" sin día
    if not found:
        m = re.search(r"\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+(\d{4})", _fold(blob))
        if not m:
            m = re.search(r"\b(octubre|noviembre|diciembre|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre)\s+(\d{4})", _fold(blob))
        if m and m.group(1) in MESES:
            y = int(m.group(2))
            mo = MESES[m.group(1)]
            ultimo = (date(y + (mo == 12), 1 if mo == 12 else mo + 1, 1) - timedelta(days=1)).day
            found.append((date(y, mo, 1), date(y, mo, ultimo)))
    return found


def _dias_mencionados(texto: str) -> set[int]:
    """Días de la agenda, no un apellido (Juan Domingo) ni el legal entero."""
    t = _fold(texto)
    if re.search(r"todos los dias(?!\s+(?:lunes|martes|miercoles|jueves|viernes|sabados?|domingos?))", t):
        return set(range(7))
    out: set[int] = set()
    ventanas = re.findall(
        r"(?:los dias|todos los|valida los|validos los|dias)\s+([a-z][a-z,\s]{2,60})",
        t,
    )
    if not ventanas:
        ventanas = [t[:80]]
    for ventana in ventanas:
        for i, nombre in DIAS:
            plano = _fold(nombre)
            if re.search(rf"\b{plano}s?\b", ventana):
                out.add(i)
    return out


def _canal(field: str, texto: str) -> str:
    blob = _fold(f"{field} {texto}")
    if "no valido para venta online" in blob or "no vale en coto digital" in blob or "no valido online" in blob:
        return "sucursal"
    online = any(w in blob for w in ("online", "e-commerce", "ecommerce", "masonline", "mas online", "mas on line", "pago online", "dia online"))
    sucursal = any(w in blob for w in ("sucursal", "tienda fisica", "tiendas fisicas", "presencial", "solo tienda", "exclusivo en sucursal", "en sucursal"))
    if online and sucursal:
        return "online y sucursal"
    if online:
        return "online"
    if sucursal:
        return "sucursal"
    if field:
        f = _fold(field)
        if f in {"both", "online y sucursal", "sucursal y online"}:
            return "online y sucursal"
        if "online" in f and "tienda" in f:
            return "online y sucursal"
        if "online" in f:
            return "online"
        if "tienda" in f or "sucursal" in f:
            return "sucursal"
    return "no indicado"


def _tope(texto: str) -> tuple[float | None, bool, bool]:
    """cap, sin_tope, conocido."""
    t = _fold(texto)
    if "sin tope" in t or "sin limite" in t:
        return None, True, True
    if not texto or "no indicado" in t or "not stated" in t:
        return None, False, False
    nums = _pesos_en(texto)
    # varios topes de segmento: no se sabe cuál
    if len(nums) > 1 and "tope" in t:
        return None, False, False
    if len(nums) == 1 and ("tope" in t or "$" in (texto or "")):
        return nums[0], False, True
    return None, False, False


def _minimo(texto: str) -> float | None:
    t = texto or ""
    m = re.search(r"m[ií]nim[oa][^$]{0,48}\$\s*(\d[\d.]*(?:,\d{1,2})?)", t, re.I)
    if not m:
        m = re.search(r"compra(?:s)?\s+(?:iguales o )?superiores a\s+\$\s*(\d[\d.]*)", _fold(t))
        if m:
            return _num_peso(m.group(1))
        return None
    return _num_peso(m.group(1))


def _cuotas_txt(texto: str) -> str:
    m = re.search(r"(\d+)\s*cuotas?\s+sin inter[eé]s", texto or "", re.I)
    if m:
        return f"{m.group(1)} cuotas sin interés"
    if re.search(r"\bcuotas?\b", texto or "", re.I) and not _pcts(texto or ""):
        return _limpia(texto)[:80]
    return ""


def _base(**kwargs: Any) -> dict[str, Any]:
    rec = {
        "chain_id": "",
        "cadena": "",
        "banco": "",
        "percent": None,
        "cuotas": "",
        "days": set(),
        "canal": "no indicado",
        "cap": None,
        "sin_tope": False,
        "cap_conocido": False,
        "minimo": None,
        "inicio": None,
        "fin": None,
        "conflicto": "",
        "oculta": False,
        "exclusion": "",
        "legal": "",
        "texto": "",
        "fechas_especificas": set(),
        "do_not_apply": None,
        "source_url": "",
        "ref": "",
    }
    rec.update(kwargs)
    return rec


def _cierra_vigencia(rec: dict[str, Any], textos: list[str]) -> None:
    rangos: list[tuple[date, date]] = []
    for texto in textos:
        for par in _rangos(texto):
            if par not in rangos:
                rangos.append(par)
    if len(rangos) > 1 and len(set(rangos)) > 1:
        rec["conflicto"] = "Hay más de una vigencia publicada y no coinciden."
        rec["inicio"], rec["fin"] = rangos[0]
    elif rangos:
        rec["inicio"], rec["fin"] = rangos[0]
    etiqueta = _fold(rec.get("texto") or "")
    dias_legal = _dias_mencionados(rec.get("legal") or "")
    if rec["days"] and dias_legal and not dias_legal.issuperset(set(rec["days"])):
        rec["conflicto"] = rec["conflicto"] or "Los días de la tarjeta y los de la letra no coinciden."
    elif rec["days"] and dias_legal and dias_legal != set(rec["days"]):
        # La letra suma un día que la tarjeta apagó (viernes en billeteras).
        rec["conflicto"] = rec["conflicto"] or "Los días de la tarjeta y los de la letra no coinciden."
    anio = rec["fin"].year if isinstance(rec.get("fin"), date) else 2026
    nombradas: list[date] = []
    m = re.search(
        r"(\d{1,2})(?:\s+y\s+[a-z]+\s+(\d{1,2}))?\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)",
        etiqueta,
    )
    if m:
        mes = MESES[m.group(3)]
        for g in (m.group(1), m.group(2)):
            if not g:
                continue
            try:
                nombradas.append(date(anio, mes, int(g)))
            except ValueError:
                pass
    if nombradas and "todos" not in etiqueta:
        rec["fechas_especificas"] = set(nombradas)


def _marca_conflictos_cruzados(recs: list[dict[str, Any]]) -> None:
    grupos: dict[tuple, list[dict[str, Any]]] = {}
    for rec in recs:
        if rec.get("percent") is None:
            continue
        banco = _fold(rec["banco"])
        for token in ("comafi", "naranja", "patagonia", "credicoop", "galicia", "icbc", "modo"):
            if token in banco:
                banco = token
                break
        clave = (rec["chain_id"], banco, rec["percent"], tuple(sorted(rec["days"])))
        grupos.setdefault(clave, []).append(rec)
    for grupo in grupos.values():
        fines = {r["fin"] for r in grupo if r.get("fin")}
        if len(fines) > 1:
            for r in grupo:
                r["conflicto"] = "Dos vigencias publicadas no coinciden (no se aplica)."


def _cargar_dia() -> list[dict[str, Any]]:
    path = DATA / "dia-promos.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    out = []
    for card in data.get("cards") or []:
        if not isinstance(card, dict):
            continue
        offer = str(card.get("offer") or "")
        pcts = _pcts(offer)
        dias = set()
        for etiqueta in card.get("days_active") or []:
            n = _dia_idx(str(etiqueta))
            if n is not None:
                dias.add(n)
        banco = str(card.get("bank") or card.get("editorTitle") or "").strip()
        terms = str(card.get("terms") or "")
        validity = str(card.get("validity") or "")
        tope_txt = str(card.get("tope") or "")
        cap, sin_tope, conocido = _tope(tope_txt + " " + validity)
        if not conocido:
            cap2, sin2, ok2 = _tope(terms[:400])
            if ok2 and not cap:
                cap, sin_tope, conocido = cap2, sin2, ok2
        rec = _base(
            chain_id="dia",
            cadena="Día",
            banco=banco,
            percent=pcts[0] if len(pcts) == 1 else None,
            cuotas=_cuotas_txt(offer) if not pcts else "",
            days=dias,
            canal=_canal(str(card.get("channel") or ""), terms),
            cap=cap,
            sin_tope=sin_tope,
            cap_conocido=conocido if (pcts or sin_tope) else False,
            minimo=_minimo(str(card.get("minimum") or "") + " " + terms[:500]),
            oculta=card.get("active") is not True,
            exclusion=str(card.get("exclusion") or ""),
            legal=terms,
            texto=str(card.get("editorTitle") or offer),
        )
        if len(pcts) > 1:
            rec["conflicto"] = "La tarjeta publica más de un porcentaje."
        _cierra_vigencia(rec, [validity, terms[:1500]])
        if "vencid" in _fold(validity):
            rec["conflicto"] = rec["conflicto"] or "La vigencia de la tarjeta está vencida."
        out.append(rec)
    return out


def _flags_dias(flags: dict[str, Any] | None, nombres: list[str] | None) -> set[int]:
    dias: set[int] = set()
    if isinstance(flags, dict) and any(flags.get(k) for k in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")):
        mapa = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
        for clave, n in mapa.items():
            if flags.get(clave):
                dias.add(n)
        return dias
    for nombre in nombres or []:
        n = _dia_idx(str(nombre))
        if n is not None:
            dias.add(n)
    return dias


def _cargar_mas() -> list[dict[str, Any]]:
    path = DATA / "mas-online-promos.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    out = []
    for row in data.get("promos") or []:
        if not isinstance(row, dict):
            continue
        banco = row.get("bank")
        if isinstance(banco, dict):
            banco = banco.get("name") or ""
        banco = str(banco or row.get("title") or "").strip()
        pct = row.get("percent")
        try:
            pct_n = float(pct) if pct is not None else None
        except (TypeError, ValueError):
            pct_n = None
        cuotas_n = row.get("installments_amount")
        cuotas = ""
        if cuotas_n and not pct_n:
            cuotas = f"{cuotas_n} cuotas {row.get('installments_text') or ''}".strip()
        tope_txt = " ".join(row.get("tope_lines") or [])
        sub = str(row.get("subtitle") or "")
        legal = str(row.get("legal") or "")
        label = str(row.get("days_label") or "")
        cap, sin_tope, conocido = _tope(tope_txt + " " + sub)
        stores = row.get("store_flags") or {}
        # El logo no es ecommerce. El canal sale del texto.
        canal = _canal("", f"{sub} {legal} {label}")
        if isinstance(stores, dict) and stores.get("ecommerce") is False and canal == "no indicado":
            canal = "sucursal"
        rec = _base(
            chain_id="masonline",
            cadena="Mas Online",
            banco=banco,
            percent=pct_n,
            cuotas=cuotas,
            days=_flags_dias(row.get("day_flags"), row.get("days")),
            canal=canal,
            cap=cap,
            sin_tope=sin_tope,
            cap_conocido=conocido if pct_n else False,
            minimo=_minimo(sub + " " + tope_txt + " " + legal[:800]),
            oculta=False,
            exclusion="",
            legal=legal,
            texto=label + " " + sub,
        )
        _cierra_vigencia(rec, [label, sub, legal[:1800]])
        # domingo MasGO es sucursal aunque el texto diga tiendas MasGO
        if "masgo" in _fold(label) and "domingo" in _fold(label):
            rec["canal"] = "sucursal"
        out.append(rec)
    return out


def _cargar_cordiez() -> list[dict[str, Any]]:
    path = DATA / "cordiez-promos.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    out = []
    for row in data.get("promos") or []:
        if not isinstance(row, dict):
            continue
        blob_pct = " ".join(row.get("percent_or_installments") or []) if isinstance(row.get("percent_or_installments"), list) else str(row.get("percent_or_installments") or "")
        cuotas_raw = " ".join(row.get("installments") or []) if isinstance(row.get("installments"), list) else ""
        pcts = _pcts(blob_pct)
        dias = set()
        for nombre in row.get("days") or ([row.get("day")] if row.get("day") else []):
            n = _dia_idx(str(nombre))
            if n is not None:
                dias.add(n)
        tope_txt = str(row.get("tope") or "")
        validity = str(row.get("validity") or "")
        cap, sin_tope, conocido = _tope(tope_txt + " " + validity + " " + blob_pct)
        rec = _base(
            chain_id="cordiez",
            cadena="Cordiez",
            banco=str(row.get("bank") or ""),
            percent=pcts[0] if len(pcts) == 1 else None,
            cuotas=_cuotas_txt(cuotas_raw or blob_pct) if not pcts else "",
            days=dias,
            canal=_canal(str(row.get("channel") or ""), ""),
            cap=cap,
            sin_tope=sin_tope,
            cap_conocido=conocido if pcts else False,
            minimo=_minimo(str(row.get("minimum_purchase") or "")),
            exclusion=str(row.get("exclusion") or ""),
            legal=validity,
            texto=blob_pct or cuotas_raw,
        )
        _cierra_vigencia(rec, [validity, tope_txt])
        out.append(rec)
    return out


def _cargar_toledo() -> list[dict[str, Any]]:
    path = DATA / "toledo-promos.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    out = []
    for row in data.get("promos") or []:
        if not isinstance(row, dict):
            continue
        pct = row.get("percent")
        if isinstance(pct, list):
            pcts = []
            for p in pct:
                pcts.extend(_pcts(str(p)))
        else:
            pcts = _pcts(str(pct or ""))
        dias = set()
        # Solo la pestaña del día. El texto largo mete la misma tarjeta en toda la semana.
        n = _dia_idx(str(row.get("day_tab") or ""))
        if n is not None:
            dias.add(n)
        cuotas = str(row.get("installments") or "")
        tope_txt = str(row.get("tope") or "")
        validity = str(row.get("validity") or "")
        cap, sin_tope, conocido = _tope(tope_txt)
        banco = row.get("bank")
        if isinstance(banco, list):
            banco = ", ".join(str(b) for b in banco)
        rec = _base(
            chain_id="toledo",
            cadena="Toledo",
            banco=str(banco or row.get("title") or ""),
            percent=pcts[0] if len(pcts) == 1 else None,
            cuotas=_cuotas_txt(cuotas or str(row.get("title") or "")) if not pcts else "",
            days=dias,
            canal=_canal(str(row.get("channel") or ""), str(row.get("legal") or "")[:400]),
            cap=cap,
            sin_tope=sin_tope,
            cap_conocido=conocido if pcts else False,
            minimo=_minimo(tope_txt + " " + str(row.get("summary") or "")),
            oculta=row.get("visible") is not True,
            exclusion=str(row.get("exclusion") or ""),
            legal=str(row.get("legal") or ""),
            texto=str(row.get("title") or "") + " " + str(row.get("subtitle") or ""),
        )
        _cierra_vigencia(rec, [validity, str(row.get("legal") or "")[:800]])
        out.append(rec)
    return out


def _cargar_josimar() -> list[dict[str, Any]]:
    path = DATA / "josimar-promos.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    out = []
    for row in data.get("promos") or []:
        if not isinstance(row, dict):
            continue
        if row.get("kind") == "envio":
            continue
        dias = set()
        for nombre in row.get("days") or []:
            for parte in re.split(r"\s+y\s+|,\s*", _fold(str(nombre))):
                k = _dia_idx(parte)
                if k is not None:
                    dias.add(k)
        pct = row.get("percent")
        pcts = _pcts(str(pct or ""))
        rec = _base(
            chain_id="josimar",
            cadena="Josimar",
            banco=str(row.get("bank") or row.get("text") or "")[:80],
            percent=pcts[0] if pcts else None,
            cuotas=str(row.get("installments") or ""),
            days=dias,
            canal=_canal(str(row.get("channel") or ""), str(row.get("text") or "")),
            cap_conocido=False,
            oculta=row.get("show_message") is not True,
            legal=str(row.get("text") or ""),
            texto=str(row.get("text") or ""),
        )
        if rec["oculta"]:
            rec["conflicto"] = ""
        out.append(rec)
    return out


def _cargar_la_anonima() -> list[dict[str, Any]]:
    path = DATA / "la-anonima-promos.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    out = []
    for row in data.get("promos") or []:
        if not isinstance(row, dict):
            continue
        dias = set()
        for nombre in row.get("days") or []:
            k = _dia_idx(str(nombre))
            if k is not None:
                dias.add(k)
        pcts = []
        for p in row.get("percent") or []:
            pcts.extend(_pcts(str(p)))
        cuotas = " ".join(row.get("installments") or []) if isinstance(row.get("installments"), list) else ""
        banco = str(row.get("bank") or "")
        if not banco or banco == "None":
            banco = str(row.get("image_alt") or cuotas or "Tarjeta")[:90]
        tope_txt = str(row.get("tope") or "")
        legal = str(row.get("legal") or "")
        cap, sin_tope, conocido = _tope(tope_txt + " " + legal[:300])
        rec = _base(
            chain_id="laanonima",
            cadena="La Anónima",
            banco=banco,
            percent=pcts[0] if len(pcts) == 1 else None,
            cuotas=_cuotas_txt(cuotas) if not pcts else "",
            days=dias,
            canal=_canal(str(row.get("channel") or ""), legal),
            cap=cap,
            sin_tope=sin_tope,
            cap_conocido=conocido if pcts else False,
            minimo=_minimo(str(row.get("minimum_purchase") or "") + " " + legal[:400]),
            exclusion=str(row.get("exclusion") or ""),
            legal=legal,
            texto=banco,
        )
        _cierra_vigencia(rec, [str(row.get("validity") or ""), legal[:600]])
        out.append(rec)
    return out


def _cargar_makro() -> list[dict[str, Any]]:
    path = DATA / "makro-promos.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    out = []
    for row in data.get("promos") or []:
        if not isinstance(row, dict):
            continue
        dias = set()
        for nombre in row.get("days") or []:
            k = DIA_NUM.get(_fold(str(nombre).split()[0] if str(nombre).split() else ""))
            if k is not None:
                dias.add(k)
        heading = str(row.get("day_heading") or "")
        dias |= _dias_mencionados(heading)
        pct = row.get("percent")
        pcts = _pcts(str(pct or "") + " " + str(row.get("headline") or ""))
        tope_txt = str(row.get("tope") or "")
        cap, sin_tope, conocido = _tope(tope_txt + " " + str(row.get("headline") or ""))
        rec = _base(
            chain_id="makro",
            cadena="Makro",
            banco=str(row.get("bank") or row.get("headline") or "")[:90],
            percent=pcts[0] if len(pcts) == 1 else None,
            cuotas=_cuotas_txt(str(row.get("installments") or row.get("headline") or "")) if not pcts else "",
            days=dias,
            canal="sucursal",
            cap=cap,
            sin_tope=sin_tope,
            cap_conocido=conocido if pcts else False,
            minimo=_minimo(str(row.get("minimum_purchase") or "")),
            exclusion=str(row.get("exclusion") or ""),
            legal=" ".join(row.get("lines") or [])[:800] if isinstance(row.get("lines"), list) else "",
            texto=str(row.get("headline") or ""),
        )
        _cierra_vigencia(rec, [str(row.get("validity") or ""), rec["legal"]])
        out.append(rec)
    return out


def _split_pipe(linea: str) -> list[str]:
    return [p.strip() for p in linea.split("|")]


def _cargar_carrefour_md() -> list[dict[str, Any]]:
    path = DATA / "promos-js.md"
    if not path.exists():
        return []
    texto = path.read_text()
    corte = texto.find("## 2. Jumbo")
    bloque = texto if corte < 0 else texto[:corte]
    out = []
    for m in re.finditer(r"^\d+\. \*\*(.+?)\*\*", bloque, re.M):
        partes = _split_pipe(m.group(1))
        if len(partes) < 8:
            continue
        banco = partes[1]
        oferta = partes[2]
        dias_txt = partes[3]
        canal_txt = partes[4]
        tope_txt = partes[5]
        minimo_txt = partes[6]
        vigencia = partes[7]
        condicion = partes[8] if len(partes) > 8 else ""
        pcts = _pcts(oferta)
        cuotas = _cuotas_txt(oferta) if not pcts else ""
        cap, sin_tope, conocido = _tope(tope_txt)
        rec = _base(
            chain_id="carrefour",
            cadena="Carrefour",
            banco=banco,
            percent=pcts[0] if len(pcts) == 1 else None,
            cuotas=cuotas,
            days=_dias_mencionados(dias_txt),
            canal=_canal(canal_txt, condicion),
            cap=cap,
            sin_tope=sin_tope,
            cap_conocido=conocido if pcts else False,
            minimo=_minimo(minimo_txt + " " + condicion) if "no indicado" not in _fold(minimo_txt) else _minimo(condicion),
            exclusion=condicion,
            legal=condicion,
            texto=oferta + " · " + dias_txt,
        )
        _cierra_vigencia(rec, [vigencia, condicion])
        if "exclusiones en legal" in _fold(condicion) or "ver legal" in _fold(condicion):
            rec["exclusion_opaca"] = True
        out.append(rec)
    return out


def _cargar_coto_md() -> list[dict[str, Any]]:
    path = DATA / "promos-js.md"
    if not path.exists():
        return []
    texto = path.read_text()
    out = []
    ini = texto.find("## 5. Coto")
    if ini < 0:
        return []
    bloque = texto[ini:]
    online = bloque.split("### Sucursales", 1)[0]
    for m in re.finditer(r"^- \*\*(.+?)\*\*", online, re.M):
        partes = _split_pipe(m.group(1))
        if len(partes) < 6:
            continue
        banco, oferta, highlighted, canal_txt = partes[0], partes[1], partes[2], partes[3]
        tope_txt = partes[4] if len(partes) > 4 else ""
        vigencia = ""
        condicion = partes[-1] if partes else ""
        for p in partes:
            if p.lower().startswith("vigencia"):
                vigencia = p.split(":", 1)[-1]
            if p.lower().startswith("short"):
                condicion = p.split(":", 1)[-1]
        pcts = _pcts(oferta)
        rec = _base(
            chain_id="cotodigital",
            cadena="Coto",
            banco=banco,
            percent=pcts[0] if len(pcts) == 1 else None,
            cuotas=_cuotas_txt(oferta) if not pcts else "",
            days=_dias_mencionados(highlighted),
            canal="online" if "online" in _fold(canal_txt) else _canal(canal_txt, condicion),
            cap_conocido=False,
            exclusion=condicion,
            legal=condicion,
            texto=oferta,
        )
        if "not stated" in _fold(tope_txt):
            rec["cap_conocido"] = False
        else:
            cap, sin_tope, conocido = _tope(tope_txt)
            rec["cap"], rec["sin_tope"], rec["cap_conocido"] = cap, sin_tope, conocido if pcts else False
        _cierra_vigencia(rec, [vigencia, condicion])
        out.append(rec)
    # Sábado 3, sucursal: el 20% de la app no es Coto Digital.
    suc = ""
    marca = "#### Selected tab: Sabado 3"
    if marca in bloque:
        suc = bloque.split(marca, 1)[1]
        suc = suc.split("#### Selected tab:", 1)[0]
    vistos = set()
    for m in re.finditer(r"(\d+)\s*% DE DESCUENTO\s*\n+([^\n]+)\n+\n*([^\n]+)", suc):
        pct = int(m.group(1))
        titulo = _limpia(m.group(2))
        legal = _limpia(m.group(3))
        clave = (pct, titulo)
        if clave in vistos:
            continue
        vistos.add(clave)
        cap, sin_tope, conocido = _tope(legal)
        rec = _base(
            chain_id="cotodigital",
            cadena="Coto",
            banco=titulo[:90],
            percent=float(pct),
            days={5},
            canal="sucursal",
            cap=cap,
            sin_tope=sin_tope,
            cap_conocido=conocido,
            exclusion=legal,
            legal=legal,
            texto=f"{pct}% sucursal sábado",
        )
        rec["fechas_especificas"] = set()
        if "coto digital" in _fold(legal):
            rec["canal"] = "sucursal"
        out.append(rec)
    return out


def _cargar_promos_semana() -> list[dict[str, Any]]:
    path = DATA / "promos-semana.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for row in data:
        if not isinstance(row, dict):
            continue
        chain_id = str(row.get("chain") or "").strip().lower()
        if not chain_id:
            continue
        cadena = CHAIN_NOMBRE.get(chain_id, chain_id.title())
        banco = str(row.get("bank") or "").strip()
        kind = str(row.get("kind") or "").strip().lower()
        val = row.get("value")

        if kind == "percent":
            pct = float(val) if val is not None else None
            cuotas = ""
        elif kind == "installments":
            pct = None
            if val is not None:
                n_c = int(val) if float(val).is_integer() else val
                cuotas = f"{n_c} cuotas sin interés" if n_c != 1 else "1 cuota sin interés"
            else:
                cuotas = "Cuotas"
        else:
            pct = None
            cuotas = ""

        # ISO 1=lunes...7=domingo -> internal 0=lunes...6=domingo
        days = {int(d) - 1 for d in (row.get("days") or []) if 1 <= int(d) <= 7}

        ch = str(row.get("channel") or "").strip().lower()
        if ch == "both":
            canal = "online y sucursal"
        elif ch == "store":
            canal = "sucursal"
        elif ch == "online":
            canal = "online"
        else:
            canal = _canal(ch, "")

        cap_raw = row.get("cap")
        if cap_raw is not None:
            cap = float(cap_raw)
            sin_tope = False
            cap_conocido = True
        else:
            cap = None
            sin_tope = ("sin tope" in str(row.get("legal") or "").lower())
            cap_conocido = True if sin_tope else False

        min_raw = row.get("minimum")
        minimo = float(min_raw) if min_raw is not None else None

        inicio = date.fromisoformat(row["valid_from"]) if row.get("valid_from") else None
        fin = date.fromisoformat(row["valid_to"]) if row.get("valid_to") else None
        legal = str(row.get("legal") or "")
        do_not_apply = row.get("do_not_apply")

        rec = _base(
            chain_id=chain_id,
            cadena=cadena,
            banco=banco,
            percent=pct,
            cuotas=cuotas,
            days=days,
            canal=canal,
            cap=cap,
            sin_tope=sin_tope,
            cap_conocido=cap_conocido,
            minimo=minimo,
            inicio=inicio,
            fin=fin,
            legal=legal,
            exclusion=legal,
            source_url=str(row.get("source_url") or ""),
            ref=str(row.get("ref") or ""),
            do_not_apply=do_not_apply,
            texto=str(row.get("legal") or "")[:120],
        )
        out.append(rec)
    return out


def cargar(forzar: bool = False) -> list[dict[str, Any]]:
    global _CACHE
    if _CACHE is not None and not forzar:
        return _CACHE
    path_semana = DATA / "promos-semana.json"
    if path_semana.exists():
        recs = _cargar_promos_semana()
        # Josimar y Comodín: sin cambios
        recs.extend(_cargar_josimar())
        _CACHE = recs
        return recs
    recs: list[dict[str, Any]] = []
    for loader in (
        _cargar_dia, _cargar_mas, _cargar_cordiez, _cargar_toledo,
        _cargar_josimar, _cargar_la_anonima, _cargar_makro,
        _cargar_carrefour_md, _cargar_coto_md,
    ):
        try:
            recs.extend(loader())
        except Exception:
            continue
    _marca_conflictos_cruzados(recs)
    _CACHE = recs
    return recs


def _vigente(rec: dict[str, Any], hoy: date) -> tuple[bool, str]:
    if rec.get("oculta"):
        return False, "La tarjeta está oculta o inactiva."
    if rec.get("conflicto"):
        return False, str(rec["conflicto"])
    fin = rec.get("fin")
    inicio = rec.get("inicio")
    if isinstance(fin, date) and fin < hoy:
        return False, f"Venció el {fin.strftime('%d/%m/%Y')}."
    if isinstance(inicio, date) and inicio > hoy:
        return False, f"Empieza el {inicio.strftime('%d/%m/%Y')}."
    especificas = rec.get("fechas_especificas") or set()
    if especificas and hoy not in especificas:
        return False, "Hoy no es una de las fechas publicadas."
    if rec.get("days") and hoy.weekday() not in rec["days"]:
        return False, "Hoy no es el día de la tarjeta."
    return True, ""


def _oferta_txt(rec: dict[str, Any]) -> str:
    if rec.get("percent"):
        n = rec["percent"]
        txt = str(int(n)) if float(n) == int(n) else str(n).replace(".", ",")
        return txt + "%"
    if rec.get("cuotas"):
        return str(rec["cuotas"])
    return "sin porcentaje"


def _tope_txt(rec: dict[str, Any]) -> str:
    if rec.get("sin_tope"):
        return "Sin tope"
    if rec.get("cap"):
        return f"${rec['cap']:,.0f}".replace(",", ".")
    return "Tope no publicado"


def _min_txt(rec: dict[str, Any]) -> str:
    if rec.get("minimo"):
        return f"${rec['minimo']:,.0f}".replace(",", ".")
    return "Sin mínimo publicado"


def _vigencia_txt(rec: dict[str, Any]) -> str:
    ini, fin = rec.get("inicio"), rec.get("fin")
    if isinstance(ini, date) and isinstance(fin, date):
        return f"{ini.strftime('%d/%m/%Y')}–{fin.strftime('%d/%m/%Y')}"
    if isinstance(fin, date):
        return f"hasta {fin.strftime('%d/%m/%Y')}"
    return "Vigencia no publicada"


def _dias_txt(rec: dict[str, Any]) -> str:
    dias = [NOMBRE_DIA[i] for i in sorted(rec.get("days") or [])]
    if not dias:
        return "día no publicado"
    if len(dias) == 7:
        return "todos los días"
    if len(dias) == 1:
        return dias[0]
    return ", ".join(dias[:-1]) + " y " + dias[-1]



_MARCA_BANCO = (
    ("banco de tierra del fuego", "Banco de Tierra del Fuego"),
    ("banco de san juan", "Banco de San Juan"),
    ("banco hipotecario", "Banco Hipotecario"),
    ("banco patagonia", "Banco Patagonia"),
    ("banco columbia", "Banco Columbia"),
    ("banco santa cruz", "Banco Santa Cruz"),
    ("banco santa fe", "Banco Santa Fe"),
    ("banco del chubut", "Banco del Chubut"),
    ("banco chubut", "Banco del Chubut"),
    ("patagonia 365", "Patagonia 365"),
    ("banco comafi", "Banco Comafi"),
    ("banco macro", "Banco Macro"),
    ("banco galicia", "Banco Galicia"),
    ("banco nacion", "Banco Nación"),
    ("banco provincia", "Banco Provincia"),
    ("banco ciudad", "Banco Ciudad"),
    ("banco supervielle", "Banco Supervielle"),
    ("banco credicoop", "Banco Credicoop"),
    ("banco de corrientes", "Banco de Corrientes"),
    ("personal pay", "Personal Pay"),
    ("mercado pago", "Mercado Pago"),
    ("cuenta dni", "Cuenta DNI"),
    ("american express", "American Express"),
    ("american expres", "American Express"),
    ("tarjeta la anonima", "Tarjeta La Anónima"),
    ("tarjeta sol", "Tarjeta Sol"),
    ("banco del sol", "Banco del Sol"),
    ("credito nacion", "Banco Nación"),
    ("naranja x", "Naranja X"),
    ("naranjax", "Naranja X"),
    ("cencopay", "Cencopay"),
    ("mutualcard", "Mutualcard"),
    ("mastercard", "Mastercard"),
    ("supervielle", "Banco Supervielle"),
    ("hipotecario", "Banco Hipotecario"),
    ("comafi", "Banco Comafi"),
    ("galicia", "Banco Galicia"),
    ("finanya", "FinanYa"),
    ("credimas", "Credimas"),
    ("favacard", "Favacard"),
    ("elebar", "Elebar"),
    ("sucredito", "Sucrédito"),
    ("titanio", "Titanio"),
    ("credicuotas", "Credicuotas"),
    ("sidecreer", "Sidecreer"),
    ("cordobesa", "Cordobesa"),
    ("prex", "Prex"),
    ("cabal", "Cabal"),
    ("visa", "Visa"),
    ("icbc", "ICBC"),
    ("bbva", "BBVA"),
    ("santander", "Santander"),
    ("bancor", "BANCOR"),
    ("modo", "MODO"),
    ("bna+", "BNA+"),
    ("bna", "BNA"),
    ("anses", "ANSES"),
    ("yoy", "Yoy"),
    ("macro", "Banco Macro"),
)

_NOMBRE_EXACTO = {
    "anses": "ANSES",
    "modo": "MODO",
    "naranjax": "Naranja X",
    "naranja x": "Naranja X",
    "club la nacion": "Club La Nación",
    "hipotecario modo": "Hipotecario MODO",
    "yoy modo": "Yoy MODO",
    "icbc sueldos": "ICBC Sueldos",
    "banco comafi modo": "Banco Comafi MODO",
}


def _es_texto_de_oferta(fold: str) -> bool:
    """Un titulo de promo, no el nombre de un banco. No va al filtro."""
    if "banks_named" in fold:
        return True
    marcas = (
        "%", "descuento", "pagando", "exclusiv", "cuota", "reintegro",
        "abonan", "atraves", " dto", "sin tope", "por mes", "jubilad",
        "familia militar", "plan z", "aniversario", "hoy ", "todos los",
        "lunes", "martes", "miercoles", "jueves", "viernes", "sabado",
        "domingo", "ahorr", "csi", "en toda tu compra", "dinero en cuenta",
        "con tarjeta",
    )
    return any(m in fold for m in marcas)


def _marcas_en(fold: str) -> list[str]:
    """Bancos nombrados en una frase. La frase no se muestra cortada."""
    ocupados: list[tuple[int, int]] = []
    hallados: list[tuple[int, str]] = []
    claves = sorted(_MARCA_BANCO, key=lambda par: len(par[0]), reverse=True)
    for clave, etiqueta in claves:
        inicio = 0
        while True:
            i = fold.find(clave, inicio)
            if i < 0:
                break
            fin = i + len(clave)
            if i > 0 and fold[i - 1].isalnum():
                inicio = i + 1
                continue
            if fin < len(fold) and fold[fin].isalnum() and not clave.endswith("+"):
                inicio = i + 1
                continue
            if clave == "nacion" and fold[max(0, i - 3):i] == "la ":
                inicio = i + 1
                continue
            if any(not (fin <= a or i >= b) for a, b in ocupados):
                inicio = i + 1
                continue
            ocupados.append((i, fin))
            hallados.append((i, etiqueta))
            inicio = fin
    hallados.sort()
    vistos: list[str] = []
    ya: set[str] = set()
    for _i, etiqueta in hallados:
        if etiqueta in ya:
            continue
        ya.add(etiqueta)
        vistos.append(etiqueta)
    return vistos


def _canon_nombre(raw: str) -> str:
    """Misma etiqueta para Anses/ANSES, Modo/MODO y los id con guion bajo."""
    limpio = re.sub(r"\s+", " ", raw.replace("_", " ")).strip(" .")
    partes = [p.strip(" .") for p in limpio.split(",") if p.strip(" .")]
    salida: list[str] = []
    vistos: set[str] = set()
    for parte in partes:
        clave = _fold(parte)
        etiqueta = _NOMBRE_EXACTO.get(clave)
        if etiqueta is None:
            etiqueta = re.sub(r"(?i)\bmodo\b", "MODO", parte)
            etiqueta = re.sub(r"(?i)\banses\b", "ANSES", etiqueta)
            etiqueta = etiqueta.replace("NaranjaX", "Naranja X").replace("NARANJAX", "Naranja X")
        firma = _fold(etiqueta)
        if firma in vistos:
            continue
        vistos.add(firma)
        salida.append(etiqueta)
    return ", ".join(salida)


def etiqueta_banco(raw: str) -> str:
    """Nombre para el filtro de bancos. No es un precio ni la letra de la promo."""
    texto = str(raw or "").strip()
    if not texto:
        return ""
    if "banks_named" in _fold(texto):
        return "Varios bancos"
    fold = _fold(texto.replace("_", " "))
    if _es_texto_de_oferta(fold):
        marcas = _marcas_en(fold)
        if "MODO" in marcas and len(marcas) == 2:
            otro = next(m for m in marcas if m != "MODO")
            return f"{otro} MODO"
        if marcas:
            return ", ".join(marcas)
        if "bancos seleccionados" in fold or "varios bancos" in fold:
            return "Varios bancos"
        return ""
    return _canon_nombre(texto)


def tarjeta_publica(rec: dict[str, Any]) -> dict[str, Any]:
    crudo = str(rec.get("banco") or "")
    filtro = etiqueta_banco(crudo)
    # La frase sin banco se queda en la tarjeta, no en el filtro.
    titulo = filtro or _canon_nombre(crudo) or crudo.strip()
    base = {
        "cadena": rec["cadena"],
        "chain_id": rec["chain_id"],
        "banco": titulo,
        "banco_filtro": filtro,
        "oferta": _oferta_txt(rec),
        "dias": _dias_txt(rec),
        "canal": rec.get("canal") or "no indicado",
        "tope": _tope_txt(rec),
        "minimo": _min_txt(rec),
        "vigencia": _vigencia_txt(rec),
    }
    if rec.get("do_not_apply"):
        base["do_not_apply"] = rec["do_not_apply"]
    return enriquecer_tarjeta(base)


def activas(hoy: date | None = None) -> list[dict[str, Any]]:
    hoy = hoy or hoy_art()
    out = []
    for rec in cargar():
        if rec["chain_id"] == "makro":
            # se listan en el navegador, no en la búsqueda de precios
            pass
        if rec.get("oculta") or rec.get("conflicto"):
            continue
        fin = rec.get("fin")
        if isinstance(fin, date) and fin < hoy:
            continue
        inicio = rec.get("inicio")
        if isinstance(inicio, date) and inicio > hoy:
            continue
        if not rec.get("percent") and not rec.get("cuotas"):
            continue
        if not rec.get("days"):
            continue
        out.append(rec)
    return out


def catalogo(hoy: date | None = None) -> dict[str, Any]:
    hoy = hoy or hoy_art()
    cards = [tarjeta_publica(r) for r in activas(hoy)]
    por_dia = []
    for i, nombre in DIAS:
        items = [c for c in cards if nombre in c["dias"] or c["dias"] == "todos los días"]
        items.sort(key=lambda c: (c["cadena"], c["banco"]))
        por_dia.append({"dia": nombre, "hoy": i == hoy.weekday(), "items": items})
    bancos: dict[str, list[dict[str, str]]] = {}
    for card in cards:
        filtro = card.get("banco_filtro") or ""
        if not filtro:
            continue
        bancos.setdefault(filtro, []).append(card)
    por_banco = [
        {"banco": banco, "items": items}
        for banco, items in sorted(bancos.items(), key=lambda kv: kv[0].casefold())
    ]
    notas = [
        "El precio grande de cada súper es el de ahora. El tachado, si aparece, es contexto de la tienda y no se compara.",
        "Una tarjeta oculta, vencida o con dos fechas que no coinciden no se muestra acá.",
        "Josimar: las promos de banco tienen showMessage en falso y no se cuentan como vigentes.",
        "Makro tiene promos de sucursal y no tiene precio de producto: no entra en la búsqueda.",
        "El Abastecedor y Comodín no tienen un archivo de promos usable: solo precio de góndola.",
        "Coto: el porcentaje del sábado en la app es de sucursal y no se resta del precio de Coto Digital.",
    ]
    return {
        "hoy": hoy.isoformat(),
        "dia": NOMBRE_DIA[hoy.weekday()],
        "por_dia": por_dia,
        "por_banco": por_banco,
        "marcas": marcas_meta(),
        "notas": notas,
        "n": len(cards),
    }


def _producto_excluido(rec: dict[str, Any], nombre: str) -> str:
    exclusion = _fold(rec.get("exclusion") or "")
    legal = _fold(rec.get("legal") or "")
    blob = exclusion + " " + legal
    nombre_f = _fold(nombre)
    if rec.get("exclusion_opaca") or "exclusiones en legal" in blob or "aplican exclusiones" in exclusion:
        if "no incluye" not in blob and "excepto" not in blob:
            return "La letra menciona exclusiones y el dato guardado no lista si este producto entra."
    categorias = (
        "yerba", "arroz", "aceite", "harina", "leche", "azucar", "cerveza", "vino",
        "gaseosa", "carne", "carniceria", "electro", "celular", "queso",
    )
    if "unicamente en los productos" in blob or "solo en los productos" in blob:
        if not any(cat in nombre_f and cat in blob for cat in categorias):
            return "La promo nombra productos y este no está en la lista."
    for cat, palabras in (
        ("carniceria", ("carne", "carnicer")),
        ("electro", ("electro", "heladera", "celular")),
        ("yerba", ("yerba",)),
        ("aceite", ("aceite",)),
        ("harina", ("harina",)),
        ("leche", ("leche",)),
    ):
        if cat in blob and any(p in nombre_f for p in palabras):
            if "no incluye" in blob or "excluye" in blob or "excepto" in blob:
                return f"La letra chica excluye {cat}."
    return ""



def _no_acumula(rec: dict[str, Any]) -> bool:
    """La letra dice que no se suma a otro descuento. Incluye el typo "acumable"."""
    blob = _fold(" ".join(str(rec.get(k) or "") for k in ("legal", "texto", "exclusion")))
    return re.search(r"no\s+acum(?:ul)?able|no\s+acumula\b|no\s+es\s+acumulable", blob) is not None


def puede_restar(
    rec: dict[str, Any],
    nombre: str,
    precio: float,
    hoy: date,
    *,
    ya_descuento: bool = False,
) -> tuple[bool, str, float]:
    ok, motivo = _vigente(rec, hoy)
    if not ok:
        return False, motivo, precio
    if rec.get("do_not_apply"):
        return False, str(rec["do_not_apply"]), precio
    if not rec.get("days") and not rec.get("fechas_especificas"):
        return False, "La tarjeta no publica el día.", precio
    if not rec.get("percent"):
        if rec.get("cuotas"):
            return False, "Es una promo de cuotas, no un porcentaje.", precio
        return False, "La tarjeta no publica un porcentaje.", precio
    if rec.get("canal") not in {"online", "online y sucursal"}:
        return False, "Vale en sucursal, no en el precio online.", precio
    # Sin un tope en pesos no se resta. "Sin tope" queda mostrado aparte
    # hasta que esa regla esté explícita (hoy no lo está).
    if rec.get("sin_tope") or not rec.get("cap"):
        if rec.get("sin_tope"):
            return False, "Dice sin tope. No se resta.", precio
        return False, "El tope no está publicado.", precio
    # Caso real: Playadito 1 kg en Mas Online se paga $3.969 (el 25% de la
    # tienda ya está adentro). Columbia dice que no acumula: no se resta el 20%.
    if _no_acumula(rec):
        if ya_descuento:
            return False, "La letra dice que no acumula y este precio ya tiene un descuento de la tienda.", precio
        return False, "La letra dice que no acumula con otros descuentos.", precio
    exclu = _producto_excluido(rec, nombre)
    if exclu:
        return False, exclu, precio
    minimo = rec.get("minimo")
    if isinstance(minimo, (int, float)) and precio < float(minimo):
        return False, "No llega al mínimo de compra de la promo.", precio
    descuento = precio * float(rec["percent"]) / 100.0
    if rec.get("cap"):
        descuento = min(descuento, float(rec["cap"]))
    total = round(precio - descuento, 2)
    if total <= 0 or total > precio:
        return False, "El descuento no se puede calcular sin pasar el precio de góndola.", precio
    return True, "", total


def aplicar_oferta(
    tienda_id: str,
    nombre: str,
    precio: float,
    hoy: date | None = None,
    *,
    ya_descuento: bool = False,
) -> dict[str, Any]:
    hoy = hoy or hoy_art()
    candidatos = []
    for rec in cargar():
        if rec["chain_id"] != tienda_id:
            continue
        if rec.get("days") and hoy.weekday() not in rec["days"]:
            if not (rec.get("fechas_especificas") and hoy in rec["fechas_especificas"]):
                continue
        ok, motivo, total = puede_restar(rec, nombre, precio, hoy, ya_descuento=ya_descuento)
        candidatos.append((ok, total, motivo, rec))
    aplicados = [c for c in candidatos if c[0]]
    promo = None
    total = precio
    promos = []
    if aplicados:
        ok, total, motivo, rec = min(aplicados, key=lambda c: c[1])
        promo = {
            "aplicada": True,
            "banco": rec["banco"],
            "descuento": _oferta_txt(rec),
            "motivo": "",
            "total": total,
            "canal": rec.get("canal") or "",
            "tope": _tope_txt(rec),
        }
        promos.append(promo)
    elif candidatos:
        # La tarjeta de hoy que no se restó, antes que una que todavía no corre.
        def _orden(c):
            rec = c[3]
            vigente = _vigente(rec, hoy)[0]
            return (0 if vigente else 1, 0 if rec.get("percent") else 1, c[2])
        candidatos.sort(key=_orden)
        _ok, _total, motivo, rec = candidatos[0]
        promo = {
            "aplicada": False,
            "banco": rec["banco"],
            "descuento": _oferta_txt(rec),
            "motivo": motivo,
            "total": precio,
            "canal": rec.get("canal") or "",
            "tope": _tope_txt(rec),
        }
        promos.append(promo)
    return {"total": total, "promo": promo, "promos": promos}


def notas_cadenas_sin_promo() -> list[dict[str, Any]]:
    return [
        {"tienda": "El Abastecedor", "ok": False, "nota": "No hay un archivo de promos usable. Solo el precio de góndola.", "items": [], "url": "", "http": 0},
        {"tienda": "Comodín", "ok": False, "nota": "No hay un archivo de promos usable. Solo el precio de góndola.", "items": [], "url": "", "http": 0},
        {"tienda": "Makro", "ok": False, "nota": "No se muestra en la búsqueda: promos de sucursal y sin precio de producto.", "items": [], "url": "", "http": 0},
    ]
