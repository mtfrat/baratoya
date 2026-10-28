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
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from baratoya.brand_logos import (
        _etiqueta_corta,
        enriquecer_tarjeta,
        meta_publica as marcas_meta,
        resolver_marcas,
    )
except ImportError:
    from brand_logos import (
        _etiqueta_corta,
        enriquecer_tarjeta,
        meta_publica as marcas_meta,
        resolver_marcas,
    )

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
    "abastecedor": "abastecedor", "el abastecedor": "abastecedor",
    "comodin": "comodin", "comodín": "comodin",
}
CHAIN_NOMBRE = {
    "dia": "Día", "carrefour": "Carrefour", "masonline": "Mas Online",
    "jumbo": "Jumbo", "disco": "Disco", "vea": "Vea", "cordiez": "Cordiez",
    "toledo": "Toledo", "josimar": "Josimar", "laanonima": "La Anónima",
    "cotodigital": "Coto Digital", "makro": "Makro",
    "supermami": "Super Mami", "abastecedor": "El Abastecedor", "comodin": "Comodín",
    "maxiconsumo": "Maxiconsumo",
}

# BaratoYa es para CABA. Estas cadenas no tienen sucursales en CABA
# (Cordiez y Super Mami: Córdoba; Toledo: Mar del Plata; La Anónima: Patagonia
# y provincia; Comodín: Jujuy, Salta y Tucumán). No se muestran ni en promos
# ni en resultados. El código de lectura queda por si se suman otras zonas.
FUERA_DE_CABA = frozenset({"cordiez", "toledo", "laanonima", "supermami", "comodin"})


def es_de_caba(chain_id: str) -> bool:
    return str(chain_id or "").strip().casefold() not in FUERA_DE_CABA


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
        # Josimar: sin cambios
        recs.extend(_cargar_josimar())
        recs = [r for r in recs if es_de_caba(r.get("chain_id") or "")]
        _CACHE = recs
        return recs
    recs: list[dict[str, Any]] = []
    for loader in (
        _cargar_dia, _cargar_mas, _cargar_josimar, _cargar_makro,
        _cargar_carrefour_md, _cargar_coto_md,
    ):
        try:
            recs.extend(loader())
        except Exception:
            continue
    recs = [r for r in recs if es_de_caba(r.get("chain_id") or "")]
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
        "El Abastecedor no tiene un archivo de promos usable: solo precio de góndola.",
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



# "no acumulable", "no acumulabe" (typo real), "no es/son acumulable(s)",
# "no se acumula", "no se superponen ni son acumulativos", "no combinable".
# Ojo: "acumulable con otras promociones" (sin "no") sí se suma.
_NO_ACUMULA_RE = re.compile(
    r"\bno\s+(?:(?:es|son|sera|seran|se|podra|podran|resulta|resultan)\s+)?"
    r"(?:acum[a-z]*|combinab[a-z]*|superpon[a-z]*)"
)


def _no_acumula(rec: dict[str, Any]) -> bool:
    """La letra dice que no se suma a otro descuento. Incluye typos ("acumable", "acumulabe")."""
    blob = _fold(" ".join(str(rec.get(k) or "") for k in ("legal", "texto", "exclusion")))
    return _NO_ACUMULA_RE.search(blob) is not None


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
    bancos_permitidos: list[str] | set[str] | None = None,
) -> dict[str, Any]:
    hoy = hoy or hoy_art()
    permitidos: set[str] | None = None
    if bancos_permitidos:
        permitidos = {str(b).strip().casefold() for b in bancos_permitidos if str(b).strip()}
        if not permitidos:
            permitidos = None

    candidatos = []
    for rec in cargar():
        if rec["chain_id"] != tienda_id:
            continue
        if rec.get("days") and hoy.weekday() not in rec["days"]:
            if not (rec.get("fechas_especificas") and hoy in rec["fechas_especificas"]):
                continue
        if permitidos is not None:
            meta = resolver_marcas(rec.get("banco") or "")
            bids = set(meta.get("brand_ids") or [])
            gids = set(meta.get("group_ids") or [])
            fold_banco = _fold(rec.get("banco") or "")
            match = bool(bids.intersection(permitidos) or gids.intersection(permitidos) or any(p in fold_banco for p in permitidos))
            if not match:
                continue
        ok, motivo, total = puede_restar(rec, nombre, precio, hoy, ya_descuento=ya_descuento)
        if ok and total < precio:
            candidatos.append((ok, total, motivo, rec))

    aplicados = [c for c in candidatos if c[0]]
    promo = None
    total = precio
    promos = []
    if aplicados:
        ok, total, motivo, rec = min(aplicados, key=lambda c: c[1])
        meta = resolver_marcas(rec.get("banco") or "")
        label = meta.get("brand_label") or _etiqueta_corta(rec.get("banco") or "")
        descuento_txt = _oferta_txt(rec)
        promo = {
            "aplicada": True,
            "banco": label,
            "banco_crudo": rec.get("banco") or "",
            "brand_ids": meta.get("brand_ids") or [],
            "descuento": descuento_txt,
            "linea_corta": f"{label} {descuento_txt}".strip(),
            "motivo": "",
            "total": total,
            "canal": rec.get("canal") or "",
            "tope": _tope_txt(rec),
        }
        promos.append(promo)
    return {"total": total, "promo": promo, "promos": promos}


def notas_cadenas_sin_promo() -> list[dict[str, Any]]:
    return [
        {"tienda": "El Abastecedor", "ok": False, "nota": "No hay un archivo de promos usable. Solo el precio de góndola.", "items": [], "url": "", "http": 0},
        {"tienda": "Makro", "ok": False, "nota": "No se muestra en la búsqueda: promos de sucursal y sin precio de producto.", "items": [], "url": "", "http": 0},
    ]


def normalizar_cadena_id(val: str) -> str:
    s = _fold(val).strip()
    if s in CHAIN_ID:
        return CHAIN_ID[s]
    clean = s.replace("-", "").replace("_", "").replace(" ", "")
    if clean in CHAIN_ID:
        return CHAIN_ID[clean]
    if s.startswith("el "):
        sin_el = s[3:].strip()
        if sin_el in CHAIN_ID:
            return CHAIN_ID[sin_el]
    for k, v in CHAIN_ID.items():
        if _fold(k) == s or _fold(k).replace(" ", "") == clean:
            return v
    return clean


def promos_para_cadena(
    cadena: str,
    dia: str | int | None = None,
    precio: float | None = None,
    nombre: str = "",
    hoy: date | None = None,
    *,
    ya_descuento: bool = False,
) -> dict[str, Any]:
    """Todas las promociones de una cadena para un día dado, calculando el precio final de cada una."""
    hoy_date = hoy or hoy_art()
    cid = normalizar_cadena_id(cadena)
    nombre_cadena = CHAIN_NOMBRE.get(cid, cadena.strip().title() if cadena else "Supermercado")

    dia_str = str(dia or "hoy").strip().lower() if dia is not None else "hoy"
    if dia_str in {"hoy", ""}:
        dia_idx = hoy_date.weekday()
        target_date = hoy_date
        dia_nombre = NOMBRE_DIA.get(dia_idx, "hoy")
    elif dia_str in {"todos", "todas", "toda la semana"}:
        dia_idx = None
        target_date = hoy_date
        dia_nombre = "todos los días"
    else:
        dia_idx = _dia_idx(dia_str)
        if dia_idx is None:
            dia_idx = hoy_date.weekday()
            target_date = hoy_date
            dia_nombre = NOMBRE_DIA.get(dia_idx, "hoy")
        else:
            diff = dia_idx - hoy_date.weekday()
            target_date = hoy_date + timedelta(days=diff)
            dia_nombre = NOMBRE_DIA.get(dia_idx, dia_str)

    precio_num = (
        float(precio)
        if precio is not None and not isinstance(precio, bool) and float(precio) > 0
        else None
    )

    sin_promo_map = {
        "abastecedor": "El Abastecedor no tiene promociones bancarias publicadas. Solo precio de góndola.",
        "comodin": "Comodín no tiene promociones bancarias publicadas. Solo precio de góndola.",
        "makro": "Makro no tiene precio de producto en el buscador.",
    }
    if cid in sin_promo_map:
        return {
            "cadena": nombre_cadena,
            "chain_id": cid,
            "dia": dia_nombre,
            "dia_idx": dia_idx,
            "fecha": target_date.isoformat(),
            "precio_gondola": precio_num,
            "nombre_producto": nombre,
            "nota": sin_promo_map[cid],
            "total": 0,
            "promos": [],
        }

    recs = cargar()
    items: list[dict[str, Any]] = []
    for rec in recs:
        if rec.get("chain_id") != cid:
            continue
        if rec.get("oculta") or rec.get("conflicto"):
            continue
        fin = rec.get("fin")
        if isinstance(fin, date) and fin < target_date:
            continue
        inicio = rec.get("inicio")
        if isinstance(inicio, date) and inicio > target_date:
            continue
        if dia_idx is not None:
            especificas = rec.get("fechas_especificas") or set()
            if especificas:
                if target_date not in especificas:
                    continue
            elif rec.get("days") and dia_idx not in rec["days"]:
                continue

        card_pub = tarjeta_publica(rec)
        banco_titulo = card_pub.get("banco") or rec.get("banco") or ""
        oferta_txt = card_pub.get("oferta") or _oferta_txt(rec)
        cuotas_txt = str(rec.get("cuotas") or "")

        if precio_num is not None:
            ok, motivo, total = puede_restar(rec, nombre, precio_num, target_date, ya_descuento=ya_descuento)
            if ok and total < precio_num:
                descuento = round(precio_num - total, 2)
                precio_final = total
                puede = True
            else:
                descuento = 0.0
                precio_final = precio_num
                puede = False
        else:
            ok, motivo, _ = puede_restar(rec, nombre, 1000.0, target_date, ya_descuento=ya_descuento)
            puede = ok
            descuento = 0.0
            precio_final = None

        partes_legales = []
        if rec.get("cap"):
            partes_legales.append(f"Tope {_tope_txt(rec)}")
        elif rec.get("sin_tope"):
            partes_legales.append("Sin tope")
        if rec.get("minimo"):
            partes_legales.append(f"Mín. {_min_txt(rec)}")
        canal = rec.get("canal")
        if canal and canal != "no indicado":
            partes_legales.append(canal.capitalize())
        if rec.get("fin"):
            partes_legales.append(f"Hasta {rec['fin'].strftime('%d/%m/%Y')}")
        linea_corta = " · ".join(partes_legales)

        # Orden:
        # 0: descuento efectivo aplicado (menor precio final primero)
        # 1: promo con porcentaje que no resta (do_not_apply, sin tope, etc.)
        # 2: cuotas al final
        if puede and descuento > 0:
            tipo_orden = 0
        elif cuotas_txt:
            tipo_orden = 2
        else:
            tipo_orden = 1

        promo_item = {
            "banco": banco_titulo,
            "banco_crudo": rec.get("banco") or "",
            "brand_ids": card_pub.get("brand_ids") or [],
            "brand_label": card_pub.get("brand_label") or banco_titulo,
            "variant_label": card_pub.get("variant_label") or "",
            "group_ids": card_pub.get("group_ids") or [],
            "oferta": oferta_txt,
            "percent": rec.get("percent"),
            "cuotas": cuotas_txt,
            "puede_restar": puede,
            "motivo": motivo,
            "descuento": descuento,
            "precio_gondola": precio_num,
            "precio_final": precio_final,
            "cap": rec.get("cap"),
            "sin_tope": bool(rec.get("sin_tope")),
            "tope": _tope_txt(rec),
            "minimo": _min_txt(rec),
            "canal": rec.get("canal") or "no indicado",
            "vigencia": _vigencia_txt(rec),
            "do_not_apply": rec.get("do_not_apply"),
            "linea_corta": linea_corta,
            "_tipo_orden": tipo_orden,
        }
        items.append(promo_item)

    items.sort(
        key=lambda p: (
            p["_tipo_orden"],
            p["precio_final"] if p["precio_final"] is not None and p["_tipo_orden"] == 0 else 999999999,
            -p["descuento"],
            -(p["percent"] or 0),
            p["banco"],
        )
    )

    for p in items:
        p.pop("_tipo_orden", None)

    return {
        "cadena": nombre_cadena,
        "chain_id": cid,
        "dia": dia_nombre,
        "dia_idx": dia_idx,
        "fecha": target_date.isoformat(),
        "precio_gondola": precio_num,
        "nombre_producto": nombre,
        "nota": "",
        "total": len(items),
        "promos": items,
    }


