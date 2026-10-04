"""Súper: catálogos VTEX públicos de Mas Online, Día y Carrefour. $0.

Solo entra un producto si el JSON trae commertialOffer.Price numérico > 0.
No hay scrapers pagos, proxies, Coto ni Mercado Libre.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

# Verificado 2026-10-03 ~21:46 ART desde este servidor (Price numérico > 0):
# Mas Online: ft=yerba → HTTP 206, Yerba Mate Taragui 500g, Price 3609.0 (pase 20:45).
# Día: ft=yerba chamigo → Yerba Mate Chamigo 500 Gr., Price 1950.0.
# Carrefour: ft=yerba natura → Yerba mate Natura 500 g., Price 1829.0.
STORES: list[dict[str, str]] = [
    {
        "id": "masonline",
        "nombre": "Mas Online",
        "origin": "https://www.masonline.com.ar",
        "fuente": "mas_online_vtex",
    },
    {
        "id": "dia",
        "nombre": "Día",
        "origin": "https://diaonline.supermercadosdia.com.ar",
        "fuente": "dia_vtex",
    },
    {
        "id": "carrefour",
        "nombre": "Carrefour",
        "origin": "https://www.carrefour.com.ar",
        "fuente": "carrefour_vtex",
    },
]

VTEX_PATH = "/api/catalog_system/pub/products/search"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def _precio(product: dict[str, Any]) -> tuple[float | None, bool]:
    items = product.get("items") or []
    if not items or not isinstance(items[0], dict):
        return None, False
    sellers = items[0].get("sellers") or []
    if not sellers or not isinstance(sellers[0], dict):
        return None, False
    offer = sellers[0].get("commertialOffer") or {}
    price = offer.get("Price")
    if not isinstance(price, (int, float)) or isinstance(price, bool):
        return None, False
    if price <= 0:
        return None, False
    return float(price), bool(offer.get("IsAvailable"))


def _parse(store: dict[str, str], body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, list):
        return []
    out: list[dict[str, Any]] = []
    for product in body:
        if not isinstance(product, dict):
            continue
        price, available = _precio(product)
        if price is None:
            continue
        name = product.get("productName") or product.get("productTitle")
        if not name:
            continue
        out.append(
            {
                "tienda": store["nombre"],
                "tienda_id": store["id"],
                "nombre": name,
                "marca": product.get("brand") or "",
                "precio": price,
                "url": product.get("link") or "",
                "disponible": available,
                "fuente_item": store["fuente"],
            }
        )
    return out


_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def _limpia(s: str) -> str:
    return " ".join((s or "").split())


def _sin_puntuacion(s: str) -> str:
    """VTEX responde 400 si ft trae '+' o signos. El espacio va como %20, no como '+'."""
    return _limpia(_PUNCT.sub(" ", s or "").replace("_", " "))


def _ft_url(origin: str, q: str) -> str:
    # quote (no quote_plus): un '+' en ft hace que Mas Online conteste
    # "Bad Request! Scripts are not allowed!".
    return origin.rstrip("/") + VTEX_PATH + "?ft=" + quote(q, safe="") + "&_from=0&_to=4"


async def _fetch(client: httpx.AsyncClient, store: dict[str, str], q: str) -> dict[str, Any]:
    url = _ft_url(store["origin"], q)
    try:
        r = await client.get(url, headers={"Accept": "application/json", "User-Agent": UA})
    except Exception as e:
        return {
            "tienda": store["nombre"],
            "tienda_id": store["id"],
            "http": 0,
            "ok": False,
            "error": str(e),
            "productos": [],
            "q_usada": q,
        }
    productos: list[dict[str, Any]] = []
    parse_error = ""
    if r.status_code in (200, 206):
        try:
            productos = _parse(store, r.json())
        except Exception as e:
            productos = []
            parse_error = str(e)
    row: dict[str, Any] = {
        "tienda": store["nombre"],
        "tienda_id": store["id"],
        "http": r.status_code,
        "ok": bool(productos),
        "productos": productos,
        "q_usada": q,
    }
    if parse_error:
        row["error"] = parse_error
    elif r.status_code not in (200, 206):
        row["error"] = f"HTTP {r.status_code}"
    return row


async def _one(client: httpx.AsyncClient, store: dict[str, str], q: str) -> dict[str, Any]:
    intento = _limpia(q)
    row = await _fetch(client, store, intento)
    if row["http"] in (200, 206):
        return row
    sano = _sin_puntuacion(intento)
    if not sano or sano.casefold() == intento.casefold():
        return row
    retry = await _fetch(client, store, sano)
    if retry["http"] in (200, 206) or retry["http"] not in (0,):
        return retry
    return row


async def buscar_super(q: str, consultas: list[str] | None = None) -> dict[str, Any]:
    """Catálogos públicos de súper ya verificados: Mas Online, Día y Carrefour.

    Si la frase completa no trae un precio > 0, prueba las consultas más cortas
    en orden y deja en q_usada la que sí coincidió.
    """
    intentos: list[str] = []
    for cand in consultas or [q]:
        limpio = _limpia(cand)
        if limpio and limpio.casefold() not in {x.casefold() for x in intentos}:
            intentos.append(limpio)
    if not intentos:
        intentos = [_limpia(q) or q]

    fuentes: list[dict[str, Any]] = []
    productos: list[dict[str, Any]] = []
    q_usada = intentos[0]
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        for intento in intentos:
            fuentes = []
            productos = []
            for store in STORES:
                row = await _one(client, store, intento)
                fuentes.append(
                    {
                        "tienda": row["tienda"],
                        "tienda_id": row["tienda_id"],
                        "http": row["http"],
                        "ok": row["ok"],
                        "n": len(row["productos"]),
                        "q": row.get("q_usada") or intento,
                        **({"error": row["error"]} if row.get("error") else {}),
                    }
                )
                productos.extend(row["productos"])
            q_usada = next((f["q"] for f in fuentes if f.get("q")), intento)
            if productos:
                break
    productos.sort(key=lambda p: p["precio"])
    return {
        "q": q,
        "q_usada": q_usada,
        "fuente": "vtex_publico",
        "productos": productos,
        "fuentes": fuentes,
    }
