"""Electro: catálogo VTEX público más la API oficial de Mercado Libre si hay credenciales.
Sin scrapers pagos y sin HTML de Mercado Libre.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

import httpx

# Verificado 2026-10-03 desde este servidor: HTTP 206 + commertialOffer.Price numérico.
STORES: list[dict[str, str]] = [
    {"id": "fravega", "nombre": "Fravega", "origin": "https://www.fravega.com"},
    {"id": "cetrogar", "nombre": "Cetrogar", "origin": "https://www.cetrogar.com.ar"},
    {"id": "naldo", "nombre": "Naldo", "origin": "https://www.naldo.com.ar"},
    {"id": "oncity", "nombre": "On City", "origin": "https://www.oncity.com"},
]

VTEX_PATH = "/api/catalog_system/pub/products/search"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
MLA_NOTA = "no disponible desde este servidor"


# Mismo aparato con otro nombre. "heladera" trae freezers y frigobares; "freezer" no trae
# heladeras con freezer (esa la pide quien escribe heladera).
_SINONIMOS: dict[str, frozenset[str]] = {
    "heladera": frozenset({"heladera", "heladeras", "freezer", "freezers", "frigobar", "frigobares", "refrigerador", "refrigeradora", "minibar"}),
    "lavarropas": frozenset({"lavarropas", "lavasecarropas", "lavarropa"}),
    "televisor": frozenset({"televisor", "televisores", "tv", "smart", "led"}),
    "tv": frozenset({"televisor", "televisores", "tv", "smart"}),
    "aire": frozenset({"aire", "split"}),
}
_CONECTOR = frozenset({"para", "de", "p", "x", "compatible", "repuesto"})
_ACCESORIO = frozenset({
    "organizador", "organizadores", "huevera", "estante", "estantes", "bandeja", "cajon",
    "burlete", "filtro", "repuesto", "manija", "puerta", "jarra", "conservadora", "termo",
    "cubetera", "imanes", "iman", "funda", "soporte", "cable", "control", "kit", "botella",
    "contenedor", "contenedores", "recipiente", "set", "tapa", "rejilla", "termostato",
    "lampara", "ventilador", "motor", "bisagra", "plaqueta", "porta", "aparador", "mueble",
    "rack", "base", "cubre", "protector", "limpiador", "accesorio", "accesorios",
})


def _fold(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return re.findall(r"[a-z0-9]+", s)


def _familia(token: str) -> frozenset[str]:
    if token in _SINONIMOS:
        return _SINONIMOS[token]
    base = token[:-1] if token.endswith("s") and len(token) > 4 else token
    return frozenset({token, base, base + "s", base + "es"})


def relevancia(nombre: str, q: str) -> int:
    """0: el titulo es el aparato pedido. 1: lo nombra pero es otra cosa (accesorio).
    2: no lo nombra (la tienda lo trajo por parecido). No mira el precio.
    """
    q_tokens = [t for t in _fold(q) if t not in _CONECTOR]
    if not q_tokens:
        return 0
    familia = _familia(q_tokens[0])
    tokens = _fold(nombre)
    pos = next((i for i, t in enumerate(tokens) if t in familia), None)
    if pos is None:
        return 2
    antes = tokens[:pos]
    if pos == 0 or not (set(antes) & (_ACCESORIO | _CONECTOR)) and len(antes) <= 2:
        if not (pos + 1 < len(tokens) and tokens[pos + 1] in {"para", "p"}):
            return 0
    return 1


def ordenar(productos: list[dict[str, Any]], q: str) -> list[dict[str, Any]]:
    """El aparato antes que el accesorio que lo nombra; dentro de cada nivel, el mas barato."""
    rel = [relevancia(str(p.get("nombre") or ""), q) for p in productos]
    if any(r < 2 for r in rel):
        productos = [p for p, r in zip(productos, rel) if r < 2]
    return sorted(productos, key=lambda p: (relevancia(str(p.get("nombre") or ""), q), p["precio"]))


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


def _imagen_vtex(product: dict[str, Any]) -> str:
    """URL que el JSON de VTEX ya trae en items[].images[].imageUrl. No se arma otra."""
    items = product.get("items") or []
    if not isinstance(items, list):
        return ""
    for item in items:
        if not isinstance(item, dict):
            continue
        images = item.get("images") or []
        if not isinstance(images, list):
            continue
        for img in images:
            if not isinstance(img, dict):
                continue
            url = img.get("imageUrl")
            if isinstance(url, str) and url.startswith("https://"):
                return url
    return ""


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
                "imagen": _imagen_vtex(product),
            }
        )
    return out


async def _one(client: httpx.AsyncClient, store: dict[str, str], q: str) -> dict[str, Any]:
    url = store["origin"].rstrip("/") + VTEX_PATH
    try:
        r = await client.get(
            url,
            # 10 por tienda: con 5, On City devolvia solo accesorios para "heladera".
            params={"ft": q, "_from": 0, "_to": 9},
            headers={"Accept": "application/json", "User-Agent": UA},
        )
    except Exception as e:
        return {"tienda": store["nombre"], "tienda_id": store["id"], "http": 0, "ok": False, "error": str(e), "productos": []}
    productos: list[dict[str, Any]] = []
    if r.status_code in (200, 206):
        try:
            productos = _parse(store, r.json())
        except Exception:
            productos = []
    return {
        "tienda": store["nombre"],
        "tienda_id": store["id"],
        "http": r.status_code,
        "ok": bool(productos),
        "productos": productos,
    }


async def buscar_electro(q: str) -> dict[str, Any]:
    productos: list[dict[str, Any]] = []
    fuentes: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        # Secuencial a propósito: pocas tiendas, sin fan-out agresivo.
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
    try:
        from meli import buscar_meli
    except ImportError:
        from baratoya.meli import buscar_meli
    try:
        meli = await buscar_meli(q)
    except Exception as e:
        meli = {
            "tienda": "Mercado Libre",
            "tienda_id": "mla",
            "http": 0,
            "ok": False,
            "n": 0,
            "productos": [],
            "aviso": str(e),
        }
    if meli.get("omitido"):
        # Misma política que /api/buscar: sin fuente, no hay banner de fallo.
        nota_mla = "catalogo_publico_cerrado"
    else:
        rows = meli.get("productos") if isinstance(meli.get("productos"), list) else []
        if rows:
            productos.extend(rows)
        fuentes.append({k: v for k, v in meli.items() if k != "productos"})
        nota_mla = meli.get("aviso") or ("ok" if meli.get("ok") else "sin resultados")
    productos = ordenar(productos, q)
    return {
        "q": q,
        "fuente": "vtex_publico",
        "productos": productos,
        "fuentes": fuentes,
        "mla": nota_mla,
    }