# Página pública. Mismos registros que el catálogo de la cuenta (activas +
# tarjeta_publica). No calcula el precio de un producto.
SEO_PATH = "/promos-bancarias-supermercados"
SEO_URL = "https://baratoya.app" + SEO_PATH
# ≤60. Conserva "promos bancarias supermercados" y suma CABA, que es el alcance real.
SEO_TITLE = "Promos bancarias supermercados hoy en CABA | BaratoYa"
_ORDEN_CADENA = (
    "dia", "carrefour", "cotodigital", "jumbo", "disco", "vea",
    "masonline", "makro", "maxiconsumo", "josimar", "abastecedor",
)
# Slug público y nombre de la URL. Coto se llama Coto en el título (cabe en
# 60 caracteres y es la búsqueda); el archivo sigue diciendo Coto Digital.
_CADENAS_SEO = (
    ("dia", "dia", "Día"),
    ("carrefour", "carrefour", "Carrefour"),
    ("cotodigital", "coto", "Coto"),
    ("jumbo", "jumbo", "Jumbo"),
    ("disco", "disco", "Disco"),
    ("vea", "vea", "Vea"),
    ("masonline", "mas-online", "Mas Online"),
    ("makro", "makro", "Makro"),
    ("maxiconsumo", "maxiconsumo", "Maxiconsumo"),
)
_SLUG_POR_ID = {cid: slug for cid, slug, _nombre in _CADENAS_SEO}
_ID_POR_SLUG = {slug: cid for cid, slug, _nombre in _CADENAS_SEO}
_NOMBRE_SEO = {cid: nombre for cid, _slug, nombre in _CADENAS_SEO}
_MESES_LARGO = (
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def fecha_larga(d: date) -> str:
    return f"{d.day} de {_MESES_LARGO[d.month]} de {d.year}"


def fecha_datos_promos(hoy: date | None = None) -> date | None:
    """Fecha que está en el archivo. No es un timestamp inventado.

    Si el JSON trae fetched_at, se usa esa fecha. promos-semana.json es una
    lista sin ese campo: queda el valid_from más nuevo del archivo que ya
    empezó. Una promo que arranca más adelante en la semana (p. ej. el 23/10
    en la carga del 19/10) no es la fecha de la carga: daba "Actualizado el
    23 de octubre" y <lastmod> en el futuro en el sitemap (visto 20/10).
    """
    hoy = hoy or hoy_art()
    path = DATA / "promos-semana.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict):
        raw = data.get("fetched_at") or data.get("updated_at")
        if raw:
            try:
                return min(date.fromisoformat(str(raw)[:10]), hoy)
            except ValueError:
                pass
        rows = data.get("promos") if isinstance(data.get("promos"), list) else []
    elif isinstance(data, list):
        rows = data
    else:
        return None
    fechas: list[date] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("valid_from"):
            continue
        try:
            fecha = date.fromisoformat(str(row["valid_from"])[:10])
        except ValueError:
            continue
        if fecha <= hoy:
            fechas.append(fecha)
    return max(fechas) if fechas else None


def lastmod_promos(hoy: date | None = None) -> str:
    """Fecha del sitemap de promos y descuentos.

    La más nueva entre el dato del archivo y el día en Argentina. La sección
    Hoy cambia con el calendario; una fecha fija en el XML se queda atrás.
    """
    candidatos = [hoy or hoy_art()]
    datos = fecha_datos_promos(candidatos[0])
    if datos is not None:
        candidatos.append(datos)
    return max(candidatos).isoformat()


def _respuesta_promos_hoy(n_hoy: int | None, cadenas_hoy: int | None) -> str:
    """Apunta a la sección Hoy. Sin un porcentaje de ahorro inventado."""
    detalle = (
        "banco o tarjeta, porcentaje o cuotas, los días y el tope si está publicado. "
        "Si la cadena no publica un dato, no lo completamos."
    )
    if n_hoy is None:
        return "En la sección Hoy de esta página, por cada cadena de supermercado de CABA: " + detalle
    if n_hoy <= 0:
        return (
            "Hoy no hay promos vigentes cargadas. La sección Hoy las lista por cadena "
            "cuando las hay: " + detalle
        )
    promo = "1 promo" if n_hoy == 1 else f"{n_hoy} promos"
    if cadenas_hoy is None:
        donde = "supermercados de CABA"
    elif cadenas_hoy == 1:
        donde = "1 cadena de supermercados de CABA"
    else:
        donde = f"{cadenas_hoy} cadenas de supermercados de CABA"
    return f"Hoy hay {promo} en {donde}. La sección Hoy las lista por cadena: {detalle}"


def faq_promos_publicas(
    n_hoy: int | None = None,
    cadenas_hoy: int | None = None,
) -> list[dict[str, str]]:
    """Hechos del cálculo que ya hace la cuenta. Sin cifras de ahorro."""
    return [
        {
            "q": "¿Cuáles son las promos bancarias de supermercados hoy?",
            "a": _respuesta_promos_hoy(n_hoy, cadenas_hoy),
        },
        {
            "q": "¿Cómo se calcula el descuento?",
            "a": (
                "En la búsqueda, BaratoYa toma el precio de góndola y resta un porcentaje "
                "solo si la promo está vigente ese día, tiene un tope en pesos, aplica a "
                "online o a online y sucursal, y la letra no dice que no acumula. Si dice "
                "sin tope, o el tope no está publicado, no se resta. Si trae una nota de "
                "por qué no se aplica, tampoco. Las de sucursal se listan y no se restan "
                "del precio online. Las cuotas no se restan: no son un porcentaje. El "
                "precio de un producto se ve con la cuenta. Esta página lista las promos, "
                "no ese precio."
            ),
        },
        {
            "q": "¿Qué es el tope?",
            "a": (
                "Es el máximo de reintegro que publica la promo, en pesos. Si el dato dice "
                "sin tope, se muestra así. Si la cadena no publica un tope, no inventamos uno "
                "y esa promo no se descuenta en la búsqueda."
            ),
        },
        {
            "q": "¿Qué días aplica cada promo?",
            "a": (
                "Los días que publicó la cadena o el banco. Una promo entra en un día si "
                "ese día está en su lista y la fecha cae entre el inicio y el fin de "
                "vigencia. El día se cuenta con la hora de Argentina."
            ),
        },
        {
            "q": "¿Las promos se acumulan?",
            "a": (
                "Si la letra dice que no acumula con otros descuentos, BaratoYa no la suma. "
                "En la búsqueda se aplica una sola de las promos que sí se pueden restar: "
                "la que deja el precio más bajo. No se suman dos porcentajes."
            ),
        },
        {
            "q": "¿BaratoYa vende los productos del súper?",
            "a": (
                "No. BaratoYa no vende ni entrega. Muestra precios y promos para comparar. "
                "La compra se hace en la tienda de la cadena."
            ),
        },
    ]


def _url_http(url: str) -> str:
    from urllib.parse import urlparse

    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return raw
    return ""


def _item_publico(rec: dict[str, Any]) -> dict[str, Any] | None:
    card = tarjeta_publica(rec)
    banco = str(card.get("banco") or "").strip()
    oferta = str(card.get("oferta") or "").strip()
    if not banco or not oferta or oferta == "sin porcentaje":
        return None
    dias = str(card.get("dias") or "").strip()
    if dias == "día no publicado":
        dias = ""
    item: dict[str, Any] = {
        "chain_id": rec.get("chain_id") or "",
        "cadena": rec.get("cadena") or "",
        "banco": banco,
        "oferta": oferta,
        "dias": dias,
        "day_ids": sorted(int(d) for d in (rec.get("days") or [])),
    }
    if rec.get("sin_tope"):
        item["tope"] = "sin tope"
    elif rec.get("cap"):
        item["tope"] = "tope " + _tope_txt(rec)
        try:
            item["tope_num"] = float(rec["cap"])
        except (TypeError, ValueError):
            pass
    if rec.get("minimo"):
        item["minimo"] = _min_txt(rec)
    canal = str(rec.get("canal") or "").strip()
    if canal and canal != "no indicado":
        item["canal"] = canal
    if isinstance(rec.get("inicio"), date) or isinstance(rec.get("fin"), date):
        vig = _vigencia_txt(rec)
        if vig and vig != "Vigencia no publicada":
            item["vigencia"] = vig
    nota = str(rec.get("do_not_apply") or "").strip().rstrip(".")
    if nota:
        item["nota"] = nota
    fuente = _url_http(str(rec.get("source_url") or ""))
    if fuente:
        item["fuente"] = fuente
    pct = rec.get("percent")
    if isinstance(pct, (int, float)) and not isinstance(pct, bool) and pct > 0:
        item["percent"] = float(pct)
    return item


def _orden_cadena(chain_id: str) -> tuple[int, str]:
    try:
        return (_ORDEN_CADENA.index(chain_id), chain_id)
    except ValueError:
        return (len(_ORDEN_CADENA), chain_id)


def _agrupar_cadenas(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grupos: dict[str, dict[str, Any]] = {}
    for it in items:
        cid = str(it.get("chain_id") or "")
        if not cid:
            continue
        grupo = grupos.get(cid)
        if grupo is None:
            slug = _SLUG_POR_ID.get(cid, "")
            grupo = {
                "chain_id": cid,
                "cadena": it.get("cadena") or cid,
                "slug": slug,
                "href": f"{SEO_PATH}/{slug}" if slug else "",
                "fuentes": [],
                "promos": [],
            }
            grupos[cid] = grupo
        grupo["promos"].append(it)
        fuente = it.get("fuente")
        if fuente and fuente not in grupo["fuentes"]:
            grupo["fuentes"].append(fuente)
    salida = [grupos[cid] for cid in sorted(grupos, key=_orden_cadena)]
    for grupo in salida:
        grupo["promos"].sort(key=lambda it: ((it.get("banco") or "").casefold(), it.get("oferta") or ""))
    return salida


def _ld(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


# (día, lista de cargar(), tarjetas). Una página pública pedía esta lista ~200 veces
# (footer, home, cada ficha de precio vía cadenas_indexables) y cada vez rearmaba
# ~270 tarjetas con logos: 2-5 s de CPU por request. Los datos solo cambian con el
# día de Argentina o con un cargar() nuevo (deploy o forzar=True), así que se arma
# una vez por día y por carga. La comparación es por identidad de la lista, no por id().
_ITEMS_MEMO: tuple[date, list[dict[str, Any]], list[dict[str, Any]]] | None = None


def _items_publicos_calc(hoy: date) -> list[dict[str, Any]]:
    items = []
    for rec in activas(hoy):
        item = _item_publico(rec)
        if item is not None:
            items.append(item)
    return items


def _items_publicos(hoy: date) -> list[dict[str, Any]]:
    """Las mismas tarjetas que lista el hub. Sin precio de producto.

    Devuelve copias: quien llama puede ordenar o tocar una tarjeta sin cambiar la memo.
    """
    global _ITEMS_MEMO
    recs = cargar()
    memo = _ITEMS_MEMO
    if memo is None or memo[0] != hoy or memo[1] is not recs:
        memo = (hoy, recs, _items_publicos_calc(hoy))
        _ITEMS_MEMO = memo
    return [{**it, "day_ids": list(it.get("day_ids") or [])} for it in memo[2]]


def descripcion_hub(n: int, cadenas_n: int, n_hoy: int) -> str:
    """Meta del hub. Arranca con el conteo de la semana. ≤155. Sin un % inventado."""
    cierre = "BaratoYa no vende ni entrega."
    if n <= 0:
        opciones = (
            f"No hay promos bancarias cargadas esta semana en supermercados de CABA. {cierre}",
        )
    else:
        promos = "1 promo bancaria" if n == 1 else f"{n} promos bancarias"
        cadenas = "1 supermercado" if cadenas_n == 1 else f"{cadenas_n} supermercados"
        if n_hoy <= 0:
            opciones = (
                f"{promos} en {cadenas} de CABA esta semana. Hoy no hay promos cargadas. {cierre}",
                f"{promos} en {cadenas} de CABA. Hoy no hay promos cargadas. {cierre}",
                f"{promos} en {cadenas} de CABA. {cierre}",
            )
        else:
            hoy = "Hoy hay 1 promo" if n_hoy == 1 else f"Hoy hay {n_hoy} promos"
            opciones = (
                (
                    f"{promos} en {cadenas} de CABA esta semana. {hoy}: banco o tarjeta, "
                    f"días y tope por cadena. {cierre}"
                ),
                (
                    f"{promos} en {cadenas} de CABA esta semana. {hoy}. "
                    f"Banco o tarjeta, días y tope. {cierre}"
                ),
                f"{promos} en {cadenas} de CABA. {hoy}. {cierre}",
                f"{promos} en {cadenas} de CABA. {cierre}",
            )
    for texto in opciones:
        if len(texto) <= 155 and '"' not in texto and "<" not in texto:
            return texto
    raise ValueError(f"descripcion del hub no entra en 155 ({n}, {cadenas_n}, {n_hoy})")


def _matriz_semana(items: list[dict[str, Any]], wd: int) -> dict[str, Any]:
    """Cadena × día: el mayor % publicado (o "cuotas"). Para elegir qué día ir a cada súper.

    Sale de las mismas tarjetas que el hub; nada se completa a mano. "mejor" marca el
    día (o los días) con el % más alto de cada cadena.
    """
    dias = [
        {"idx": d["idx"], "nombre": d["nombre"], "plural": d["plural"],
         "href": f"{DESCUENTOS_PATH}/{d['slug']}", "hoy": d["idx"] == wd}
        for d in _DIAS_SEO
    ]
    filas = []
    for g in _agrupar_cadenas(items):
        celdas = []
        for d in dias:
            propios = _items_de(g["promos"], int(d["idx"]))
            pct, _ = _top_descuento(propios)
            celdas.append({
                "idx": d["idx"],
                "pct": pct,
                "txt": f"{_pct_publico(pct)}%" if pct is not None else ("cuotas" if propios else "—"),
                "hoy": d["hoy"],
                "mejor": False,
            })
        mejor = max((c["pct"] for c in celdas if c["pct"] is not None), default=None)
        mejores = []
        for c, d in zip(celdas, dias):
            if mejor is not None and c["pct"] == mejor:
                c["mejor"] = True
                mejores.append(d["nombre"])
        filas.append({
            "chain_id": g["chain_id"],
            "cadena": g["cadena"],
            "href": g["href"],
            "celdas": celdas,
            "mejor_pct": mejor,
            "mejor_txt": _pct_publico(mejor) if mejor is not None else "",
            "mejores_dias": mejores,
        })
    return {"dias": dias, "filas": filas}


def _top_hub(por_cadena: list[dict[str, Any]]) -> dict[str, Any] | None:
    """El mayor % de hoy, en qué cadenas y, si es uno solo, con qué banco o billetera."""
    con = [f for f in por_cadena if f["top_pct"] is not None]
    if not con:
        return None
    mx = max(f["top_pct"] for f in con)
    filas = [f for f in con if f["top_pct"] == mx]
    bancos: set[str] = set()
    for f in filas:
        for raw in f["bancos"]:
            bancos.add(banco_canonico(raw) or raw)
    banco = bancos.pop() if len(bancos) == 1 else ""
    if len(banco) > 24:
        banco = ""
    return {
        "pct": mx,
        "txt": _pct_publico(mx),
        "cadenas": [str(f["cadena"]) for f in filas],
        "banco": banco,
    }


def descripcion_hub_hoy(dia: str, n_hoy: int, cadenas_hoy: int, top: dict[str, Any] | None) -> str:
    """Meta con el dato de hoy (120-155): el mayor % y dónde. "" si no hay un % hoy."""
    if not top or n_hoy <= 0:
        return ""
    cadenas = top["cadenas"]
    lugar_top = _unir(cadenas) if len(cadenas) <= 3 else f"{cadenas[0]} y {len(cadenas) - 1} cadenas más"
    con = f" con {top['banco']}" if top["banco"] else ""
    promos = "1 promo bancaria" if n_hoy == 1 else f"{n_hoy} promos bancarias"
    lugar = "1 supermercado" if cadenas_hoy == 1 else f"{cadenas_hoy} supermercados"
    cap = dia[:1].upper() + dia[1:]
    opciones = (
        f"Hoy {dia}: hasta {top['txt']}% en {lugar_top}{con}. {promos} en {lugar} de CABA, por banco y por cadena.",
        f"Hoy {dia}: hasta {top['txt']}% en {lugar_top}{con}. {promos} en {lugar} de CABA, con banco y tope.",
        f"Hoy {dia}: hasta {top['txt']}% en {lugar_top}. {promos} en {lugar} de CABA, por banco y por cadena.",
        f"{cap}: hasta {top['txt']}% en {lugar_top}. {promos} hoy en {lugar} de CABA, con banco, tope y días.",
    )
    for texto in opciones:
        if 120 <= len(texto) <= 155 and '"' not in texto and "<" not in texto:
            return texto
    return ""


def _faq_hub_hoy(
    dia: str,
    por_cadena: list[dict[str, Any]],
    por_banco: list[dict[str, Any]],
    matriz: dict[str, Any],
) -> list[dict[str, str]]:
    """Preguntas que responde el resumen de hoy y la tabla de la semana. Solo datos cargados."""
    faq: list[dict[str, str]] = []
    if por_cadena:
        partes = [
            f"{f['cadena']} {f['top_txt']}%" if f["top_txt"] else f"{f['cadena']} solo cuotas"
            for f in por_cadena
        ]
        faq.append({
            "q": "¿Qué supermercado tiene el mayor descuento bancario hoy?",
            "a": (
                f"Hoy {dia}, según lo publicado por cada cadena, el mayor descuento en cada "
                f"supermercado de CABA es: {_unir(partes)}. Es el mejor caso con el banco o la "
                f"billetera que lo da, no un descuento para todos los medios de pago; el tope y "
                f"las condiciones están en el resumen de hoy."
            ),
        })
    bancos = [b for b in por_banco if b["top_txt"]]
    if bancos:
        partes = [f"{b['banco']} (hasta {b['top_txt']}% en {b['cadenas'][0]['cadena']})" for b in bancos[:8]]
        resto = len(bancos) - len(partes)
        extra = f" y {resto} más" if resto > 0 else ""
        faq.append({
            "q": "¿Qué bancos tienen descuento en supermercados hoy?",
            "a": (
                f"Hoy {dia} hay descuento en supermercados de CABA con {_unir(partes)}{extra}."
                + (" Otros bancos solo publican cuotas hoy." if len(bancos) < len(por_banco) else "")
                + " Cada promo tiene su tope y sus condiciones."
            ),
        })
    filas = [f for f in matriz.get("filas") or [] if f["mejor_txt"]]
    if filas:
        partes = []
        for f in filas:
            dias = f["mejores_dias"]
            cuando = _unir(dias) if len(dias) <= 3 else f"{len(dias)} días de la semana"
            partes.append(f"{f['cadena']}: {cuando} ({f['mejor_txt']}%)")
        faq.append({
            "q": "¿Qué día conviene ir a cada supermercado?",
            "a": (
                f"Esta semana, el día con el mayor descuento publicado en cada supermercado es: "
                f"{'; '.join(partes)}. Depende del banco o la billetera que tengas: la tabla de "
                f"la semana muestra el mayor porcentaje de cada día."
            ),
        })
    return faq


def pagina_seo(hoy: date | None = None) -> dict[str, Any]:
    """Vista de /promos-bancarias-supermercados. Solo campos presentes."""
    hoy = hoy or hoy_art()
    items = _items_publicos(hoy)
    wd = hoy.weekday()
    hoy_items = [it for it in items if wd in it["day_ids"]]
    por_dia = []
    for i, nombre in DIAS:
        cadenas = _agrupar_cadenas([it for it in items if i in it["day_ids"]])
        if not cadenas:
            continue
        por_dia.append({"dia": nombre, "hoy": i == wd, "cadenas": cadenas})
    hoy_cadenas = _agrupar_cadenas(hoy_items)
    cadenas_n = len({it["chain_id"] for it in items})
    cadenas_hoy = len(hoy_cadenas)
    actualizado = fecha_datos_promos(hoy)
    por_cadena_hoy = _resumen_por_cadena(hoy_items)
    por_banco_hoy = _resumen_por_banco(hoy_items)
    matriz = _matriz_semana(items, wd)
    top = _top_hub(por_cadena_hoy)
    faq = faq_promos_publicas(len(hoy_items), cadenas_hoy) + _faq_hub_hoy(
        NOMBRE_DIA[wd], por_cadena_hoy, por_banco_hoy, matriz
    )
    return {
        "title": SEO_TITLE,
        "description": descripcion_hub_hoy(
            NOMBRE_DIA[wd], len(hoy_items), cadenas_hoy, top
        ) or descripcion_hub(len(items), cadenas_n, len(hoy_items)),
        "por_cadena_hoy": por_cadena_hoy,
        "por_banco_hoy": por_banco_hoy,
        "matriz": matriz,
        "top_hoy": top,
        "canonical": SEO_URL,
        "path": SEO_PATH,
        "hoy_iso": hoy.isoformat(),
        "dia": NOMBRE_DIA[wd],
        "fecha": fecha_larga(hoy),
        "actualizado": fecha_larga(actualizado) if actualizado else "",
        "n": len(items),
        "n_hoy": len(hoy_items),
        "cadenas_n": cadenas_n,
        "cadenas": [
            {"nombre": c["nombre"], "href": c["href"]}
            for c in cadenas_indexables(hoy)
        ],
        "hoy_cadenas": hoy_cadenas,
        "por_dia": por_dia,
        "dias_nav": nav_dias(hoy),
        "faq": faq,
        "ld_faq": _ld({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": item["q"],
                    "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
                }
                for item in faq
            ],
        }),
        "ld_breadcrumb": _ld({
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "name": "Inicio",
                    "item": "https://baratoya.app/",
                },
                {
                    "@type": "ListItem",
                    "position": 2,
                    "name": "Promos bancarias supermercados",
                    "item": SEO_URL,
                },
            ],
        }),
    }


