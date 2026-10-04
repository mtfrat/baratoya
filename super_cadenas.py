"""Súper: catálogo VTEX público de Mas Online (ex Chango Más). $0.

Solo entra una cadena si el JSON trae commertialOffer.Price numérico > 0.
No hay scrapers pagos, proxies ni Mercado Libre.
"""
from __future__ import annotations

from typing import Any

import httpx

# Verificado 2026-10-03 ~20:45 ART desde este servidor:
# GET https://www.masonline.com.ar/api/catalog_system/pub/products/search?ft=yerba&_from=0&_to=4
# HTTP 206, Yerba Mate Taragui 500g, Price 3609.0.
STORES: list[dict[str, str]] = [
    {
        "id": "masonline",
        "nombre": "Mas Online",
        "origin": "https://www.masonline.com.ar",
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
                "fuente_item": "mas_online_vtex",
            }
        )
    return out


async def _one(client: httpx.AsyncClient, store: dict[str, str], q: str) -> dict[str, Any]:
    url = store["origin"].rstrip("/") + VTEX_PATH
    try:
        r = await client.get(
            url,
            params={"ft": q, "_from": 0, "_to": 4},
            headers={"Accept": "application/json", "User-Agent": UA},
        )
    except Exception as e:
        return {
            "tienda": store["nombre"],
            "tienda_id": store["id"],
            "http": 0,
            "ok": False,
            "error": str(e),
            "productos": [],
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
    }
    if parse_error:
        row["error"] = parse_error
    elif r.status_code not in (200, 206):
        row["error"] = f"HTTP {r.status_code}"
    return row


async def buscar_super(q: str) -> dict[str, Any]:
    """Catálogos públicos de súper ya verificados. Hoy: solo Mas Online."""
    productos: list[dict[str, Any]] = []
    fuentes: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        for store in STORES:
            row = await _one(client, store, q)
            fuentes.append(
                {
                    "tienda": row["tienda"],
                    "tienda_id": row["tienda_id"],
                    "http": row["http"],
                    "ok": row["ok"],
                    "n": len(row["productos"]),
                    **({"error": row["error"]} if row.get("error") else {}),
                }
            )
            productos.extend(row["productos"])
    productos.sort(key=lambda p: p["precio"])
    return {
        "q": q,
        "fuente": "vtex_publico",
        "productos": productos,
        "fuentes": fuentes,
    }
