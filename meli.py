"""Búsqueda oficial de Mercado Libre Argentina. Sin HTML y sin proxy.

Usa la app BaratoYa (client credentials) solo si MLA_PUBLIC_SEARCH=true.
Si faltan las variables, no inventa precios.

Mercado Libre cerró la búsqueda pública de catálogo. GET
/sites/MLA/search?q= responde 403 desde IPs residenciales y de nube, con
o sin Authorization. La documentación oficial solo deja búsqueda acotada
al vendedor, con OAuth de un usuario vinculado. El token client_credentials
no restaura el listado de todo el marketplace. No scrapear
listado.mercadolibre.com.ar: ENABLE_PAID_SCRAPERS sigue en false y no se
inventan precios. Volver a mostrar publicaciones de MLA es una decisión
de producto (programa partner o OAuth por usuario), no un ajuste de este
cliente. ENABLE_MLA no reabre ese recurso.
"""
from __future__ import annotations

import os
import time
import unicodedata
from typing import Any

import httpx

TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
# Recurso cerrado: 403 para cualquier cliente. Ver el docstring del módulo.
SEARCH_URL = "https://api.mercadolibre.com/sites/MLA/search"
AVISO_CATALOGO_CERRADO = (
    "Mercado Libre cerró la búsqueda pública de su API; por ahora BaratoYa muestra súpers oficiales."
)
_STOP = {
    "la", "el", "los", "las", "de", "del", "y", "e", "o", "u",
    "con", "para", "por", "en", "al", "un", "una", "lo", "a",
}
_token: dict[str, Any] = {"value": "", "exp": 0.0}


def _fold(s: str) -> str:
    raw = unicodedata.normalize("NFKD", s or "")
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return " ".join(raw.casefold().split())


def _tokens(q: str) -> list[str]:
    out = []
    for part in _fold(q).split():
        if part in _STOP or len(part) < 2:
            continue
        out.append(part)
    return out


def credenciales() -> tuple[str, str]:
    return (
        os.getenv("MERCADOLIBRE_CLIENT_ID", "").strip(),
        os.getenv("MERCADOLIBRE_CLIENT_SECRET", "").strip(),
    )


def busqueda_publica_habilitada() -> bool:
    """True solo con MLA_PUBLIC_SEARCH=true.

    Por defecto está apagada. El catálogo público ya no existe: cada búsqueda
    pegaba a /sites/MLA/search, recibía 403 y la UI lo mostraba como si
    BaratoYa hubiera fallado. ENABLE_MLA no alcanza para reabrirla.
    """
    return os.getenv("MLA_PUBLIC_SEARCH", "false").lower() == "true"


def _ean(item: dict[str, Any]) -> str:
    attrs = item.get("attributes") or []
    if not isinstance(attrs, list):
        return ""
    for attr in attrs:
        if not isinstance(attr, dict):
            continue
        if str(attr.get("id") or "") not in {"GTIN", "EAN", "GTIN14"}:
            continue
        value = str(attr.get("value_name") or "").strip()
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) in {8, 12, 13, 14}:
            return digits
    return ""


def _attr(item: dict[str, Any], key: str) -> str:
    attrs = item.get("attributes") or []
    if not isinstance(attrs, list):
        return ""
    for attr in attrs:
        if isinstance(attr, dict) and str(attr.get("id") or "") == key:
            return str(attr.get("value_name") or "").strip()
    return ""


def _cabe(q: str, item: dict[str, Any]) -> bool:
    tokens = _tokens(q)
    if not tokens:
        return False
    hay = _fold(" ".join([
        str(item.get("title") or ""),
        _attr(item, "BRAND"),
        _attr(item, "MODEL"),
    ]))
    return all(token in hay for token in tokens)


def _precio(item: dict[str, Any]) -> float | None:
    price = item.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return None
    if price <= 0:
        return None
    return float(price)