def _unir(partes: list[str]) -> str:
    if not partes:
        return ""
    if len(partes) == 1:
        return partes[0]
    if len(partes) == 2:
        return f"{partes[0]} y {partes[1]}"
    return ", ".join(partes[:-1]) + " y " + partes[-1]


def _n_promos(n: int) -> str:
    return "1 promo" if n == 1 else f"{n} promos"


def titulo_cadena(nombre: str) -> str:
    """≤60. Arranca con "promociones bancarias" (la búsqueda) y, si entra, supermercado."""
    opciones = (
        f"Promociones bancarias {nombre} supermercado hoy | BaratoYa",
        f"Promociones bancarias {nombre} hoy | BaratoYa",
        f"Promos bancarias {nombre} supermercado hoy | BaratoYa",
        f"Promos bancarias {nombre} hoy: bancos y días | BaratoYa",
        f"Promos bancarias {nombre} hoy | BaratoYa",
        f"Promos {nombre} hoy: bancos y días | BaratoYa",
        f"Promos {nombre} hoy | BaratoYa",
    )
    for texto in opciones:
        if len(texto) <= 60:
            return texto
    raise ValueError(f"titulo de {nombre} no entra en 60")


def h1_cadena(nombre: str) -> str:
    """La búsqueda es "promociones bancarias en {cadena} hoy"."""
    return f"Promociones bancarias en {nombre} hoy"


def descripcion_cadena(nombre: str, dia: str, hasta_pct: float | None = None) -> str:
    if hasta_pct and nombre == "Carrefour":
        hasta = _pct_txt(hasta_pct)
        for texto in (
            (
                f"Promociones bancarias del supermercado {nombre} hoy ({dia}) en CABA: "
                f"hasta {hasta} de descuento. Banco o tarjeta, días y tope. BaratoYa no vende ni entrega."
            ),
            (
                f"Promociones bancarias de {nombre} hoy ({dia}) en CABA: hasta {hasta}. "
                f"Bancos, días y tope. BaratoYa no vende ni entrega."
            ),
        ):
            # ≤155 como el resto de las metas: con "miércoles" la primera daba 157.
            if len(texto) <= 155:
                return texto
    opciones = (
        (
            f"Promociones bancarias del supermercado {nombre} hoy ({dia}) en CABA: "
            f"banco o tarjeta, días y tope si está publicado. BaratoYa no vende ni entrega."
        ),
        (
            f"Promociones bancarias del supermercado {nombre} hoy ({dia}) en CABA: "
            f"banco, días y tope si está publicado. BaratoYa no vende ni entrega."
        ),
        (
            f"Promociones bancarias de {nombre} hoy ({dia}) en CABA: banco o tarjeta, "
            f"días y tope si está publicado. BaratoYa no vende ni entrega."
        ),
        (
            f"Promociones bancarias de {nombre} hoy ({dia}) en CABA: bancos, días y tope "
            f"si está publicado. BaratoYa no vende ni entrega."
        ),
        (
            f"Promos de {nombre} hoy ({dia}) en CABA. Bancos, días y tope si está "
            f"publicado. BaratoYa no vende ni entrega."
        ),
    )
    for texto in opciones:
        if len(texto) <= 155:
            return texto
    raise ValueError(f"descripcion de {nombre} no entra en 155")


# Coto (65 imp, pos 8.8) y Carrefour (30 imp, pos 8.5) ya rankean con el título,
# el H1 y la meta de antes (GSC 19/10): no se tocan. El resto lleva
# "promociones bancarias <Cadena> hoy" seguido, que es como se busca.
_CADENAS_META_FIJA = frozenset({"cotodigital", "carrefour"})


def titulo_cadena_hoy(nombre: str) -> str:
    """≤60. "Promociones bancarias <Cadena> hoy" seguido. Sin %: el título no cambia por día."""
    opciones = (
        f"Promociones bancarias {nombre} hoy: bancos y topes | BaratoYa",
        f"Promociones bancarias {nombre} hoy | BaratoYa",
        f"Promos bancarias {nombre} hoy | BaratoYa",
    )
    for texto in opciones:
        if len(texto) <= 60:
            return texto
    raise ValueError(f"titulo de {nombre} no entra en 60")


def h1_cadena_hoy(nombre: str, dia: str) -> str:
    return f"Promociones bancarias {nombre} hoy, {dia}"


def descripcion_cadena_hoy(
    nombre: str,
    dia: str,
    n_hoy: int,
    top: dict[str, str] | None,
    semana_top: dict[str, Any] | None = None,
    hoy_idx: int | None = None,
) -> str:
    """≤155. Arranca con la búsqueda. El % solo si hoy hay uno publicado sin condiciones extra.

    Si en la semana hay un % mayor que el de hoy (sin condición para el que compra y con
    tope publicado), va también: es lo que decide la visita (GSC 26/10: Maxiconsumo
    0 clics / 98 imp @7,3 con "hasta 5%" en la meta y 30% el miércoles en la tabla).
    """
    cierre = "BaratoYa no vende ni entrega."
    base = f"Promociones bancarias {nombre} hoy ({dia}) en CABA"
    opciones: list[str] = []
    hoy_pct = None
    if n_hoy and top:
        try:
            hoy_pct = float(str(top["pct"]).rstrip("%").replace(",", "."))
        except ValueError:
            hoy_pct = None
    if semana_top and (hoy_pct is None or semana_top["pct"] > hoy_pct):
        tope = f" ({semana_top['tope']})" if semana_top.get("tope") else ""
        sem = f"En la semana, hasta {semana_top['pct_txt']} {semana_top['dias']} con {semana_top['banco']}{tope}"
        sem_corta = f"En la semana, hasta {semana_top['pct_txt']} {semana_top['dias']}{tope}"
        hoy_sem = f"hasta {semana_top['pct_txt']} con {semana_top['banco']}{tope}"
        if hoy_idx in semana_top.get("day_ids", []) and n_hoy:
            opciones += [
                f"{base}: {hoy_sem}. {_n_promos(n_hoy)} hoy, con días y tope. {cierre}",
                f"{base}: {hoy_sem}. {_n_promos(n_hoy)} hoy, con días y tope.",
                f"{base}: {hoy_sem}.",
            ]
        elif hoy_pct is not None:
            pct, bancos = top["pct"], top["bancos"]
            opciones += [
                f"{base}: hasta {pct} con {bancos}. {sem}. {cierre}",
                f"{base}: hasta {pct} con {bancos}. {sem}.",
                f"{base}: hasta {pct}. {sem}.",
                f"{base}: {pct} con {bancos}. {sem_corta}.",
            ]
        elif n_hoy:
            opciones += [
                f"{base}: {_n_promos(n_hoy)} hoy. {sem}. {cierre}",
                f"{base}: {_n_promos(n_hoy)} hoy. {sem}.",
                f"{base}: {_n_promos(n_hoy)} hoy. {sem_corta}.",
            ]
        else:
            opciones += [
                f"{base}: hoy no hay promos cargadas. {sem}.",
                f"{base}: hoy no hay promos cargadas. {sem_corta}.",
            ]
    if n_hoy and top:
        pct, bancos = top["pct"], top["bancos"]
        opciones += [
            f"{base}: hasta {pct} con {bancos}. {_n_promos(n_hoy)} del supermercado hoy, con días y tope. {cierre}",
            f"{base}: hasta {pct} con {bancos}. {_n_promos(n_hoy)} hoy, con días y tope. {cierre}",
            f"{base}: hasta {pct} con {bancos}. Bancos, días y tope del supermercado. {cierre}",
            f"{base}: hasta {pct}. {_n_promos(n_hoy)} del supermercado hoy, con bancos, días y tope. {cierre}",
            f"{base}: hasta {pct}. Bancos, días y tope del supermercado. {cierre}",
        ]
    if n_hoy:
        opciones += [
            f"{base}: {_n_promos(n_hoy)} del supermercado hoy, con banco o tarjeta, días y tope si está publicado. {cierre}",
            f"{base}: {_n_promos(n_hoy)} del supermercado hoy, con banco, días y tope. {cierre}",
        ]
    for texto in opciones:
        if len(texto) <= 155 and '"' not in texto and "<" not in texto:
            return texto
    return descripcion_cadena(nombre, dia)


def notas_honestidad() -> list[dict[str, str]]:
    """Las mismas respuestas del hub sobre tope, sucursal y conflictos."""
    por_q = {item["q"]: item["a"] for item in faq_promos_publicas()}
    claves = (
        "¿Qué es el tope?",
        "¿Cómo se calcula el descuento?",
        "¿Las promos se acumulan?",
    )
    return [{"q": q, "a": por_q[q]} for q in claves]


def cadenas_indexables(hoy: date | None = None) -> list[dict[str, str]]:
    """Cadenas con al menos una promo pública, en el orden del hub."""
    hoy = hoy or hoy_art()
    presentes = {it["chain_id"] for it in _items_publicos(hoy)}
    salida = []
    for chain_id, slug, nombre in _CADENAS_SEO:
        if chain_id not in presentes:
            continue
        href = f"{SEO_PATH}/{slug}"
        salida.append({
            "chain_id": chain_id,
            "slug": slug,
            "nombre": nombre,
            "href": href,
            "url": "https://baratoya.app" + href,
        })
    return salida


def _respuesta_promociones_cadena(nombre: str, dia_hoy: str, fecha: str, n_hoy: int) -> str:
    """Cuenta las promos de hoy. No inventa un banco ni un porcentaje."""
    cuando = f"Hoy es {dia_hoy} {fecha}."
    if n_hoy == 1:
        cuantas = "hay 1 promoción bancaria"
    elif n_hoy:
        cuantas = f"hay {n_hoy} promociones bancarias"
    else:
        return (
            f"{cuando} Esta semana, según lo publicado por {nombre}, "
            f"no hay promociones bancarias para ese día."
        )
    return (
        f"{cuando} Esta semana, según lo publicado por {nombre}, "
        f"{cuantas} para ese día. Están en la sección Hoy: banco o tarjeta, "
        f"porcentaje o cuotas, y el tope si está publicado."
    )


def _faq_cadena(
    nombre: str,
    dia_hoy: str,
    fecha: str,
    items: list[dict[str, Any]],
    conteo_dias: Counter[int],
    n_hoy: int,
) -> list[dict[str, str]]:
    """Preguntas que se responden con lo publicado por la cadena. Sin cifras inventadas."""
    faq: list[dict[str, str]] = [{
        "q": f"¿Cuáles son las promociones bancarias en {nombre} hoy?",
        "a": _respuesta_promociones_cadena(nombre, dia_hoy, fecha, n_hoy),
    }]
    if n_hoy:
        faq.append({
            "q": f"¿Hay promos bancarias de {nombre} hoy?",
            "a": (
                f"Hoy es {dia_hoy} {fecha}. Esta semana, según lo publicado por {nombre}, "
                f"hay {_n_promos(n_hoy)} para ese día."
            ),
        })
    else:
        faq.append({
            "q": f"¿Hay promos bancarias de {nombre} hoy?",
            "a": (
                f"Hoy es {dia_hoy} {fecha}. Esta semana, según lo publicado por {nombre}, "
                f"no hay promos para ese día."
            ),
        })

    if conteo_dias:
        maximo = max(conteo_dias.values())
        top = [NOMBRE_DIA[i] for i, _nombre in DIAS if conteo_dias.get(i) == maximo]
        vacios = [NOMBRE_DIA[i] for i, _nombre in DIAS if not conteo_dias.get(i)]
        if len(top) == 1:
            frase = (
                f"Esta semana, según lo publicado por {nombre}, el {top[0]} tiene "
                f"{_n_promos(maximo)}. Es el día con más promos."
            )
        else:
            frase = (
                f"Esta semana, según lo publicado por {nombre}, "
                f"{_unir([f'el {d}' for d in top])} tienen {_n_promos(maximo)} cada uno. "
                f"Empatan como los días con más promos."
            )
        if vacios:
            frase += f" No hay promos cargadas para {_unir([f'el {d}' for d in vacios])}."
        faq.append({
            "q": f"¿Qué día tiene más promos en {nombre}?",
            "a": frase,
        })

    bancos = sorted({it["banco"] for it in items if it.get("banco")}, key=str.casefold)
    if bancos:
        faq.append({
            "q": f"¿Qué bancos o billeteras figuran en {nombre}?",
            "a": (
                f"Esta semana, según lo publicado por {nombre}, las promos figuran "
                f"a nombre de {_unir(bancos)}."
            ),
        })

    canales = Counter(it["canal"] for it in items if it.get("canal"))
    if canales:
        orden = ("online", "online y sucursal", "sucursal")
        partes = []
        for canal in orden:
            n = canales.pop(canal, 0)
            if n:
                verbo = "figura" if n == 1 else "figuran"
                partes.append(f"{_n_promos(n)} {verbo} como {canal}")
        for canal, n in sorted(canales.items()):
            verbo = "figura" if n == 1 else "figuran"
            partes.append(f"{_n_promos(n)} {verbo} como {canal}")
        texto = f"Esta semana, según lo publicado por {nombre}, {_unir(partes)}."
        if any(it.get("canal") == "sucursal" for it in items):
            texto += " Las de sucursal se listan y no se restan del precio online."
        faq.append({
            "q": f"¿Las promos de {nombre} son online o de sucursal?",
            "a": texto,
        })
    return faq


def _faq_cadena_semana(nombre: str, semana: dict[str, Any]) -> list[dict[str, str]]:
    """Preguntas propias de la cadena, con el resumen de la semana. Solo si hay dato."""
    faq: list[dict[str, str]] = []
    if not semana:
        return faq
    mayor = " ".join(x for x in (semana.get("mayor_general"), semana.get("mayor_condicion")) if x)
    if mayor:
        faq.append({
            "q": f"¿Cuál es el mayor descuento en {nombre} esta semana?",
            "a": f"Según lo publicado por {nombre}: {mayor[0].lower()}{mayor[1:]} Revisá el tope y el canal antes de pagar.",
        })
    if semana.get("cuotas_n"):
        n = int(semana["cuotas_n"])
        texto = (
            f"Sí. Esta semana, según lo publicado por {nombre}, hay "
            f"{_n_promos(n)} en cuotas sin interés, con {_unir(semana['cuotas_bancos'])}."
        )
        cond = int(semana.get("cuotas_cond_n") or 0)
        if cond:
            texto += (
                f" {'1 tiene' if cond == 1 else f'{cond} tienen'} condiciones publicadas"
                f" (por ejemplo: «{semana['cuotas_cond_ej']}»)."
            )
        texto += " Las cuotas no se restan del precio: no son un porcentaje."
        faq.append({"q": f"¿{nombre} tiene cuotas sin interés?", "a": texto})
    if semana.get("sin_tope"):
        promos = [
            _promo_txt(it, pct=bool(it.get("percent"))).replace(", sin tope", "").replace(" (sin tope)", "")
            for it in semana["sin_tope"]
        ]
        faq.append({
            "q": f"¿Qué promos de {nombre} no tienen tope?",
            "a": (
                f"Esta semana, según lo publicado por {nombre}, figuran sin tope: {_unir(promos)}. "
                "Si una promo no publica el tope, no la contamos como sin tope."
            ),
        })
    return faq


def _ld_faq(faq: list[dict[str, str]]) -> str:
    return _ld({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["q"],
                "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
            }
            for item in faq
        ],
    })


_COLUMNAS_CADENA = (
    ("banco", "Banco"),
    ("oferta", "Promo"),
    ("tope", "Tope"),
    ("minimo", "Mínimo"),
    ("canal", "Canal"),
    ("vigencia", "Vigencia"),
    ("nota", "Nota"),
)


def _pct_txt(p: float) -> str:
    return f"{int(p)}%" if float(p).is_integer() else f"{p:g}%".replace(".", ",")


def _es_nombre_banco(banco: str) -> bool:
    """Deja afuera textos de promo que la cadena publica en el lugar del banco."""
    b = banco.strip()
    return bool(b) and len(b) <= 40 and not b[0].isdigit() and not _fold(b).startswith("si ")


def _con_condicion(it: dict[str, Any]) -> bool:
    """True si la nota publicada pone una condición (solo socios, excluye, conflicto...).

    Una nota que solo aclara el tope ("Sin tope de reintegro") no es una condición.
    """
    nota = _fold(str(it.get("nota") or ""))
    if not nota:
        return False
    resto = re.sub(r"sin tope(?: de reintegro| informado)?", "", nota)
    return bool(resto.strip(" ;.,"))


def _condicion_txt(it: dict[str, Any]) -> str:
    """La primera parte de la nota, tal como está publicada."""
    return str(it.get("nota") or "").split(";", 1)[0].strip().rstrip(".")