def _imagen(item: dict[str, Any]) -> str:
    url = item.get("thumbnail") or ""
    if isinstance(url, str) and url.startswith("https://"):
        return url
    return ""


def _fila(item: dict[str, Any]) -> dict[str, Any] | None:
    precio = _precio(item)
    title = str(item.get("title") or "").strip()
    url = str(item.get("permalink") or "").strip()
    if precio is None or not title or not url.startswith("https://"):
        return None
    return {
        "tienda": "Mercado Libre",
        "tienda_id": "mla",
        "nombre": title,
        "marca": _attr(item, "BRAND"),
        "modelo": _attr(item, "MODEL"),
        "precio": precio,
        "precio_lista": None,
        "descuento_tienda": None,
        "url": url,
        "disponible": True,
        "fuente_item": "mercadolibre",
        "ean": _ean(item),
        "imagen": _imagen(item),
        "canal": "marketplace",
    }


async def _access_token(client: httpx.AsyncClient) -> tuple[str, str]:
    client_id, client_secret = credenciales()
    if not client_id or not client_secret:
        return "", "faltan MERCADOLIBRE_CLIENT_ID y MERCADOLIBRE_CLIENT_SECRET"
    now = time.time()
    if _token["value"] and now < float(_token["exp"]):
        return str(_token["value"]), ""
    try:
        r = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Accept": "application/json"},
        )
    except Exception as e:
        return "", str(e)
    if r.status_code != 200:
        return "", f"token http {r.status_code}"
    try:
        body = r.json()
    except Exception:
        return "", "token sin json"
    token = body.get("access_token") if isinstance(body, dict) else None
    if not isinstance(token, str) or not token:
        return "", "token vacío"
    expires = body.get("expires_in") if isinstance(body, dict) else 0
    try:
        ttl = int(expires)
    except (TypeError, ValueError):
        ttl = 300
    _token["value"] = token
    _token["exp"] = now + max(60, ttl - 60)
    return token, ""


async def buscar_meli(q: str, limit: int = 10) -> dict[str, Any]:
    """Publicaciones activas cuyo título cubre la búsqueda. Precio actual, no tachado."""
    vacio = {
        "tienda": "Mercado Libre",
        "tienda_id": "mla",
        "http": 0,
        "ok": False,
        "n": 0,
        "productos": [],
        "aviso": "",
    }
    if not busqueda_publica_habilitada():
        # No es un error de esta búsqueda: no hay listado público que consultar.
        vacio["omitido"] = "catalogo_publico_cerrado"
        return vacio
    if not all(credenciales()):
        vacio["aviso"] = "sin credenciales de la app"
        return vacio
    async with httpx.AsyncClient(timeout=15.0) as client:
        token, err = await _access_token(client)
        if not token:
            vacio["aviso"] = err or "sin token"
            return vacio
        try:
            r = await client.get(
                SEARCH_URL,
                params={"q": q, "limit": max(1, min(limit, 20))},
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        except Exception as e:
            vacio["aviso"] = str(e)
            return vacio
    vacio["http"] = r.status_code
    if r.status_code != 200:
        if r.status_code == 403:
            # Cerrado para el token de app, para un token de otro vendedor y sin auth.
            vacio["aviso"] = AVISO_CATALOGO_CERRADO
        else:
            vacio["aviso"] = f"búsqueda http {r.status_code}"
        return vacio
    try:
        body = r.json()
    except Exception:
        vacio["aviso"] = "búsqueda sin json"
        return vacio
    results = body.get("results") if isinstance(body, dict) else None
    productos: list[dict[str, Any]] = []
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict) or not _cabe(q, item):
                continue
            row = _fila(item)
            if row:
                productos.append(row)
    productos.sort(key=lambda p: p["precio"])
    vacio["ok"] = bool(productos)
    vacio["n"] = len(productos)
    vacio["productos"] = productos
    vacio["aviso"] = "" if productos else "ninguna publicación coincide con la búsqueda"
    return vacio