def resumen_cadena(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Resumen calculado solo con lo publicado: mayor % por día y días por banco."""
    items = [it for it in items if _es_nombre_banco(it.get("banco") or "")]
    mejor: list[dict[str, str]] = []
    for i, nombre_dia in DIAS:
        del_dia = [it for it in items if i in it.get("day_ids", []) and it.get("percent")]
        if not del_dia:
            continue
        top = max(it["percent"] for it in del_dia)
        bancos = sorted({it["banco"] for it in del_dia if it["percent"] == top}, key=str.casefold)
        fila = {"dia": nombre_dia, "pct": _pct_txt(top), "bancos": ", ".join(bancos)}
        topes = {it.get("tope", "") for it in del_dia if it["percent"] == top}
        if len(topes) == 1 and next(iter(topes)):
            fila["tope"] = next(iter(topes))
        if all(_con_condicion(it) for it in del_dia if it["percent"] == top):
            # El mayor % del día tiene condiciones publicadas: se dice, y se muestra
            # el mayor sin condiciones extra si lo hay.
            fila["condicion"] = "con condiciones publicadas"
            generales = [it for it in del_dia if not _con_condicion(it)]
            if generales:
                g_top = max(it["percent"] for it in generales)
                fila["general_pct"] = _pct_txt(g_top)
                fila["general_bancos"] = ", ".join(
                    sorted({it["banco"] for it in generales if it["percent"] == g_top}, key=str.casefold)
                )
        mejor.append(fila)
    por_banco: dict[str, set[int]] = {}
    for it in items:
        por_banco.setdefault(it["banco"], set()).update(it.get("day_ids", []))
    bancos = [
        {"banco": b, "dias": ", ".join(NOMBRE_DIA[d] for d in sorted(ds)) if len(ds) < 7 else "todos los días"}
        for b, ds in sorted(por_banco.items(), key=lambda kv: kv[0].casefold())
        if ds
    ]
    online = sorted({it["banco"] for it in items if "online" in (it.get("canal") or "")}, key=str.casefold)
    return {"mejor_por_dia": mejor, "por_banco": bancos, "bancos_online": online}


def _dias_item_txt(it: dict[str, Any]) -> str:
    ids = sorted(set(it.get("day_ids") or []))
    if len(ids) == 7:
        return "todos los días"
    return _unir([NOMBRE_DIA[d] for d in ids])


def _promo_txt(it: dict[str, Any], *, pct: bool = False) -> str:
    """"Banco (días, tope)" con lo publicado. pct=True antepone el porcentaje."""
    partes = [_dias_item_txt(it)] if it.get("day_ids") else []
    if it.get("tope"):
        partes.append(str(it["tope"]))
    cabeza = f"{_pct_txt(it['percent'])} con {it['banco']}" if pct else str(it["banco"])
    return f"{cabeza} ({', '.join(partes)})" if partes else cabeza


def _mejores(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Las promos con el mayor %, sin repetir banco + días + tope."""
    con = [it for it in items if it.get("percent")]
    if not con:
        return []
    top = max(it["percent"] for it in con)
    vistos: set[tuple[str, str, str]] = set()
    salida = []
    for it in sorted(con, key=lambda x: (min(x.get("day_ids") or [7]), (x.get("banco") or "").casefold())):
        if it["percent"] != top:
            continue
        clave = (it["banco"], _dias_item_txt(it), str(it.get("tope") or ""))
        if clave in vistos:
            continue
        vistos.add(clave)
        salida.append(it)
    return salida


# Notas que solo avisan que falta un dato en lo publicado (no restringen quién ni qué
# compra). Sirven para decir el mayor % de la semana en la meta, con el tope a la vista.
_NOTA_SOLO_DATO = re.compile(
    r"^(vigencia no informada(?: en el legal)?|sin tope(?: o tope no informado| informado)?"
    r"|canal no (?:indicado|informado))$"
)


def _restringe_comprador(it: dict[str, Any]) -> bool:
    """True si la nota pone una condición al que compra (socios, rubros, sucursales...)."""
    if not _con_condicion(it):
        return False
    partes = [_fold(p).strip(" .,") for p in str(it.get("nota") or "").split(";")]
    return not all(_NOTA_SOLO_DATO.match(p) for p in partes if p)


def _banco_corto(raw: str) -> str:
    """El nombre como lo publica la cadena, sin el paréntesis; si es largo, el canónico."""
    corto = re.sub(r"\s*\(.*?\)\s*", " ", raw).strip()
    if corto and len(corto) <= 24:
        return corto
    return banco_canonico(raw) or (raw if len(raw) <= 24 else "")


def mejor_semana_cadena(items: list[dict[str, Any]], hoy: date) -> dict[str, Any] | None:
    """El mayor % de la semana que se puede decir en una línea: sin condición para el que
    compra y con tope en pesos publicado (o "sin tope"). None si no hay."""
    aptos = [
        it for it in items
        if it.get("percent") and it.get("day_ids") and _es_nombre_banco(it.get("banco") or "")
        and not _restringe_comprador(it)
        and (isinstance(it.get("tope_num"), (int, float)) or it.get("tope") == "sin tope")
    ]
    if not aptos:
        return None
    pct = max(float(it["percent"]) for it in aptos)
    ties = sorted(
        (it for it in aptos if float(it["percent"]) == pct),
        key=lambda it: (min(it["day_ids"]), -(it.get("tope_num") or 0), (it.get("banco") or "").casefold()),
    )
    it = ties[0]
    banco = _banco_corto(str(it.get("banco") or ""))
    if not banco:
        return None
    ids = sorted(set(it["day_ids"]))
    if len(ids) == 7:
        dias = "todos los días"
    else:
        dias = "el " + _unir([NOMBRE_DIA[d] for d in ids])
    tope = "sin tope" if it.get("tope") == "sin tope" else str(it.get("tope") or "")
    return {
        "pct": pct,
        "pct_txt": _pct_txt(pct),
        "banco": banco,
        "dias": dias,
        "day_ids": ids,
        "tope": tope,
        "canal": str(it.get("canal") or ""),
        "nota": _condicion_txt(it) if _con_condicion(it) else "",
    }


def resumen_semana_cadena(nombre: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Resumen de la semana de una cadena. Solo cuentas sobre las tarjetas publicadas."""
    items = [it for it in items if _es_nombre_banco(it.get("banco") or "")]
    if not items:
        return {}
    con_pct = [it for it in items if it.get("percent")]
    cuotas = [it for it in items if not it.get("percent")]
    bancos = sorted({it["banco"] for it in items}, key=str.casefold)
    lineas: list[str] = []
    partes = []
    if con_pct:
        partes.append(f"{len(con_pct)} con porcentaje de descuento")
    if cuotas:
        partes.append(f"{len(cuotas)} en cuotas sin interés")
    lineas.append(
        f"Esta semana, según lo publicado por {nombre}, hay {_n_promos(len(items))} de "
        f"{len(bancos)} {'banco o billetera' if len(bancos) == 1 else 'bancos y billeteras'}"
        + (f": {_unir(partes)}." if partes else ".")
    )
    generales = _mejores([it for it in con_pct if not _con_condicion(it)])
    condicionadas = _mejores([it for it in con_pct if _con_condicion(it)])
    mayor_general = ""
    mayor_condicion = ""
    if generales:
        mayor_general = (
            "El mayor descuento sin condiciones extra en la nota es "
            + _unir([_promo_txt(it, pct=True) for it in generales[:3]])
            + "."
        )
        lineas.append(mayor_general)
    if condicionadas and (not generales or condicionadas[0]["percent"] > generales[0]["percent"]):
        it = condicionadas[0]
        mayor_condicion = (
            f"El porcentaje más alto publicado es {_promo_txt(it, pct=True)}, "
            f"con una condición: «{_condicion_txt(it)}»."
        )
        lineas.append(mayor_condicion)
    con_tope = [it for it in items if isinstance(it.get("tope_num"), (int, float))]
    if con_tope:
        mx = max(it["tope_num"] for it in con_tope)
        it = sorted(
            (x for x in con_tope if x["tope_num"] == mx),
            key=lambda x: (_con_condicion(x), (x.get("banco") or "").casefold()),
        )[0]
        oferta = _pct_txt(it["percent"]) if it.get("percent") else str(it.get("oferta") or "")
        linea = f"El tope más alto publicado es de {str(it['tope']).removeprefix('tope ')}: {it['banco']}, {oferta}, {_dias_item_txt(it)}"
        linea += " (ver la nota en la tabla)." if _con_condicion(it) else "."
        lineas.append(linea)
    sin_tope = [it for it in items if it.get("tope") == "sin tope"]
    if sin_tope:
        lineas.append(
            "Figuran sin tope: "
            + _unir([_promo_txt(it, pct=bool(it.get("percent"))).replace(", sin tope", "").replace(" (sin tope)", "") for it in sin_tope[:4]])
            + "."
        )
    dias_con = sorted({d for it in items for d in it.get("day_ids", [])})
    vacios = [NOMBRE_DIA[i] for i, _n in DIAS if i not in dias_con]
    if vacios:
        lineas.append(f"No hay promos cargadas para {_unir(['el ' + d for d in vacios])}.")
    else:
        lineas.append("Hay promos cargadas para los 7 días.")
    cuotas_cond = [it for it in cuotas if _con_condicion(it)]
    return {
        "lineas": lineas,
        "n": len(items),
        "bancos_n": len(bancos),
        "pct_n": len(con_pct),
        "cuotas_n": len(cuotas),
        "cuotas_bancos": sorted({it["banco"] for it in cuotas}, key=str.casefold),
        "cuotas_cond_n": len(cuotas_cond),
        "cuotas_cond_ej": _condicion_txt(cuotas_cond[0]) if cuotas_cond else "",
        "mayor_general": mayor_general,
        "mayor_condicion": mayor_condicion,
        "sin_tope": sin_tope,
    }


def hoy_otras_cadenas(chain_id: str, hoy: date) -> list[dict[str, Any]]:
    """Hoy en cada cadena con página: cuántas promos y el mayor % publicado. La propia va marcada."""
    por_cadena = promos_de_hoy_por_cadena(hoy)
    filas = []
    for c in cadenas_indexables(hoy):
        info = por_cadena.get(c["chain_id"])
        filas.append({
            "nombre": c["nombre"],
            "href": c["href"],
            "propia": c["chain_id"] == chain_id,
            "n": info["n"] if info else 0,
            "top_pct": f"{info['top_txt']}%" if info and info.get("top_txt") else "",
        })
    return filas


# Mayoristas con página propia. Quien busca "promociones bancarias maxiconsumo" compra
# por cantidad: la comparación útil es contra el otro mayorista, no contra Coto o Día.
_MAYORISTAS = ("maxiconsumo", "makro")


def mayoristas_semana(chain_id: str, hoy: date) -> list[dict[str, Any]]:
    """Maxiconsumo y Makro esta semana, con las mismas tarjetas que sus páginas.

    [] si la cadena no es mayorista o si no hay al menos dos mayoristas con promos.
    """
    if chain_id not in _MAYORISTAS:
        return []
    indice = {c["chain_id"]: c for c in cadenas_indexables(hoy)}
    todos = _items_publicos(hoy)
    wd = hoy.weekday()
    filas: list[dict[str, Any]] = []
    for cid in _MAYORISTAS:
        if cid not in indice:
            continue
        items = [it for it in todos if it.get("chain_id") == cid and _es_nombre_banco(it.get("banco") or "")]
        if not items:
            continue
        con_pct = [it for it in items if it.get("percent")]
        canales = Counter(str(it.get("canal") or "no indicado") for it in items)
        hoy_items = [it for it in items if wd in it.get("day_ids", [])]
        top_hoy, _ = _top_descuento(hoy_items)
        filas.append({
            "chain_id": cid,
            "nombre": indice[cid]["nombre"],
            "href": indice[cid]["href"],
            "propia": cid == chain_id,
            "n": len(items),
            "bancos_n": len({it["banco"] for it in items}),
            "pct_n": len(con_pct),
            "cuotas_n": len(items) - len(con_pct),
            "n_hoy": len(hoy_items),
            "top_hoy_txt": _pct_txt(top_hoy) if top_hoy is not None else "",
            "mejor": mejor_semana_cadena(items, hoy),
            "mayor": (_mejores(con_pct) or [None])[0],
            "canales": [{"canal": k, "n": v} for k, v in sorted(canales.items(), key=lambda kv: (-kv[1], kv[0]))],
        })
    return filas if len(filas) >= 2 else []


def _linea_mayorista(f: dict[str, Any]) -> str:
    partes = [f"{_n_promos(f['n'])} de {f['bancos_n']} {'banco o billetera' if f['bancos_n'] == 1 else 'bancos y billeteras'}"]
    m, mayor = f.get("mejor"), f.get("mayor")
    if m:
        tope = f", {m['tope']}" if m.get("tope") else ""
        nota = f" (nota: «{m['nota']}»)" if m.get("nota") else ""
        partes.append(f"mayor % con tope publicado: {m['pct_txt']} {m['dias']} con {m['banco']}{tope}{nota}")
    if mayor and (not m or float(mayor["percent"]) > m["pct"]):
        txt = f"mayor % publicado: {_promo_txt(mayor, pct=True)}"
        if _con_condicion(mayor):
            txt += f", nota: «{_condicion_txt(mayor)}»"
        partes.append(txt)
    canales = _unir([f"{c['n']} de {c['canal']}" for c in f["canales"]])
    partes.append(f"canal: {canales}")
    return "; ".join(partes)


def _faq_mayoristas(nombre: str, filas: list[dict[str, Any]], items: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Dos preguntas de quien compra en mayorista, con las tarjetas de la semana."""
    if not filas:
        return []
    faq: list[dict[str, str]] = []
    orden = sorted(filas, key=lambda f: (-f["n"], f["nombre"]))
    if orden[0]["n"] == orden[-1]["n"]:
        texto = f"Esta semana empatan en cantidad: {_unir([f['nombre'] for f in filas])} publican {_n_promos(orden[0]['n'])} cada uno."
    else:
        texto = (
            f"Esta semana {orden[0]['nombre']} publica {_n_promos(orden[0]['n'])} y "
            + _unir([f"{f['nombre']} {_n_promos(f['n'])}" for f in orden[1:]])
            + "."
        )
    for f in filas:
        if f.get("mayor"):
            texto += f" En {f['nombre']}, el mayor porcentaje es {_promo_txt(f['mayor'], pct=True)}"
            texto += f". Nota publicada: «{_condicion_txt(f['mayor'])}»." if _con_condicion(f["mayor"]) else "."
    faq.append({
        "q": "¿Qué mayorista tiene más promociones bancarias esta semana: Maxiconsumo o Makro?",
        "a": texto + " Revisá el tope, el canal y la nota de cada promo antes de pagar.",
    })
    con_pct = [it for it in items if it.get("percent") and _es_nombre_banco(it.get("banco") or "")]
    mejores = _mejores(con_pct)
    if mejores:
        top = mejores[0]
        texto = (
            f"Según lo publicado por {nombre} esta semana, el mayor porcentaje es "
            f"{_promo_txt(top, pct=True)}."
        )
        if _con_condicion(top):
            texto += f" Nota publicada: «{_condicion_txt(top)}»."
        resto = [it for it in con_pct if float(it["percent"]) < float(top["percent"])]
        if resto:
            sig = _mejores(resto)[0]
            texto += f" Le sigue {_promo_txt(sig, pct=True)}."
        texto += " El detalle por día está en la tabla de esta página."
        faq.append({"q": f"¿Qué día conviene comprar en {nombre}?", "a": texto})
    return faq


def pagina_seo_cadena(slug: str, hoy: date | None = None) -> dict[str, Any] | None:
    """Vista de /promos-bancarias-supermercados/<slug>. None si no hay datos."""
    chain_id = _ID_POR_SLUG.get((slug or "").strip())
    if not chain_id:
        return None
    hoy = hoy or hoy_art()
    items = [it for it in _items_publicos(hoy) if it.get("chain_id") == chain_id]
    if not items:
        return None
    nombre = _NOMBRE_SEO[chain_id]
    nombre_archivo = str(items[0].get("cadena") or nombre)
    wd = hoy.weekday()
    dia = NOMBRE_DIA[wd]
    items.sort(key=lambda it: ((it.get("banco") or "").casefold(), it.get("oferta") or ""))
    hoy_promos = [it for it in items if wd in it.get("day_ids", [])]
    filas: list[dict[str, str]] = []
    conteo: Counter[int] = Counter()
    for i, nombre_dia in DIAS:
        for it in items:
            if i not in it.get("day_ids", []):
                continue
            fila = {"dia": nombre_dia, "banco": it["banco"], "oferta": it["oferta"]}
            for key in ("tope", "minimo", "canal", "vigencia", "nota"):
                valor = it.get(key)
                if valor:
                    fila[key] = valor
            filas.append(fila)
            conteo[i] += 1
    columnas = [
        {"key": key, "label": label}
        for key, label in _COLUMNAS_CADENA
        if key in {"banco", "oferta"} or any(fila.get(key) for fila in filas)
    ]
    fuentes: list[str] = []
    for it in items:
        fuente = it.get("fuente")
        if fuente and fuente not in fuentes:
            fuentes.append(fuente)
    semana = resumen_semana_cadena(nombre, items)
    faq = _faq_cadena(nombre, dia, fecha_larga(hoy), items, conteo, len(hoy_promos))
    faq += _faq_cadena_semana(nombre, semana)
    resumen = resumen_cadena(items)
    top_hoy = next((f for f in resumen["mejor_por_dia"] if f["dia"] == dia), None)
    if top_hoy and top_hoy.get("condicion"):
        # El % del día tiene condiciones: en la meta va el mayor sin condiciones, si lo hay.
        top_hoy = (
            {"pct": top_hoy["general_pct"], "bancos": top_hoy["general_bancos"]}
            if top_hoy.get("general_pct") else None
        )
    if top_hoy and len(top_hoy["bancos"].split(", ")) > 2:
        top_hoy = {"pct": top_hoy["pct"], "bancos": "varios bancos"}
    hoy_pct = sorted(
        (it for it in hoy_promos if it.get("percent")),
        key=lambda it: (-float(it["percent"]), (it.get("banco") or "").casefold()),
    )
    hoy_cuotas = [it for it in hoy_promos if not it.get("percent")]
    fija = chain_id in _CADENAS_META_FIJA
    semana_top = mejor_semana_cadena(items, hoy)
    mayoristas = mayoristas_semana(chain_id, hoy)
    if mayoristas:
        faq += [q for q in _faq_mayoristas(nombre, mayoristas, items) if q["q"] not in {x["q"] for x in faq}]
    dia_slug = next(d["slug"] for d in _DIAS_SEO if d["idx"] == wd)
    href = f"{SEO_PATH}/{_SLUG_POR_ID[chain_id]}"
    canonical = "https://baratoya.app" + href
    otras = [c for c in cadenas_indexables(hoy) if c["chain_id"] != chain_id]
    actualizado = fecha_datos_promos(hoy)
    return {
        "title": titulo_cadena(nombre) if fija else titulo_cadena_hoy(nombre),
        "description": descripcion_cadena(
            nombre, dia, max((it["percent"] for it in hoy_promos if it.get("percent")), default=None)
        ) if fija else descripcion_cadena_hoy(nombre, dia, len(hoy_promos), top_hoy, semana_top, wd),
        "canonical": canonical,
        "h1": h1_cadena(nombre) if fija else h1_cadena_hoy(nombre, dia),
        "path": href,
        "slug": _SLUG_POR_ID[chain_id],
        "nombre": nombre,
        "nombre_archivo": nombre_archivo,
        "hoy_iso": hoy.isoformat(),
        "dia": dia,
        "fecha": fecha_larga(hoy),
        "actualizado": fecha_larga(actualizado) if actualizado else "",
        "n": len(items),
        "n_hoy": len(hoy_promos),
        "fuentes": fuentes,
        "hoy_promos": hoy_promos,
        "hoy_pct": hoy_pct,
        "hoy_cuotas": hoy_cuotas,
        "semana": semana,
        "hoy_cadenas": hoy_otras_cadenas(chain_id, hoy),
        "mayoristas": [dict(f, linea=_linea_mayorista(f)) for f in mayoristas],
        "dia_href": f"{DESCUENTOS_PATH}/{dia_slug}",
        "filas": filas,
        "columnas": columnas,
        "faq": faq,
        "resumen": resumen,
        "notas": notas_honestidad(),
        "otras": otras,
        "dias_nav": nav_dias(hoy),
        "hub_href": SEO_PATH,
        "ld_faq": _ld_faq(faq),
        "ld_breadcrumb": _ld({
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "name": "Inicio",
                    "item": "https://baratoya.app/",
                },
                {
                    "@type": "ListItem",
                    "position": 2,
                    "name": "Promos bancarias supermercados",
                    "item": SEO_URL,
                },
                {
                    "@type": "ListItem",
                    "position": 3,
                    "name": nombre,
                    "item": canonical,
                },
            ],
        }),
    }


# Páginas por día de la semana. El slug "dia" ya es la cadena Día, así que
# estas URLs viven en /descuentos-supermercados y no bajo el hub de cadenas.
DESCUENTOS_PATH = "/descuentos-supermercados"
DESCUENTOS_URL = "https://baratoya.app" + DESCUENTOS_PATH
DESCUENTOS_TITLE = "Descuentos en supermercados por día y por banco | BaratoYa"
DESCUENTOS_H1 = "Descuentos en supermercados por día en CABA"
_DIAS_SEO = (
    {"idx": 0, "slug": "lunes", "nombre": "lunes", "plural": "lunes"},
    {"idx": 1, "slug": "martes", "nombre": "martes", "plural": "martes"},
    {"idx": 2, "slug": "miercoles", "nombre": "miércoles", "plural": "miércoles"},
    {"idx": 3, "slug": "jueves", "nombre": "jueves", "plural": "jueves"},
    {"idx": 4, "slug": "viernes", "nombre": "viernes", "plural": "viernes"},
    {"idx": 5, "slug": "sabado", "nombre": "sábado", "plural": "sábados"},
    {"idx": 6, "slug": "domingo", "nombre": "domingo", "plural": "domingos"},
)
_DIA_POR_SLUG = {d["slug"]: d for d in _DIAS_SEO}


def _meta_120(opciones: tuple[str, ...], que: str) -> str:
    for texto in opciones:
        if 120 <= len(texto) <= 155 and '"' not in texto and "<" not in texto:
            return texto
    largos = ", ".join(str(len(t)) for t in opciones)
    raise ValueError(f"{que} no entra en 120-155 ({largos})")


def _pct_publico(n: float) -> str:
    if float(n) == int(n):
        return str(int(n))
    return str(n).replace(".", ",")


def _cadenas_txt(n: int) -> str:
    return "1 cadena" if n == 1 else f"{n} cadenas"


def nav_dias(hoy: date | None = None) -> list[dict[str, Any]]:
    """Los 7 días, con el de hoy marcado en America/Argentina/Buenos_Aires."""
    hoy = hoy or hoy_art()
    wd = hoy.weekday()
    salida = []
    for spec in _DIAS_SEO:
        href = f"{DESCUENTOS_PATH}/{spec['slug']}"
        salida.append({
            "idx": spec["idx"],
            "slug": spec["slug"],
            "nombre": spec["nombre"],
            "plural": spec["plural"],
            "href": href,
            "url": "https://baratoya.app" + href,
            "hoy": spec["idx"] == wd,
        })
    return salida


def urls_sitemap(hoy: date | None = None) -> list[tuple[str, str]]:
    """Promos y descuentos, con lastmod del dato o del día. No una fecha fija."""
    hoy = hoy or hoy_art()
    last = lastmod_promos(hoy)
    urls = [(SEO_URL, last)]
    urls.extend((c["url"], last) for c in cadenas_indexables(hoy))
    urls.append((DESCUENTOS_URL, last))
    urls.extend((d["url"], last) for d in nav_dias(hoy))
    return urls


def titulo_dia(plural: str, *, es_hoy: bool = False) -> str:
    """El día va en el título. Si esa página es la de hoy, también entra "hoy"."""
    if es_hoy:
        texto = f"Descuentos en supermercados hoy, los {plural} | BaratoYa"
    else:
        texto = f"Descuentos en supermercados los {plural} | BaratoYa"
    if len(texto) > 60:
        raise ValueError(f"titulo de {plural} no entra en 60 ({len(texto)})")
    return texto


def h1_dia(plural: str, *, es_hoy: bool = False) -> str:
    if es_hoy:
        return f"Descuentos en supermercados hoy, los {plural} en CABA"
    return f"Descuentos en supermercados los {plural} en CABA"


def intro_dia(resumen: dict[str, Any], fecha: str, dia_hoy: str, es_hoy: bool) -> str:
    """Abre la página por el día, con el conteo publicado. Sin un % inventado."""
    plural = str(resumen["plural"])
    nombre = str(resumen["nombre"])
    if es_hoy:
        cuando = f"Hoy es {nombre} {fecha}, así que esta es la página de los descuentos de hoy."
    else:
        cuando = f"Hoy es {dia_hoy} {fecha}. Acá están los descuentos del {nombre}."
    return (
        f"Descuentos en supermercados los {plural} en CABA: "
        f"{_n_promos(int(resumen['n']))} en {_cadenas_txt(int(resumen['cadenas_n']))}, "
        f"de todas las cadenas juntas. {cuando}"
    )


def descripcion_dia(
    plural: str,
    n: int,
    cadenas_n: int,
    top_pct: float | None,
    top_cadena: str = "",
    top_banco: str = "",
) -> str:
    if n <= 0:
        return _meta_120((
            f"Los {plural} no hay promos bancarias cargadas para los supermercados de CABA. "
            f"Si la cadena no publica ese dato, no lo completamos. BaratoYa no vende.",
            f"No hay descuentos cargados los {plural} en supermercados de CABA. "
            f"Mostramos solo lo publicado por cada cadena. BaratoYa no vende ni entrega.",
        ), f"descripcion de {plural}")
    promo = "1 promo bancaria" if n == 1 else f"{n} promos bancarias"
    lugar = "1 supermercado" if cadenas_n == 1 else f"{cadenas_n} supermercados"
    if top_pct is None:
        return _meta_120((
            f"Los {plural} hay {promo} en {lugar} de CABA. Ese día las cadenas no publican "
            f"un porcentaje. BaratoYa no vende ni entrega.",
            f"Descuentos los {plural} en supermercados de CABA: {promo} en {lugar}. "
            f"Sin un porcentaje publicado ese día. BaratoYa no vende ni entrega.",
        ), f"descripcion de {plural}")
    pct = _pct_publico(top_pct)
    concretas: tuple[str, ...] = ()
    if top_cadena:
        cap = plural[:1].upper() + plural[1:]
        con = f" con {top_banco}" if top_banco else ""
        concretas = (
            f"{cap}: hasta {pct}% en {top_cadena}{con}. {promo[:1].upper() + promo[1:]} en {lugar} "
            f"de CABA, por banco y por cadena.",
            f"{cap}: hasta {pct}% en {top_cadena}. {promo[:1].upper() + promo[1:]} en {lugar} "
            f"de CABA, por banco y por cadena.",
            f"Descuentos los {plural}: hasta {pct}% en {top_cadena}{con}. Hay {promo} en {lugar} "
            f"de CABA, con tope y banco de cada una.",
        )
    return _meta_120(concretas + (
        f"Los {plural} hay {promo} en {lugar} de CABA. El mayor porcentaje publicado "
        f"es {pct}%. BaratoYa no vende ni entrega.",
        f"Descuentos los {plural} en supermercados de CABA: {promo} en {lugar}. "
        f"El mayor porcentaje publicado es {pct}%. BaratoYa no vende ni entrega.",
    ), f"descripcion de {plural}")


def descripcion_dias(n: int, cadenas_n: int, dia_nombre: str) -> str:
    if n == 1:
        promos = "1 promo vigente"
    else:
        promos = f"{n} promos vigentes"
    if cadenas_n == 1:
        lugar = "1 cadena"
    else:
        lugar = f"{cadenas_n} cadenas"
    return _meta_120((
        f"Descuentos de supermercados en CABA, de lunes a domingo: {promos} en {lugar}. "
        f"Hoy es {dia_nombre}. BaratoYa no vende ni entrega.",
        f"Hay {promos} en {lugar} de supermercados de CABA, separadas por día. "
        f"Hoy es {dia_nombre}. BaratoYa no vende ni entrega.",
    ), "descripcion del hub por día")


def _top_descuento(items: list[dict[str, Any]]) -> tuple[float | None, list[dict[str, Any]]]:
    con = [it for it in items if isinstance(it.get("percent"), (int, float)) and it["percent"] > 0]
    if not con:
        return None, []
    mx = max(float(it["percent"]) for it in con)
    return mx, [it for it in con if float(it["percent"]) == mx]


def _frase_top(ties: list[dict[str, Any]]) -> str:
    por: dict[str, dict[str, Any]] = {}
    for it in ties:
        cid = str(it.get("chain_id") or "")
        if not cid:
            continue
        slot = por.get(cid)
        if slot is None:
            slot = {"cadena": it.get("cadena") or cid, "bancos": []}
            por[cid] = slot
        banco = str(it.get("banco") or "").strip()
        if banco and banco not in slot["bancos"]:
            slot["bancos"].append(banco)
    partes = []
    for cid in sorted(por, key=_orden_cadena):
        slot = por[cid]
        bancos = sorted(slot["bancos"], key=str.casefold)
        if bancos:
            partes.append(f"{slot['cadena']} ({_unir(bancos)})")
        else:
            partes.append(str(slot["cadena"]))
    return _unir(partes)


def _conteo_cadenas(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conteo: dict[str, dict[str, Any]] = {}
    for it in items:
        cid = str(it.get("chain_id") or "")
        if not cid:
            continue
        slot = conteo.get(cid)
        if slot is None:
            conteo[cid] = {"chain_id": cid, "cadena": it.get("cadena") or cid, "n": 0}
            slot = conteo[cid]
        slot["n"] += 1
    ordenados = [conteo[cid] for cid in sorted(conteo, key=_orden_cadena)]
    ordenados.sort(key=lambda s: (-int(s["n"]), _orden_cadena(s["chain_id"])))
    return ordenados


def _items_de(items: list[dict[str, Any]], idx: int) -> list[dict[str, Any]]:
    return [it for it in items if idx in it.get("day_ids", [])]


def promos_de_hoy_por_cadena(hoy: date | None = None) -> dict[str, dict[str, Any]]:
    """Por cadena con página pública: las promos que aplican hoy (día de Argentina).

    Mismas tarjetas que el hub y la página del día. top_pct es el mayor porcentaje
    publicado (None si hoy solo hay cuotas); bancos_top, los bancos que lo dan.
    """
    hoy = hoy or hoy_art()
    wd = hoy.weekday()
    indice = {c["chain_id"]: c for c in cadenas_indexables(hoy)}
    dia = _items_de(_items_publicos(hoy), wd)
    out: dict[str, dict[str, Any]] = {}
    for chain_id, cadena in indice.items():
        propios = [it for it in dia if it.get("chain_id") == chain_id]
        if not propios:
            continue
        top_pct, ties = _top_descuento(propios)
        bancos_top: list[str] = []
        for it in ties:
            banco = str(it.get("banco") or "").strip()
            if banco and banco not in bancos_top:
                bancos_top.append(banco)
        out[chain_id] = {
            "chain_id": chain_id,
            "nombre": cadena["nombre"],
            "href": cadena["href"],
            "n": len(propios),
            "top_pct": top_pct,
            "top_txt": _pct_publico(top_pct) if top_pct is not None else "",
            "bancos_top": bancos_top,
            "cuotas_n": sum(1 for it in propios if "percent" not in it),
        }
    return out



def mejor_dia_por_cadena(hoy: date | None = None) -> dict[str, dict[str, Any]]:
    """Por cadena con página pública: el día (o los días) de la semana con el mayor %.

    Mismas tarjetas que la tabla de la semana del hub (_matriz_semana). bancos son los
    que dan ese % (nombre corto si se reconoce). Una cadena que esta semana solo publica
    cuotas queda con pct None y sin días. Nada se completa a mano.
    """
    hoy = hoy or hoy_art()
    wd = hoy.weekday()
    indice = {c["chain_id"]: c for c in cadenas_indexables(hoy)}
    items = [it for it in _items_publicos(hoy) if it.get("chain_id") in indice]
    out: dict[str, dict[str, Any]] = {}
    for chain_id, cadena in indice.items():
        propios = [it for it in items if it.get("chain_id") == chain_id]
        if not propios:
            continue
        pct, _ = _top_descuento(propios)
        dias: list[dict[str, Any]] = []
        bancos: list[str] = []
        if pct is not None:
            for d in _DIAS_SEO:
                _, ties = _top_descuento(_items_de(propios, int(d["idx"])))
                ties = [it for it in ties if float(it["percent"]) == pct]
                if not ties:
                    continue
                del_dia: list[str] = []
                for it in ties:
                    raw = str(it.get("banco") or "").strip()
                    banco = banco_canonico(raw) or raw
                    if banco and len(banco) <= 28 and banco not in del_dia:
                        del_dia.append(banco)
                    if banco and len(banco) <= 28 and banco not in bancos:
                        bancos.append(banco)
                dias.append({
                    "idx": d["idx"],
                    "nombre": d["nombre"],
                    "href": f"{DESCUENTOS_PATH}/{d['slug']}",
                    "hoy": d["idx"] == wd,
                    "bancos": sorted(del_dia, key=str.casefold),
                })
        out[chain_id] = {
            "chain_id": chain_id,
            "nombre": cadena["nombre"],
            "href": cadena["href"],
            "pct": pct,
            "pct_txt": _pct_publico(pct) if pct is not None else "",
            "dias": dias,
            "bancos": sorted(bancos, key=str.casefold),
        }
    return out

# Bancos y billeteras con nombre propio para la vista "por banco". Primer patrón que
# coincide gana (sobre el texto sin acentos y en minúsculas). Lo que no está acá
# (clubes de diarios, "Visa y Master", "Medios de Pago", jubilados…) queda solo en la
# lista completa de cada cadena: no se adivina de qué banco es.
_BANCOS_CANON: tuple[tuple[str, str], ...] = (
    ("Cuenta DNI (Banco Provincia)", r"cuenta dni"),
    ("Banco Nación", r"^(?!club).*(\bnacion\b|\bbna\b)"),
    ("Banco Galicia", r"\bgalicia\b"),
    ("BBVA", r"\bbbva\b"),
    ("Banco Macro", r"\bmacro\b"),
    ("Banco Patagonia", r"\bpatagonia\b"),
    ("Banco Comafi", r"\bcomafi\b"),
    ("Banco Ciudad", r"\bciudad\b"),
    ("Banco Credicoop", r"\bcredicoop\b"),
    ("Banco Supervielle", r"\bsupervielle\b"),
    ("Banco Hipotecario", r"\bhipotecario\b"),
    ("ICBC", r"\bicbc\b"),
    ("Banco Columbia", r"\bcolumbia\b"),
    ("Bancor (Banco de Córdoba)", r"\bbancor\b|banco cordoba"),
    ("Naranja X", r"\bnaranja\b"),
    ("Mercado Pago", r"mercado pago"),
    ("Personal Pay", r"personal pay"),
    ("CencoPay", r"\bcencopay\b"),
    ("American Express", r"american express"),
    ("MODO", r"^modo$"),
)


def banco_canonico(nombre: str) -> str | None:
    """El banco o la billetera de una promo, con un nombre único. None si no es claro."""
    texto = " ".join(_fold(nombre or "").split())
    if not texto:
        return None
    for canon, patron in _BANCOS_CANON:
        if re.search(patron, texto):
            return canon
    return None


def _pct_de(it: dict[str, Any]) -> float | None:
    pct = it.get("percent")
    if isinstance(pct, (int, float)) and pct > 0:
        return float(pct)
    return None


def _resumen_por_cadena(dia_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Por cadena: el mayor porcentaje publicado ese día, quién lo da y su tope."""
    grupos = _agrupar_cadenas(dia_items)
    filas = []
    for g in grupos:
        top_pct, ties = _top_descuento(g["promos"])
        bancos: list[str] = []
        for it in ties:
            banco = str(it.get("banco") or "").strip()
            if banco and banco not in bancos:
                bancos.append(banco)
        topes = {str(it.get("tope") or "").strip() for it in ties}
        tope = topes.pop() if len(topes) == 1 else ""
        filas.append({
            "chain_id": g["chain_id"],
            "cadena": g["cadena"],
            "href": g["href"],
            "n": len(g["promos"]),
            "top_pct": top_pct,
            "top_txt": _pct_publico(top_pct) if top_pct is not None else "",
            "bancos": sorted(bancos, key=str.casefold),
            "tope": tope,
            "cuotas_n": sum(1 for it in g["promos"] if "percent" not in it),
        })
    filas.sort(key=lambda f: (-(f["top_pct"] or 0), _orden_cadena(f["chain_id"])))
    return filas


def _resumen_por_banco(dia_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Por banco o billetera con nombre claro: en qué cadenas da algo ese día y cuánto."""
    por: dict[str, dict[str, dict[str, Any]]] = {}
    for it in dia_items:
        canon = banco_canonico(str(it.get("banco") or ""))
        cid = str(it.get("chain_id") or "")
        if canon is None or not cid:
            continue
        slot = por.setdefault(canon, {}).get(cid)
        if slot is None:
            slot = {"chain_id": cid, "cadena": it.get("cadena") or cid, "pct": None, "cuotas": False}
            por[canon][cid] = slot
        pct = _pct_de(it)
        if pct is None:
            slot["cuotas"] = True
        elif slot["pct"] is None or pct > slot["pct"]:
            slot["pct"] = pct
    filas = []
    for canon, cadenas in por.items():
        lista = sorted(cadenas.values(), key=lambda c: (-(c["pct"] or 0), _orden_cadena(c["chain_id"])))
        for c in lista:
            c["txt"] = f"{_pct_publico(c['pct'])}%" if c["pct"] is not None else "cuotas"
        mejor = max((c["pct"] for c in lista if c["pct"] is not None), default=None)
        filas.append({
            "banco": canon,
            "top_pct": mejor,
            "top_txt": _pct_publico(mejor) if mejor is not None else "",
            "cadenas": lista,
        })
    filas.sort(key=lambda f: (-(f["top_pct"] or 0), -len(f["cadenas"]), _fold(f["banco"])))
    return filas


def _resumen_dia(spec: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    """Mismos ítems que el bloque de ese día en el hub de promos."""
    dia_items = _items_de(items, int(spec["idx"]))
    cadenas = _agrupar_cadenas(dia_items)
    top_pct, ties = _top_descuento(dia_items)
    top_txt = _pct_publico(top_pct) if top_pct is not None else ""
    top_donde = _frase_top(ties) if ties else ""
    conteo = _conteo_cadenas(dia_items)
    cuotas_n = sum(1 for it in dia_items if "percent" not in it)
    n = len(dia_items)
    plural = spec["plural"]
    if n == 0:
        linea = (
            f"Esta semana, según lo publicado por cada cadena, no hay promos "
            f"vigentes para los {plural}."
        )
    else:
        linea = f"Hay {_n_promos(n)} en {_cadenas_txt(len(cadenas))}."
        if top_txt:
            linea += f" El mayor porcentaje publicado es {top_txt}%"
            if top_donde:
                linea += f", en {top_donde}"
            linea += "."
    return {
        "por_cadena": _resumen_por_cadena(dia_items),
        "por_banco": _resumen_por_banco(dia_items),
        "idx": spec["idx"],
        "slug": spec["slug"],
        "nombre": spec["nombre"],
        "plural": plural,
        "href": f"{DESCUENTOS_PATH}/{spec['slug']}",
        "url": "https://baratoya.app" + f"{DESCUENTOS_PATH}/{spec['slug']}",
        "n": n,
        "cadenas_n": len(cadenas),
        "top_pct": top_pct,
        "top_txt": top_txt,
        "top_donde": top_donde,
        "cuotas_n": cuotas_n,
        "conteo": conteo,
        "linea": linea,
        "cadenas": cadenas,
    }


# Notas que no cambian quién puede usar la promo: avisan que falta un dato o que hay
# rubros excluidos (electro, bodegas, carnes...). Todo lo demás ("solo socios", "solo
# jubilados", "solo productos seleccionados", provincias, primera compra, conflictos
# entre card y legal) deja la promo fuera del bloque "para cualquiera".
_NOTA_PARA_TODOS = re.compile(
    r"^(vigencia no informada(?: en el legal)?|sin tope(?: o tope no informado| informado| de reintegro)?"
    r"|canal no (?:indicado|informado)|excluye .+|aplican exclusiones(?: \(ver legales\))?"
    r"|exclusiones o restricciones(?: \(ver legales\))?|no incluye preciazos)$"
)
_NOTA_EXCLUYE = re.compile(r"^(excluye .+|aplican exclusiones.*|exclusiones o restricciones.*|no incluye preciazos)$")
# Nombres que en realidad son un grupo de clientes, no un banco o billetera abierta.
_BANCO_SEGMENTO = re.compile(r"anses|jubilad|pensionad|emplead|club|sueldo|primera compra")


def _unir_o(partes: list[str]) -> str:
    """Alternativas: "A o B", "A, B o C"."""
    if len(partes) <= 1:
        return "".join(partes)
    return ", ".join(partes[:-1]) + " o " + partes[-1]


def _pesos_txt(n: float) -> str:
    return "$" + f"{int(round(n)):,}".replace(",", ".")


def _apta_para_todos(it: dict[str, Any]) -> bool:
    """Promo con % que puede usar cualquier cliente de ese banco o billetera, con el tope
    publicado (en pesos o "sin tope")."""
    banco = str(it.get("banco") or "")
    if not it.get("percent") or not _es_nombre_banco(banco) or _BANCO_SEGMENTO.search(_fold(banco)):
        return False
    if not (isinstance(it.get("tope_num"), (int, float)) or it.get("tope") == "sin tope"):
        return False
    partes = [_fold(x).strip(" .,") for x in str(it.get("nota") or "").split(";")]
    return all(_NOTA_PARA_TODOS.match(x) for x in partes if x)


def para_todos_dia(dia_items: list[dict[str, Any]], hrefs: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Por cadena, el mayor % de ese día que puede usar cualquiera (sin segmento, socios,
    provincias ni productos seleccionados), con tope y hasta qué compra rinde el %.

    Solo cuentas sobre lo publicado: compra_tope = tope / %. Nada estimado aparte de eso.
    """
    hrefs = hrefs or {}
    por: dict[str, list[dict[str, Any]]] = {}
    for it in dia_items:
        if _apta_para_todos(it) and it.get("chain_id"):
            por.setdefault(str(it["chain_id"]), []).append(it)
    filas = []
    for cid, lista in por.items():
        pct = max(float(it["percent"]) for it in lista)
        ties = [it for it in lista if float(it["percent"]) == pct]
        # Entre los que empatan, el de tope más alto ("sin tope" primero).
        def _tope_key(it: dict[str, Any]) -> float:
            return float("inf") if it.get("tope") == "sin tope" else float(it.get("tope_num") or 0)
        mejor = max(_tope_key(it) for it in ties)
        ties = [it for it in ties if _tope_key(it) == mejor]
        ties.sort(key=lambda it: (_fold(str(it.get("banco") or ""))))
        bancos: list[str] = []
        for it in ties:
            raw = str(it.get("banco") or "").strip()
            b = raw if len(raw) <= 28 else (_banco_corto(raw) or raw)
            if b and b not in bancos:
                bancos.append(b)
        it0 = ties[0]
        canales = []
        for it in ties:
            c = str(it.get("canal") or "").strip()
            if c and c not in canales:
                canales.append(c)
        minimos = sorted({str(it.get("minimo") or "").strip() for it in ties} - {""})
        sin_tope = it0.get("tope") == "sin tope"
        tope_num = None if sin_tope else float(it0["tope_num"])
        compra = tope_num * 100.0 / pct if tope_num else None
        notas = [_fold(x).strip(" .,") for it in ties for x in str(it.get("nota") or "").split(";")]
        excluye = any(_NOTA_EXCLUYE.match(x) for x in notas if x)
        sin_tope_txt = ""
        if sin_tope:
            informado = all(
                not re.search(r"tope no informado|sin tope informado", _fold(str(it.get("nota") or "")))
                for it in ties
            )
            sin_tope_txt = "sin tope" if informado else "sin tope informado"
        filas.append({
            "chain_id": cid,
            "cadena": str(it0.get("cadena") or cid),
            "href": hrefs.get(cid, ""),
            "pct": pct,
            "pct_txt": _pct_publico(pct),
            "bancos": bancos,
            "bancos_txt": _unir_o(bancos),
            "tope_num": tope_num,
            "tope_txt": _pesos_txt(tope_num) if tope_num else sin_tope_txt,
            "compra_tope": compra,
            "compra_txt": _pesos_txt(compra) if compra else "",
            "minimo": minimos[0] if len(minimos) == 1 else "",
            "canal": canales[0] if len(canales) == 1 else ("online y sucursal" if canales else ""),
            "excluye": excluye,
        })
    filas.sort(key=lambda f: (-f["pct"], -(f["tope_num"] or 0), _orden_cadena(f["chain_id"])))
    return filas


def _faq_dia_para_todos(filas: list[dict[str, Any]], plural: str) -> list[dict[str, str]]:
    """Dos preguntas con el bloque "para cualquiera": cuál conviene y cuánto gastar."""
    if not filas:
        return []
    partes = [f"{f['cadena']} {f['pct_txt']}% con {f['bancos_txt']}" for f in filas[:6]]
    resto = len(filas) - len(partes)
    extra = f" y {resto} más" if resto > 0 else ""
    faq = [{
        "q": f"¿Qué descuentos de supermercado de los {plural} puede usar cualquiera?",
        "a": (
            f"Esta semana, según lo publicado por cada cadena, los {plural} hay descuentos sin requisitos "
            f"especiales (no son solo para jubilados, socios de un club, una provincia o productos "
            f"seleccionados) en {_unir(partes)}{extra}. Las exclusiones de rubros de cada legal siguen valiendo."
        ),
    }]
    con_tope = [f for f in filas if f["compra_tope"]]
    if con_tope:
        frases = []
        for i, f in enumerate(con_tope[:3]):
            rinde = "el descuento completo rinde hasta una compra de" if i == 0 else "rinde hasta"
            frase = f"con {f['bancos_txt']} en {f['cadena']} ({f['pct_txt']}%, tope {f['tope_txt']}) {rinde} {f['compra_txt']}"
            if f["minimo"]:
                minimo = (_pesos_en(f["minimo"]) or [0.0])[0]
                if minimo and minimo >= f["compra_tope"]:
                    frase += f" (pide un mínimo de {f['minimo']}: con el mínimo ya llegás al tope)"
                else:
                    frase += f" y pide un mínimo de {f['minimo']}"
            frases.append(frase)
        texto = "Esta semana, según lo publicado por cada cadena, " + "; ".join(frases) + "."
        texto += " Arriba de ese monto el reintegro queda en el tope, así que el porcentaje real baja."
        faq.append({
            "q": f"¿Cuánto conviene gastar los {plural} para aprovechar el tope del descuento?",
            "a": texto,
        })
    return faq


def _respuesta_descuentos_dia(resumen: dict[str, Any]) -> str:
    """Responde con el conteo y, si está publicado, el mayor porcentaje. Nada inventado."""
    plural = resumen["plural"]
    n = int(resumen["n"])
    if n <= 0:
        return (
            f"Esta semana, según lo publicado por cada cadena, no hay descuentos "
            f"vigentes los {plural} en supermercados de CABA."
        )
    cadenas = [str(slot["cadena"]) for slot in resumen["conteo"]]
    donde = _unir(cadenas) if cadenas else _cadenas_txt(int(resumen["cadenas_n"]))
    texto = (
        f"Esta semana, según lo publicado por cada cadena, hay {_n_promos(n)} "
        f"los {plural} en {donde}."
    )
    if resumen["top_txt"]:
        donde_top = f" en {resumen['top_donde']}" if resumen["top_donde"] else ""
        texto += f" El mayor porcentaje publicado es {resumen['top_txt']}%{donde_top}."
    else:
        texto += " Ese día las cadenas no publican un porcentaje."
    return texto


def _faq_dia(resumen: dict[str, Any]) -> list[dict[str, str]]:
    plural = resumen["plural"]
    n = int(resumen["n"])
    faq: list[dict[str, str]] = [{
        "q": f"¿Cuáles son los descuentos en supermercados los {plural}?",
        "a": _respuesta_descuentos_dia(resumen),
    }]
    if n <= 0:
        faq.append({
            "q": f"¿Hay descuentos en supermercados los {plural}?",
            "a": (
                f"Esta semana, según lo publicado por cada cadena, no hay promos "
                f"vigentes para los {plural} en supermercados de CABA."
            ),
        })
        return faq
    if resumen["top_txt"]:
        donde = resumen["top_donde"]
        donde_txt = f", en {donde}" if donde else ""
        faq.append({
            "q": f"¿Qué supermercado tiene más descuento los {plural}?",
            "a": (
                f"Esta semana, según lo publicado por cada cadena, el mayor porcentaje "
                f"los {plural} es {resumen['top_txt']}%{donde_txt}."
            ),
        })
    else:
        faq.append({
            "q": f"¿Hay un porcentaje de descuento publicado los {plural}?",
            "a": (
                f"Esta semana, según lo publicado por cada cadena, las promos de los "
                f"{plural} no traen un porcentaje. Hay {_n_promos(int(resumen['cuotas_n']))} de cuotas."
            ),
        })
    conteo = resumen["conteo"]
    if conteo:
        maximo = int(conteo[0]["n"])
        top = [slot["cadena"] for slot in conteo if int(slot["n"]) == maximo]
        if len(top) == 1:
            frase = (
                f"Esta semana, según lo publicado por cada cadena, {top[0]} tiene "
                f"{_n_promos(maximo)} los {plural}. Es la cadena con más promos ese día."
            )
        else:
            frase = (
                f"Esta semana, según lo publicado por cada cadena, {_unir(top)} tienen "
                f"{_n_promos(maximo)} los {plural} cada una. "
                f"Empatan como las cadenas con más promos ese día."
            )
        faq.append({
            "q": f"¿Qué supermercado tiene más promos los {plural}?",
            "a": frase,
        })
    bancos = [b for b in resumen.get("por_banco") or [] if b["top_txt"]]
    if bancos:
        partes = [
            f"{b['banco']} (hasta {b['top_txt']}% en {b['cadenas'][0]['cadena']})" for b in bancos[:8]
        ]
        resto = len(bancos) - len(partes)
        extra = f" y {resto} más" if resto > 0 else ""
        faq.append({
            "q": f"¿Qué bancos tienen descuento en supermercados los {plural}?",
            "a": (
                f"Esta semana, según lo publicado por cada cadena, los {plural} hay descuento con "
                f"{_unir(partes)}{extra}. Cada promo tiene su tope y sus condiciones: están en la "
                f"lista de cada supermercado."
            ),
        })
    filas = [f for f in resumen.get("por_cadena") or []]
    if filas:
        partes = []
        for f in filas:
            if f["top_txt"]:
                partes.append(f"{f['cadena']} {f['top_txt']}%")
            else:
                partes.append(f"{f['cadena']} solo cuotas")
        faq.append({
            "q": f"¿Qué descuento da cada supermercado los {plural}?",
            "a": (
                f"Esta semana, según lo publicado por cada cadena, el mayor descuento de los "
                f"{plural} en cada supermercado es: {_unir(partes)}. Es el mejor caso con el banco "
                f"o la billetera que lo da, no un descuento para todos los medios de pago."
            ),
        })
    cuotas = int(resumen["cuotas_n"])
    if cuotas:
        cierre = (
            f" De esas, {_n_promos(cuotas)} son cuotas y no un porcentaje. "
            f"Las cuotas no se restan del precio."
        )
    else:
        cierre = ""
    faq.append({
        "q": f"¿Cuántos descuentos de supermercado hay los {plural}?",
        "a": (
            f"Esta semana, según lo publicado por cada cadena, hay {_n_promos(n)} "
            f"los {plural}, en {_cadenas_txt(int(resumen['cadenas_n']))} de CABA.{cierre}"
        ),
    })
    return faq


def _faq_dias(resumenes: list[dict[str, Any]], dia_hoy: str) -> list[dict[str, str]]:
    faq: list[dict[str, str]] = []
    con_promos = [r for r in resumenes if r["n"]]
    if not con_promos:
        faq.append({
            "q": "¿Qué día hay descuentos en los supermercados?",
            "a": "Esta semana, según lo publicado por cada cadena, no hay promos vigentes de lunes a domingo.",
        })
        return faq
    maximo = max(int(r["n"]) for r in con_promos)
    top = [r for r in resumenes if int(r["n"]) == maximo]
    if len(top) == 1:
        frase = (
            f"Esta semana, según lo publicado por cada cadena, los {top[0]['plural']} "
            f"tienen {_n_promos(maximo)}. Es el día con más promos."
        )
    else:
        nombres = _unir([f"los {r['plural']}" for r in top])
        frase = (
            f"Esta semana, según lo publicado por cada cadena, {nombres} tienen "
            f"{_n_promos(maximo)} cada uno. Empatan como los días con más promos."
        )
    faq.append({
        "q": "¿Qué día hay más promos de supermercado?",
        "a": frase,
    })
    con_pct = [r for r in resumenes if r["top_pct"] is not None]
    if con_pct:
        mejor = max(float(r["top_pct"]) for r in con_pct)
        dias_top = [r for r in con_pct if float(r["top_pct"]) == mejor]
        pct = _pct_publico(mejor)
        if len(dias_top) == 1:
            r = dias_top[0]
            donde = f" En {r['top_donde']}." if r["top_donde"] else ""
            texto = (
                f"Esta semana, según lo publicado por cada cadena, el mayor porcentaje "
                f"es {pct}%, los {r['plural']}.{donde}"
            )
        else:
            nombres = _unir([f"los {r['plural']}" for r in dias_top])
            texto = (
                f"Esta semana, según lo publicado por cada cadena, el mayor porcentaje "
                f"es {pct}%, {nombres}."
            )
        faq.append({
            "q": "¿Qué día tiene el mayor porcentaje de descuento?",
            "a": texto,
        })
    faq.append({
        "q": "¿Qué día es hoy para estas promos?",
        "a": (
            f"Hoy es {dia_hoy}, con la hora de Argentina. "
            f"Una promo entra en un día si ese día está en su lista y la fecha "
            f"cae entre el inicio y el fin de vigencia."
        ),
    })
    return faq


def _breadcrumb_dias(extra: dict[str, str] | None = None) -> str:
    items = [
        {
            "@type": "ListItem",
            "position": 1,
            "name": "Inicio",
            "item": "https://baratoya.app/",
        },
        {
            "@type": "ListItem",
            "position": 2,
            "name": "Descuentos en supermercados",
            "item": DESCUENTOS_URL,
        },
    ]
    if extra:
        items.append({
            "@type": "ListItem",
            "position": 3,
            "name": extra["name"],
            "item": extra["item"],
        })
    return _ld({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items,
    })


def _vista_listados(hoy: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Ítems públicos del hub y el resumen de cada día, con la misma fecha."""
    items = _items_publicos(hoy)
    return items, [_resumen_dia(spec, items) for spec in _DIAS_SEO]


def _calendario_bancos(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Banco o billetera × día de la semana: el mayor % publicado y en qué cadena.

    Sale de las mismas tarjetas que las páginas por día (mismo alias de bancos que el
    hub). Un banco sin nombre claro (p. ej. "Visa y Master") no entra. Nada a mano.
    """
    por: dict[str, dict[int, dict[str, Any]]] = {}
    for it in items:
        canon = banco_canonico(str(it.get("banco") or ""))
        if canon is None:
            continue
        pct = _pct_de(it)
        for idx in it.get("day_ids", []):
            slot = por.setdefault(canon, {}).setdefault(int(idx), {"pct": None, "cadenas": []})
            cadena = str(it.get("cadena") or it.get("chain_id") or "")
            if pct is not None and (slot["pct"] is None or pct > slot["pct"]):
                slot["pct"] = pct
                slot["cadenas"] = [cadena] if cadena else []
            elif pct is not None and pct == slot["pct"] and cadena and cadena not in slot["cadenas"]:
                slot["cadenas"].append(cadena)
    filas = []
    for canon, dias in por.items():
        mejor = max((d["pct"] for d in dias.values() if d["pct"] is not None), default=None)
        mejores = []
        cadenas_mejor: list[str] = []
        for spec in _DIAS_SEO:
            d = dias.get(int(spec["idx"]))
            if d and mejor is not None and d["pct"] == mejor:
                mejores.append(spec["nombre"])
                for c in d["cadenas"]:
                    if c not in cadenas_mejor:
                        cadenas_mejor.append(c)
        filas.append({
            "banco": canon,
            "mejor_pct": mejor,
            "mejor_txt": _pct_publico(mejor) if mejor is not None else "",
            "mejores_dias": mejores,
            "cadenas_mejor": cadenas_mejor,
            "dias": [spec["nombre"] for spec in _DIAS_SEO if int(spec["idx"]) in dias],
        })
    filas.sort(key=lambda f: (-(f["mejor_pct"] or 0), -len(f["dias"]), _fold(f["banco"])))
    return filas


def _texto_dias(nombres: list[str]) -> str:
    return _unir(nombres) if len(nombres) <= 3 else f"{len(nombres)} días de la semana"


def _linea_banco(f: dict[str, Any]) -> str:
    """Banco Nación: hasta 35% el miércoles en Mas Online. Tiene promos 5 días."""
    if f["mejor_txt"]:
        cadenas = f["cadenas_mejor"]
        donde = ""
        if cadenas:
            donde = f" en {_unir(cadenas)}" if len(cadenas) <= 3 else f" en {len(cadenas)} cadenas"
        dias = f["mejores_dias"]
        plural = {str(spec["nombre"]): str(spec["plural"]) for spec in _DIAS_SEO}
        if len(dias) == 1:
            cuando = f"el {dias[0]}"
        elif len(dias) <= 3:
            cuando = f"los {_unir([plural.get(d, d) for d in dias])}"
        else:
            cuando = f"en {len(dias)} días de la semana"
        texto = f"hasta {f['mejor_txt']}% {cuando}{donde}"
    else:
        texto = "solo cuotas"
    n = len(f["dias"])
    if n == 7:
        texto += ". Tiene promos todos los días"
    elif n >= 5:
        faltan = [str(spec["nombre"]) for spec in _DIAS_SEO if str(spec["nombre"]) not in f["dias"]]
        texto += f". Tiene promos todos los días menos el {_unir(faltan).replace(' y ', ' y el ')}"
    else:
        plurales = {str(spec["nombre"]): str(spec["plural"]) for spec in _DIAS_SEO}
        texto += f". Tiene promos los {_unir([plurales.get(d, d) for d in f['dias']])}"
    return texto + "."


def _que_dia_conviene(resumenes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """El día con más promos y el día con el mayor %. Solo con los datos cargados."""
    con = [r for r in resumenes if r["n"]]
    if not con:
        return None
    maximo = max(int(r["n"]) for r in con)
    mas = [r for r in con if int(r["n"]) == maximo]
    con_pct = [r for r in con if r["top_pct"] is not None]
    mejor = max((float(r["top_pct"]) for r in con_pct), default=None)
    top = [r for r in con_pct if mejor is not None and float(r["top_pct"]) == mejor]
    if len(mas) == 1:
        texto = (
            f"Esta semana, según lo publicado por cada cadena, el día con más promos es "
            f"el {mas[0]['nombre']} ({_n_promos(maximo)})."
        )
    else:
        texto = (
            f"Esta semana, según lo publicado por cada cadena, los días con más promos son "
            f"{_unir(['el ' + str(r['nombre']) for r in mas])} ({_n_promos(maximo)} cada uno)."
        )
    if top:
        top_txt = _unir([f"el {r['nombre']}" for r in top])
        donde = f", en {top[0]['top_donde']}" if len(top) == 1 and top[0]["top_donde"] else ""
        if len(top) > 1 and len({r["top_donde"] for r in top}) == 1 and top[0]["top_donde"]:
            donde = f", en {top[0]['top_donde']}"
        texto += f" El mayor porcentaje es {_pct_publico(mejor)}%, {top_txt}{donde}."
    return {
        "mas": mas,
        "mas_n": maximo,
        "top": top,
        "top_pct": mejor,
        "top_txt": _pct_publico(mejor) if mejor is not None else "",
        "texto": texto,
    }


def descripcion_dias_conviene(conviene: dict[str, Any] | None, n: int, cadenas_n: int) -> str:
    """Meta con el dato (120-155): qué día tiene más promos y el mayor %. "" si no entra."""
    if not conviene or n <= 0:
        return ""
    mas = _unir(["el " + str(r["nombre"]) for r in conviene["mas"]])
    tiene = "tiene" if len(conviene["mas"]) == 1 else "tienen"
    top = _unir(["el " + str(r["nombre"]) for r in conviene["top"]])
    llega = "llega" if len(conviene["top"]) == 1 else "llegan"
    lugar = _cadenas_txt(cadenas_n)
    opciones = []
    if conviene["top_txt"]:
        opciones += [
            f"Qué día conviene ir al súper: {mas} {tiene} más promos ({conviene['mas_n']}) y {top} {llega} a {conviene['top_txt']}%. Por día y por banco, {n} promos en {lugar} de CABA.",
            f"Qué día conviene ir al súper: {mas} {tiene} más promos ({conviene['mas_n']}) y {top} {llega} a {conviene['top_txt']}%. {n} promos en {lugar} de CABA.",
            f"Qué día conviene ir al súper: {mas} {tiene} más promos y {top} {llega} a {conviene['top_txt']}%. Por día y por banco, en {lugar} de CABA.",
        ]
    opciones.append(
        f"Qué día conviene ir al supermercado: {mas} {tiene} más promos ({conviene['mas_n']}). Descuentos por día y por banco, {n} promos en {lugar} de CABA."
    )
    for texto in opciones:
        if 120 <= len(texto) <= 155 and '"' not in texto and "<" not in texto:
            return texto
    return ""


def _faq_dias_extra(conviene: dict[str, Any] | None, bancos: list[dict[str, Any]]) -> list[dict[str, str]]:
    faq: list[dict[str, str]] = []
    if conviene:
        faq.append({
            "q": "¿Cuál es el mejor día para ir al supermercado?",
            "a": (
                conviene["texto"]
                + " El que más conviene depende de tu banco o billetera: cada promo tiene su "
                "tope, compra mínima y exclusiones."
            ),
        })
    con_pct = [b for b in bancos if b["mejor_txt"]]
    if con_pct:
        partes = []
        for b in con_pct[:8]:
            dias = b["mejores_dias"]
            partes.append(f"{b['banco']}: {_texto_dias(dias)} ({b['mejor_txt']}%)")
        resto = len(con_pct) - len(partes)
        extra = f" y {resto} bancos o billeteras más en la lista" if resto > 0 else ""
        faq.append({
            "q": "¿Qué día descuenta mi banco en el supermercado?",
            "a": (
                f"Esta semana, el día con el mayor descuento publicado de cada banco o billetera "
                f"en supermercados de CABA es: {'; '.join(partes)}{extra}."
            ),
        })
    return faq


def pagina_seo_dias(hoy: date | None = None) -> dict[str, Any]:
    """Vista de /descuentos-supermercados. Enlaza los 7 días y marca el de hoy."""
    hoy = hoy or hoy_art()
    items, resumenes = _vista_listados(hoy)
    wd = hoy.weekday()
    for resumen, spec in zip(resumenes, _DIAS_SEO):
        resumen["hoy"] = spec["idx"] == wd
    dia = NOMBRE_DIA[wd]
    conviene = _que_dia_conviene(resumenes)
    bancos = _calendario_bancos(items)
    for r in resumenes:
        r["mas"] = bool(conviene) and any(m["idx"] == r["idx"] for m in conviene["mas"])
        r["top"] = bool(conviene) and any(t["idx"] == r["idx"] for t in conviene["top"])
    for b in bancos:
        b["linea"] = _linea_banco(b)
    faq = _faq_dias(resumenes, dia) + _faq_dias_extra(conviene, bancos)
    actualizado = fecha_datos_promos(hoy)
    cadenas_n = len({it["chain_id"] for it in items})
    fecha = fecha_larga(hoy)
    if len(items) == 1:
        promos_txt = "1 promo vigente"
    else:
        promos_txt = f"{len(items)} promos vigentes"
    intro = (
        f"Esta semana, según lo publicado por cada cadena, hay {promos_txt} en "
        f"{_cadenas_txt(cadenas_n)} de CABA, de lunes a domingo. Hoy es {dia} {fecha}."
    )
    return {
        "title": DESCUENTOS_TITLE,
        "description": descripcion_dias_conviene(conviene, len(items), cadenas_n)
        or descripcion_dias(len(items), cadenas_n, dia),
        "conviene": conviene,
        "bancos": bancos,
        "hoy_resumen": next((r for r in resumenes if r["idx"] == wd), None),
        "canonical": DESCUENTOS_URL,
        "h1": DESCUENTOS_H1,
        "path": DESCUENTOS_PATH,
        "hoy_iso": hoy.isoformat(),
        "dia": dia,
        "fecha": fecha,
        "intro": intro,
        "actualizado": fecha_larga(actualizado) if actualizado else "",
        "n": len(items),
        "cadenas_n": cadenas_n,
        "dias": resumenes,
        "dias_nav": nav_dias(hoy),
        "cadenas": cadenas_indexables(hoy),
        "hub_promos": SEO_PATH,
        "faq": faq,
        "notas": notas_honestidad(),
        "ld_faq": _ld_faq(faq),
        "ld_breadcrumb": _breadcrumb_dias(),
    }


def pagina_seo_dia(slug: str, hoy: date | None = None) -> dict[str, Any] | None:
    """Vista de /descuentos-supermercados/<dia>. None si el slug no es un día."""
    spec = _DIA_POR_SLUG.get((slug or "").strip())
    if spec is None:
        return None
    hoy = hoy or hoy_art()
    _items, resumenes = _vista_listados(hoy)
    resumen = next(r for r in resumenes if r["slug"] == spec["slug"])
    wd = hoy.weekday()
    for row in resumenes:
        row["hoy"] = row["idx"] == wd
    plural = spec["plural"]
    hrefs = {str(f["chain_id"]): str(f["href"] or "") for f in resumen["por_cadena"]}
    para_todos = para_todos_dia(_items_de(_items, int(spec["idx"])), hrefs)
    con_algo = {f["chain_id"] for f in para_todos}
    sin_para_todos = [str(f["cadena"]) for f in resumen["por_cadena"] if f["chain_id"] not in con_algo]
    faq = _faq_dia(resumen) + _faq_dia_para_todos(para_todos, plural)
    actualizado = fecha_datos_promos(hoy)
    canonical = resumen["url"]
    es_hoy = spec["idx"] == wd
    fecha = fecha_larga(hoy)
    dia_hoy = NOMBRE_DIA[wd]
    top_cadena = top_banco = ""
    primera = (resumen["por_cadena"] or [None])[0]
    if primera and primera["top_txt"]:
        top_cadena = str(primera["cadena"])
        if len(primera["bancos"]) == 1:
            raw = primera["bancos"][0]
            top_banco = banco_canonico(raw) or (raw if len(raw) <= 24 else "")
    comparar = [
        {
            "nombre": r["nombre"],
            "plural": r["plural"],
            "href": r["href"],
            "n": r["n"],
            "top_txt": r["top_txt"],
            "cadenas_n": r["cadenas_n"],
            "hoy": r["hoy"],
            "actual": r["slug"] == spec["slug"],
        }
        for r in resumenes
    ]
    return {
        "por_cadena": resumen["por_cadena"],
        "por_banco": resumen["por_banco"],
        "para_todos": para_todos,
        "sin_para_todos": sin_para_todos,
        "sin_para_todos_txt": _unir(sin_para_todos),
        "comparar": comparar,
        "title": titulo_dia(plural, es_hoy=es_hoy),
        "description": descripcion_dia(
            plural, resumen["n"], resumen["cadenas_n"], resumen["top_pct"], top_cadena, top_banco
        ),
        "canonical": canonical,
        "h1": h1_dia(plural, es_hoy=es_hoy),
        "intro": intro_dia(resumen, fecha, dia_hoy, es_hoy),
        "path": resumen["href"],
        "slug": spec["slug"],
        "nombre": spec["nombre"],
        "plural": plural,
        "es_hoy": es_hoy,
        "hoy_iso": hoy.isoformat(),
        "dia_hoy": dia_hoy,
        "fecha": fecha,
        "actualizado": fecha_larga(actualizado) if actualizado else "",
        "n": resumen["n"],
        "cadenas_n": resumen["cadenas_n"],
        "top_txt": resumen["top_txt"],
        "top_donde": resumen["top_donde"],
        "linea": resumen["linea"],
        "cadenas": resumen["cadenas"],
        "dias_nav": nav_dias(hoy),
        "otras_cadenas": cadenas_indexables(hoy),
        "hub_promos": SEO_PATH,
        "hub_dias": DESCUENTOS_PATH,
        "faq": faq,
        "notas": notas_honestidad(),
        "ld_faq": _ld_faq(faq),
        "ld_breadcrumb": _breadcrumb_dias({"name": spec["nombre"], "item": canonical}),
    }

