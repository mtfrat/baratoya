"""Súper: catálogos VTEX públicos. $0.

Solo entra un producto si hay un precio de venta numérico > 0 (VTEX Price,
el número de ahora). ListPrice o el tachado es contexto, no el precio que se compara.
No hay scrapers pagos ni proxies. Makro, Mercado Libre y Maxiconsumo no entran como precio.
"""
from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote

import httpx

from promos_hoy import aplicar_oferta

# Verificado 2026-10-03 ~21:56 ART desde este servidor (Price numérico > 0, sin proxy):
# Mas Online, Día, Carrefour, Jumbo, Disco, Vea, Cordiez, Toledo y Josimar.
# Mismo path /api/catalog_system/pub/products/search. Coto sigue en HTML, no entra.
STORES: list[dict[str, str]] = [
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
    {
        "id": "masonline",
        "nombre": "Mas Online",
        "origin": "https://www.masonline.com.ar",
        "fuente": "mas_online_vtex",
    },
    {
        "id": "jumbo",
        "nombre": "Jumbo",
        "origin": "https://www.jumbo.com.ar",
        "fuente": "jumbo_vtex",
    },
    {
        "id": "disco",
        "nombre": "Disco",
        "origin": "https://www.disco.com.ar",
        "fuente": "disco_vtex",
    },
    {
        "id": "vea",
        "nombre": "Vea",
        "origin": "https://www.vea.com.ar",
        "fuente": "vea_vtex",
    },
    {
        "id": "cordiez",
        "nombre": "Cordiez",
        "origin": "https://www.cordiez.com.ar",
        "fuente": "cordiez_vtex",
    },
    {
        "id": "toledo",
        "nombre": "Toledo",
        "origin": "https://www.toledodigital.com.ar",
        "fuente": "toledo_vtex",
    },
    {
        "id": "josimar",
        "nombre": "Josimar",
        "origin": "https://www.josimar.com.ar",
        "fuente": "josimar_vtex",
    },
    {
        "id": "abastecedor",
        "nombre": "El Abastecedor",
        "origin": "https://www.abastecedor.com.ar",
        "fuente": "abastecedor_vtex",
    },
    {
        "id": "comodin",
        "nombre": "Comodín",
        "origin": "https://www.comodinencasa.com.ar",
        "fuente": "comodin_vtex",
    },
]

VTEX_PATH = "/api/catalog_system/pub/products/search"
# Una página por cadena alcanza para filtrar el mismo producto. No es un barrido.
_PAGE_TO = 29
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_STOP_NOMBRE = {
    "la", "el", "los", "las", "de", "del", "y", "e", "o", "u",
    "para", "por", "en", "al", "un", "una", "lo", "a", "x",
}
_TIENDA_ORDEN = {s["id"]: i for i, s in enumerate(STORES)}
_TIENDA_ORDEN["precios_claros"] = len(_TIENDA_ORDEN)
_TIENDA_ORDEN["laanonima"] = len(_TIENDA_ORDEN)
_TIENDA_ORDEN["supermami"] = len(_TIENDA_ORDEN)
_TIENDA_ORDEN["cotodigital"] = len(_TIENDA_ORDEN)

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SIZE_RE = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)?)\s*(kg|kilos?|gramos?|grs?|g|mls?|cc|litros?|lts?|l)\b",
    re.IGNORECASE,
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
    # Sin stock no es el precio que se paga ahora. Jumbo publica Price en ítems con cantidad 0.
    qty = offer.get("AvailableQuantity")
    flag = offer.get("IsAvailable")
    if flag is False or qty == 0:
        return float(price), False
    return float(price), True


def _lista_y_badge(precio: float, lista: float | None) -> tuple[float | None, int | None]:
    """El tachado y el % de la tienda son contexto. No reemplazan el precio de venta."""
    if lista is None or lista <= precio:
        return None, None
    # Cencosud a veces manda un ListPrice de cientos de miles junto a un Price real.
    # Eso no es el tachado de la góndola: no se muestra ni se usa para ordenar.
    if lista > precio * 3:
        return None, None
    pct = (1 - precio / lista) * 100
    redondo = int(round(pct))
    badge = redondo if redondo > 0 and abs(pct - redondo) <= 0.45 else None
    return float(lista), badge


def _lista_vtex(product: dict[str, Any], precio: float) -> tuple[float | None, int | None]:
    items = product.get("items") or []
    if not items or not isinstance(items[0], dict):
        return None, None
    sellers = items[0].get("sellers") or []
    if not sellers or not isinstance(sellers[0], dict):
        return None, None
    offer = sellers[0].get("commertialOffer") or {}
    lista = offer.get("ListPrice")
    if isinstance(lista, bool) or not isinstance(lista, (int, float)):
        return None, None
    return _lista_y_badge(precio, float(lista))


def _ean_item(product: dict[str, Any]) -> str:
    items = product.get("items") or []
    if not items or not isinstance(items[0], dict):
        return ""
    raw = items[0].get("ean")
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits if len(digits) >= 8 else ""


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


def _imagen_publicada(p: dict[str, Any]) -> str:
    url = p.get("imagen")
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
        if price is None or not available:
            continue
        name = product.get("productName") or product.get("productTitle")
        if not name:
            continue
        lista, badge = _lista_vtex(product, price)
        out.append(
            {
                "tienda": store["nombre"],
                "tienda_id": store["id"],
                "nombre": name,
                "marca": product.get("brand") or "",
                "precio": price,
                "precio_lista": lista,
                "descuento_tienda": badge,
                "url": product.get("link") or "",
                "disponible": available,
                "fuente_item": store["fuente"],
                "ean": _ean_item(product),
                "imagen": _imagen_vtex(product),
            }
        )
    return out


def _limpia(s: str) -> str:
    return " ".join((s or "").split())


def _sin_puntuacion(s: str) -> str:
    """VTEX responde 400 si ft trae '+' o signos. El espacio va como %20, no como '+'."""
    return _limpia(_PUNCT.sub(" ", s or "").replace("_", " "))


def _ft_url(origin: str, q: str) -> str:
    # quote (no quote_plus): un '+' en ft hace que Mas Online conteste
    # "Bad Request! Scripts are not allowed!".
    return (
        origin.rstrip("/")
        + VTEX_PATH
        + "?ft="
        + quote(q, safe="")
        + "&_from=0&_to="
        + str(_PAGE_TO)
    )


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



def _dinero_txt(raw: str) -> float | None:
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
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        n = float(s)
    except ValueError:
        return None
    return n if n > 0 else None


def _row_vacio(store: dict[str, str], http: int, error: str, q: str) -> dict[str, Any]:
    return {
        "tienda": store["nombre"],
        "tienda_id": store["id"],
        "http": http,
        "ok": False,
        "error": error,
        "productos": [],
        "q_usada": q,
    }


def _parse_la_anonima(html: str) -> list[dict[str, Any]]:
    """Precio de ahora en data-precio. El código interno no es un EAN.

    La categoría trae un '>' adentro del atributo, así que no se puede cortar el tag con [^>].
    """
    out = []
    vistos = set()
    for m in re.finditer(r'href="([^"]*?/art_\d+/)"', html or ""):
        href = m.group(1)
        if href in vistos:
            continue
        ventana = (html or "")[m.start(): m.start() + 1600]
        nombre_m = re.search(r'data-nombre\s*=\s*"([^"]+)"', ventana)
        marca_m = re.search(r'data-marca\s*=\s*"([^"]*)"', ventana)
        precio_m = re.search(r'data-precio\s*=\s*"([\d.]+)"', ventana)
        if not nombre_m or not precio_m:
            continue
        nombre = nombre_m.group(1)
        marca = marca_m.group(1) if marca_m else ""
        raw = precio_m.group(1)
        try:
            precio = float(raw)
        except ValueError:
            continue
        if precio <= 0:
            continue
        vistos.add(href)
        anterior = None
        ant = re.search(r'data-precio_anterior\s*=\s*"([\d.]+)"', ventana)
        if ant:
            try:
                anterior = float(ant.group(1))
            except ValueError:
                anterior = None
        lista, badge = _lista_y_badge(precio, anterior)
        url = href if href.startswith("http") else "https://www.laanonima.com.ar" + href
        out.append(
            {
                "tienda": "La Anónima",
                "tienda_id": "laanonima",
                "nombre": nombre,
                "marca": "" if marca in {"", "NA"} else marca,
                "precio": precio,
                "precio_lista": lista,
                "descuento_tienda": badge,
                "url": url,
                "disponible": True,
                "fuente_item": "la_anonima_html",
                "ean": "",
                "imagen": "",
            }
        )
    return out


def _parse_super_mami(html: str) -> list[dict[str, Any]]:
    out = []
    partes = (html or "").split('class="precio-unidad"')
    for parte in partes[1:]:
        precio_m = re.search(r"\$\s*([\d.,]+)", parte[:500])
        titulo_m = re.search(r'title="([^"]+)"', parte[:1500])
        if not precio_m or not titulo_m:
            continue
        precio = _dinero_txt(precio_m.group(1))
        if not precio:
            continue
        # el link del producto está antes de este precio
        out.append(
            {
                "tienda": "Super Mami",
                "tienda_id": "supermami",
                "nombre": titulo_m.group(1),
                "marca": "",
                "precio": precio,
                "precio_lista": None,
                "descuento_tienda": None,
                "url": "",
                "disponible": True,
                "fuente_item": "super_mami_html",
                "ean": "",
                "imagen": "",
                "_bloque": parte,
            }
        )
    # links: cada tile trae /super/producto/ antes del precio. Rebuscar en el html completo por título.
    limpio = []
    for item in out:
        item.pop("_bloque", None)
        titulo = item["nombre"]
        pos = (html or "").find(titulo)
        href = ""
        if pos > 0:
            ventana = html[max(0, pos - 2500):pos]
            links = re.findall(r'href="(/super/producto/[^"]+)"', ventana)
            if links:
                href = "https://www.supermami.com.ar" + links[-1].split(";")[0]
        item["url"] = href
        limpio.append(item)
    # dedupe
    vistos = set()
    final = []
    for item in limpio:
        if item["nombre"] in vistos:
            continue
        vistos.add(item["nombre"])
        final.append(item)
    return final


def _parse_coto(html: str) -> list[dict[str, Any]]:
    """HTML de static.cotodigital3. El shell de www.coto.com.ar no trae precio."""
    if not html or "app-root" in html[:2000] and "cotodigital3" not in html[:500]:
        return []
    out = []
    # nombre (codigo) y un precio $3.349,00 cercano
    for m in re.finditer(
        r"([A-Za-zÁÉÍÓÚáéíóúÑñ0-9][^<\n]{8,80}?)\s*\((\d{5,8})\)[\s\S]{0,240}?\$\s*([\d.]+,\d{2})",
        html,
    ):
        nombre = " ".join(m.group(1).split())
        if len(nombre) < 8 or "Precio" in nombre:
            continue
        precio = _dinero_txt(m.group(3))
        if not precio:
            continue
        out.append(
            {
                "tienda": "Coto Digital",
                "tienda_id": "cotodigital",
                "nombre": nombre,
                "marca": "",
                "precio": precio,
                "precio_lista": None,
                "descuento_tienda": None,
                "url": "",
                "disponible": True,
                "fuente_item": "coto_digital_html",
                "ean": "",
                "imagen": "",
            }
        )
        if len(out) >= 24:
            break
    return out


_LA_ANONIMA = {
    "id": "laanonima",
    "nombre": "La Anónima",
    "fuente": "la_anonima_html",
}
_SUPER_MAMI = {
    "id": "supermami",
    "nombre": "Super Mami",
    "fuente": "super_mami_html",
}
_COTO = {
    "id": "cotodigital",
    "nombre": "Coto Digital",
    "fuente": "coto_digital_html",
}


async def _fetch_la_anonima(client: httpx.AsyncClient, q: str) -> dict[str, Any]:
    url = "https://www.laanonima.com.ar/buscar/" + quote(q, safe="")
    try:
        r = await client.get(url, headers={"Accept": "text/html", "User-Agent": UA})
    except Exception as e:
        return _row_vacio(_LA_ANONIMA, 0, str(e), q)
    productos = _parse_la_anonima(r.text or "") if r.status_code == 200 else []
    row = {
        "tienda": "La Anónima",
        "tienda_id": "laanonima",
        "http": r.status_code,
        "ok": bool(productos),
        "productos": productos,
        "q_usada": q,
    }
    if r.status_code != 200:
        row["error"] = f"HTTP {r.status_code}"
    elif not productos:
        row["error"] = "HTTP 200 sin precio en el listado"
    return row


async def _fetch_super_mami(client: httpx.AsyncClient, q: str) -> dict[str, Any]:
    url = (
        "https://www.supermami.com.ar/super/categoria?_dyncharset=utf-8&Dy=1&Nty=1&Ntk=All&No=0&Ntt="
        + quote(q, safe="")
    )
    try:
        r = await client.get(url, headers={"Accept": "text/html", "User-Agent": UA})
    except Exception as e:
        return _row_vacio(_SUPER_MAMI, 0, str(e), q)
    productos = _parse_super_mami(r.text or "") if r.status_code == 200 else []
    row = {
        "tienda": "Super Mami",
        "tienda_id": "supermami",
        "http": r.status_code,
        "ok": bool(productos),
        "productos": productos,
        "q_usada": q,
    }
    if r.status_code != 200:
        row["error"] = f"HTTP {r.status_code}"
    elif not productos:
        row["error"] = "HTTP 200 sin precio"
    return row


async def _fetch_coto(client: httpx.AsyncClient, q: str) -> dict[str, Any]:
    # Sin seguir el 301 a www.coto.com.ar: esa página es el shell y no trae precio.
    url = (
        "https://static.cotodigital3.com.ar/sitios/cdigi/browse?_dyncharset=utf-8&Dy=1&Ntt="
        + quote(q, safe="")
        + "&Nty=1&Ntk=All&Nrpp=12"
    )
    try:
        r = await client.get(
            url,
            headers={"Accept": "text/html", "User-Agent": UA},
            follow_redirects=False,
        )
    except Exception as e:
        return _row_vacio(_COTO, 0, str(e), q)
    if r.status_code in {301, 302, 303, 307, 308}:
        return _row_vacio(_COTO, r.status_code, "Redirige al shell sin precio", q)
    productos = _parse_coto(r.text or "") if r.status_code == 200 else []
    row = {
        "tienda": "Coto Digital",
        "tienda_id": "cotodigital",
        "http": r.status_code,
        "ok": bool(productos),
        "productos": productos,
        "q_usada": q,
    }
    if r.status_code != 200:
        row["error"] = f"HTTP {r.status_code}"
    elif not productos:
        row["error"] = "HTTP 200 sin precio"
    return row


async def buscar_super(q: str, consultas: list[str] | None = None) -> dict[str, Any]:
    """Catálogos públicos ya verificados. Si la frase no trae un precio, prueba una más corta.

    Una cadena que no devuelve Price > 0 queda con ok=false y cero productos. No se inventa.
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
            rows = await asyncio.gather(
                *[_one(client, store, intento) for store in STORES],
                _fetch_la_anonima(client, intento),
                _fetch_super_mami(client, intento),
                _fetch_coto(client, intento),
            )
            fuentes = []
            productos = []
            for row in rows:
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
    return {
        "q": q,
        "q_usada": q_usada,
        "fuente": "vtex_publico",
        "productos": productos,
        "fuentes": fuentes,
    }


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.casefold()


def _preparar(s: str) -> str:
    s = _fold(s)
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)
    s = re.sub(r"[^\w\s.]", " ", s, flags=re.UNICODE)
    return " ".join(s.split())


def _unit_base(num: str, unit: str) -> tuple[str, int | float] | None:
    unit = unit.casefold()
    try:
        n = float(num)
    except ValueError:
        return None
    if unit in {"kg", "kilo", "kilos"}:
        kind, base = "g", n * 1000
    elif unit in {"g", "gr", "grs", "gramo", "gramos"}:
        kind, base = "g", n
    elif unit in {"l", "lt", "lts", "litro", "litros"}:
        kind, base = "ml", n * 1000
    elif unit in {"ml", "mls", "cc"}:
        kind, base = "ml", n
    else:
        return None
    if base <= 0:
        return None
    if abs(base - round(base)) < 1e-6:
        base = int(round(base))
    return kind, base


def _sizes_in(text: str) -> list[tuple[str, int | float]]:
    found: list[tuple[str, int | float]] = []
    for num, unit in _SIZE_RE.findall(_preparar(text)):
        size = _unit_base(num, unit)
        if size:
            found.append(size)
    return found


def _size_token(size: tuple[str, int | float]) -> str:
    kind, amount = size
    if kind == "g":
        if isinstance(amount, int) and amount >= 1000 and amount % 1000 == 0:
            return f"{amount // 1000}kg"
        return f"{_num_txt(amount)}g"
    if isinstance(amount, int) and amount >= 1000 and amount % 1000 == 0:
        return f"{amount // 1000}l"
    return f"{_num_txt(amount)}ml"


def _num_txt(amount: int | float) -> str:
    if isinstance(amount, int) or (isinstance(amount, float) and amount == int(amount)):
        return str(int(amount))
    return str(amount).rstrip("0").rstrip(".")


def tamano_texto(size: tuple[str, int | float] | None) -> str:
    if not size:
        return ""
    kind, amount = size
    n = _num_txt(amount)
    if kind == "g":
        if isinstance(amount, int) and amount >= 1000 and amount % 1000 == 0:
            return f"{amount // 1000} kg"
        return f"{n} g"
    if isinstance(amount, int) and amount >= 1000 and amount % 1000 == 0:
        return f"{amount // 1000} L"
    return f"{n} ml"


def _tokens(text: str) -> list[str]:
    raw = _preparar(text).split()
    out: list[str] = []
    i = 0
    while i < len(raw):
        t = raw[i].strip(".")
        if not t:
            i += 1
            continue
        m = re.fullmatch(r"(\d+(?:\.\d+)?)([a-z]+)", t)
        if m:
            size = _unit_base(m.group(1), m.group(2))
            if size:
                out.append(_size_token(size))
                i += 1
                continue
        if re.fullmatch(r"\d+(?:\.\d+)?", t) and i + 1 < len(raw):
            size = _unit_base(t, raw[i + 1].strip("."))
            if size:
                out.append(_size_token(size))
                i += 2
                continue
            if t.endswith(".0"):
                t = str(int(float(t)))
            elif "." not in t:
                t = str(int(t))
        if t in _STOP_NOMBRE or (t.isalpha() and len(t) == 1):
            i += 1
            continue
        out.append(t)
        i += 1
    return out


def _lev(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 1:
        return 2
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (ca != cb)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def _size_amount_hits(token: str, amount: int | float) -> bool:
    if not re.fullmatch(r"\d+", token):
        return False
    return int(token) == amount


def _token_hit(needle: str, hay: list[str], fuzzy: bool) -> bool:
    if needle in hay:
        return True
    if re.fullmatch(r"\d+", needle):
        n = int(needle)
        for h in hay:
            m = re.fullmatch(r"(\d+)(g|kg|ml|l)", h)
            if not m:
                continue
            amount = int(m.group(1))
            unit = m.group(2)
            if unit == "kg":
                amount *= 1000
            elif unit == "l":
                amount *= 1000
            if amount == n and unit in {"g", "kg", "ml", "l"}:
                # 500 hits 500 g or 500 ml, not 1 kg.
                if unit in {"kg", "l"} and int(m.group(1)) != n:
                    continue
                if unit in {"g", "ml"} and amount == n:
                    return True
                if unit in {"kg", "l"} and amount == n:
                    return True
        return False
    if not fuzzy or not needle.isalpha():
        return False
    for h in hay:
        if not h.isalpha():
            continue
        if len(needle) >= 8 and abs(len(needle) - len(h)) <= 1 and _lev(needle, h) <= 1:
            return True
        if len(needle) >= 6 and h.startswith(needle) and 0 < len(h) - len(needle) <= 2:
            return True
    return False


def _covers(q_tokens: list[str], hay: list[str], fuzzy: bool) -> bool:
    if not q_tokens:
        return True
    return all(_token_hit(t, hay, fuzzy) for t in q_tokens)


def _extras(name_tokens: list[str], q_tokens: list[str]) -> int:
    return sum(1 for t in name_tokens if not any(_token_hit(q, [t], fuzzy=False) for q in q_tokens))


def _consulta_size(q: str) -> tuple[str, tuple[str, int | float] | int] | None:
    size, pack, ambiguo = _medida_texto(q)
    if ambiguo:
        return None
    if size:
        return ("exact", _balde(size))
    bare = [int(t) for t in _tokens(q) if re.fullmatch(r"\d+", t)]
    if pack and int(pack[0]) in bare:
        bare = [n for n in bare if n != int(pack[0])]
    if not bare:
        return None
    return ("either", bare[-1])


def _size_ok(size: tuple[str, int | float] | None, spec) -> bool:
    """Mismo balde: 2% o la misma etiqueta (1 kg, 1kg, 1000 g). 500 g no es 1 kg."""
    if spec is None:
        return True
    if size is None:
        return False
    kind, mode = spec
    if kind == "exact":
        return _mismo_balde(size, mode)
    amount = float(mode)
    skind, samount = size
    if skind not in {"g", "ml"} or amount <= 0 or float(samount) <= 0:
        return False
    return abs(float(samount) - amount) / max(float(samount), amount) <= 0.02


def _precio_item(p: dict[str, Any]) -> float | None:
    if p.get("tienda"):
        raw = p.get("precio")
    else:
        raw = p.get("precioMin")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    if raw <= 0:
        return None
    return float(raw)


def _ean_of(p: dict[str, Any]) -> str:
    raw = p.get("ean")
    if not raw and not p.get("tienda"):
        raw = p.get("id")
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits if len(digits) >= 8 else ""


_TIPOS_PRODUCTO = frozenset({
    "yerba", "leche", "aceite", "arroz", "azucar", "harina", "fideos",
    "cafe", "te", "agua", "gaseosa", "cerveza", "vino", "queso",
    "manteca", "yogurt", "polenta",
})
_MARCA_INGREDIENTE = frozenset({"con", "sabor", "saborizada"})
# Otro producto que nombra al tipo como ingrediente o como destino: "Flan de leche",
# "Dulce de leche", "Hervidor de leche", "Postre sabor leche". Si aparece antes del tipo,
# el producto es eso y no el tipo.
_OTRO_PRODUCTO = frozenset({
    "flan", "flanes", "postre", "postres", "hervidor", "batidor", "espumador",
    "alfajor", "alfajores", "chocolatada", "chocolate", "chocolates", "chocolatin",
    "tableta", "bombon", "bombones", "oblea", "obleas", "galletitas", "galletas",
    "galletita", "galleta", "donuts", "donas", "alimento", "torta", "tortas", "budin", "bizcochuelo", "helado", "helados",
    "mousse", "dulce", "crema", "licor", "bebida", "acondicionador", "shampoo",
    "jabon", "jarra", "taza", "vaso", "mamadera", "cafetera", "pava", "bandeja",
    "molde", "batidora", "rallador", "tapa", "pastillas", "caramelos", "barra",
    "barrita", "cereal", "cereales", "muffin", "muffins", "bano", "magdalena",
    "magdalenas", "pepitas", "rellena", "relleno",
})
# Variantes del tipo que no son lo que se pide con la palabra sola ("leche" no es
# "leche chocolatada"). Bajan en el orden salvo que la consulta las nombre.
_VARIANTE_BAJA = frozenset({
    "chocolatada", "chocoltada", "condensada", "fermentada", "saborizada", "cacao", "frutilla",
    "vainilla", "infantil", "modificada", "repostero", "repostera",
})
_UNIT_SRC = r"kilos?|kg|gramos?|grs?|mls?|cc|litros?|lts?|ml|g|l"
_PACK_X_SIZE_RE = re.compile(
    rf"(?<!\d)(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*({_UNIT_SRC})\b",
    re.IGNORECASE,
)
_PACK_WORD_RE = re.compile(r"\bpack\s*x\s*(\d+)\b", re.IGNORECASE)
_PACK_UN_RE = re.compile(
    r"(?<!\d)(\d+)\s*(?:unidades|unidad|un|u)\b",
    re.IGNORECASE,
)
_PACK_X_BARE_RE = re.compile(r"(?<!\d)x\s*(\d+)\b", re.IGNORECASE)
_PUM_NO_DISPONIBLE = "precio por kg/L no disponible"


def _marca_norm(p: dict[str, Any]) -> str:
    """Marca en mayusculas, sin acentos. Vacia no se inventa con la primera palabra."""
    raw = p.get("marca")
    if raw is None or not str(raw).strip():
        raw = p.get("brand") or ""
    s = unicodedata.normalize("NFKD", str(raw))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.upper().split())


def _tipo_en(text: str) -> str:
    """Sustantivo de cabeza. con/sabor/saborizada en los dos tokens previos lo vuelven ingrediente.

    Si antes del tipo aparece otro producto (flan, postre, dulce, hervidor...), el sustantivo
    de cabeza es ese: "Flan de leche" es flan, "Dulce de leche" es dulce.
    """
    tokens = [t.strip(".") for t in _preparar(text).split() if t.strip(".")]
    for i, token in enumerate(tokens):
        if token not in _TIPOS_PRODUCTO and token not in _OTRO_PRODUCTO:
            continue
        prev = tokens[max(0, i - 2):i]
        if any(p in _MARCA_INGREDIENTE for p in prev):
            continue
        return token
    return ""


def _tipo_de(p: dict[str, Any]) -> str:
    nombre = str(p.get("nombre") or p.get("descripcion") or "")
    pres = str(p.get("presentacion") or "")
    return _tipo_en(f"{nombre} {pres}")


def _balde(size: tuple[str, int | float] | None) -> tuple[str, int | float] | None:
    if not size:
        return None
    kind, amount = size
    if isinstance(amount, float) and abs(amount - round(amount)) < 1e-6:
        amount = int(round(amount))
    return kind, amount


def _etiqueta_tamano(size: tuple[str, int | float] | None) -> str:
    size = _balde(size)
    if not size:
        return ""
    return _size_token(size)


def _mismo_balde(
    a: tuple[str, int | float] | None,
    b: tuple[str, int | float] | None,
) -> bool:
    """Mismo balde si la etiqueta normalizada coincide o la diferencia es de hasta 2%."""
    if a is None or b is None:
        return a is None and b is None
    if _etiqueta_tamano(a) and _etiqueta_tamano(a) == _etiqueta_tamano(b):
        return True
    if a[0] != b[0]:
        return False
    fa, fb = float(a[1]), float(b[1])
    if fa <= 0 or fb <= 0:
        return False
    return abs(fa - fb) / max(fa, fb) <= 0.02


def _recortar(text: str, start: int, end: int) -> str:
    return " ".join((text[:start] + " " + text[end:]).split())


def _sacar_pack(text: str) -> tuple[tuple[int, tuple[str, int | float] | None] | None, str]:
    """Multipack: 6 x 1 L, pack x3, 6 un, x 3. La unidad suelta no es pack."""
    raw = _preparar(text)
    m = _PACK_X_SIZE_RE.search(raw)
    if m and int(m.group(1)) >= 2:
        unit = _unit_base(m.group(2), m.group(3))
        if unit:
            return (int(m.group(1)), _balde(unit)), _recortar(raw, m.start(), m.end())
    m = _PACK_WORD_RE.search(raw)
    if m and int(m.group(1)) >= 2:
        return (int(m.group(1)), None), _recortar(raw, m.start(), m.end())
    m = _PACK_UN_RE.search(raw)
    if m and int(m.group(1)) >= 2:
        return (int(m.group(1)), None), _recortar(raw, m.start(), m.end())
    m = _PACK_X_BARE_RE.search(raw)
    if m and int(m.group(1)) >= 2 and not re.search(r"\d\s*$", raw[:m.start()]):
        after = raw[m.end():]
        # "x 500 g" / "x 1 kg" es gramaje, no multipack ("pack x6", "12 un").
        if re.match(rf"\s*({_UNIT_SRC})\b", after, re.IGNORECASE):
            return None, raw
        return (int(m.group(1)), None), _recortar(raw, m.start(), m.end())
    return None, raw


def _total_pack(pack: tuple[int, tuple[str, int | float] | None]) -> tuple[str, int | float] | None:
    if not pack or pack[1] is None:
        return None
    kind, amount = pack[1]
    total = float(amount) * int(pack[0])
    if abs(total - round(total)) < 1e-6:
        total = int(round(total))
    return kind, total


def _medida_texto(text: str) -> tuple[
    tuple[str, int | float] | None,
    tuple[int, tuple[str, int | float] | None] | None,
    bool,
]:
    """Size suelto, pack y si hubo medidas que no se pueden decidir."""
    if not str(text or "").strip():
        return None, None, False
    pack, rest = _sacar_pack(text)
    sizes = [_balde(s) for s in _sizes_in(rest)]
    sizes = [s for s in sizes if s]
    if pack and pack[1] is not None:
        if not sizes:
            return pack[1], pack, False
        if all(_mismo_balde(s, pack[1]) or _mismo_balde(s, _total_pack(pack)) for s in sizes):
            return pack[1], pack, False
        return None, (pack[0], None), True
    if not sizes:
        return None, pack, False
    if all(_mismo_balde(s, sizes[0]) for s in sizes[1:]):
        return sizes[0], pack, False
    return None, pack, True


def _elegir_pack(primero, segundo):
    if primero and primero[1] is not None:
        return primero
    if segundo and segundo[1] is not None:
        return segundo
    return primero or segundo


def _medida_de(
    p: dict[str, Any],
) -> tuple[tuple[str, int | float] | None, tuple[int, tuple[str, int | float] | None] | None]:
    """Presentacion manda. Si hay varias medidas y no se puede decidir, contenido desconocido."""
    nombre = str(p.get("nombre") or p.get("descripcion") or "")
    pres = str(p.get("presentacion") or "")
    sp, pp, ap = _medida_texto(pres) if pres.strip() else (None, None, False)
    sn, pn, an = _medida_texto(nombre) if nombre.strip() else (None, None, False)
    pack = _elegir_pack(pp, pn)
    if pres.strip() and (sp is not None or ap):
        size = None if ap else sp
    elif an:
        size = None
    else:
        size = sn
    if pack and pack[1] is not None:
        if size is not None and not (
            _mismo_balde(size, pack[1]) or _mismo_balde(size, _total_pack(pack))
        ):
            return None, (int(pack[0]), None)
        return _balde(pack[1]), (int(pack[0]), _balde(pack[1]))
    return _balde(size), pack


def _item_size(p: dict[str, Any]) -> tuple[str, int | float] | None:
    return _medida_de(p)[0]


def _pack_id(pack: tuple[int, tuple[str, int | float] | None] | None) -> tuple:
    if not pack:
        return ("unit",)
    return ("pack", int(pack[0]))


def _pum_fila(
    precio: float,
    size: tuple[str, int | float] | None,
    pack: tuple[int, tuple[str, int | float] | None] | None,
) -> tuple[float | None, str, str]:
    """ARS/kg o ARS/L solo con contenido neto conocido. El pack sin gramos o ml no se inventa."""
    if pack and pack[1] is None:
        return None, "", _PUM_NO_DISPONIBLE
    if pack and pack[1] is not None:
        pum, unidad = _pum(precio, _total_pack(pack))
        if pum is None:
            return None, "", _PUM_NO_DISPONIBLE
        return pum, unidad, ""
    pum, unidad = _pum(precio, size)
    return pum, unidad, ""


def _tamano_fila(
    size: tuple[str, int | float] | None,
    pack: tuple[int, tuple[str, int | float] | None] | None,
) -> str:
    if pack and pack[1] is not None:
        return f"{int(pack[0])} x {tamano_texto(pack[1])}"
    base = tamano_texto(size)
    if pack:
        extra = f"pack x{int(pack[0])}"
        return f"{extra}, {base}" if base else extra
    return base


def _hay(p: dict[str, Any]) -> list[str]:
    return _tokens(
        " ".join(str(p.get(k) or "") for k in ("nombre", "marca", "presentacion"))
    )


def _pum(precio: float, size: tuple[str, int | float] | None) -> tuple[float | None, str]:
    """Precio por kg o por L a partir del precio de góndola y el tamaño declarado. Nada más."""
    if not size:
        return None, ""
    kind, amount = size
    base = float(amount) / 1000.0
    if base <= 0:
        return None, ""
    if kind == "g":
        return precio / base, "kg"
    if kind == "ml":
        return precio / base, "L"
    return None, ""


def _cabeza(nombre: str, q_tokens: list[str]) -> int:
    """1 si el titulo es del tipo pedido y arranca con el sustantivo de la consulta."""
    if not q_tokens:
        return 0
    q_tipo = _tipo_en(" ".join(q_tokens))
    if q_tipo and _tipo_en(nombre) != q_tipo:
        return 0
    # La primera palabra del titulo, sin sacar la marca: "Bon o Bon Leche" es un bombon
    # aunque la marca sea "Bon o Bon"; casi toda leche se publica "Leche ...".
    nts = _tokens(nombre)
    if not nts:
        return 0
    return 1 if _token_hit(q_tokens[0], [nts[0]], fuzzy=True) else 0


def _variante(nts: list[str], q_tokens: list[str]) -> int:
    pedidas = set(q_tokens)
    return sum(1 for t in nts if t in _VARIANTE_BAJA and t not in pedidas)


def _rank(nombre: str, q_tokens: list[str]) -> tuple:
    nts = _tokens(nombre)
    exact = 1 if _covers(q_tokens, nts, fuzzy=False) else 0
    return (
        exact,
        _cabeza(nombre, q_tokens),
        -_variante(nts, q_tokens),
        -_extras(nts, q_tokens),
        SequenceMatcher(None, " ".join(q_tokens), " ".join(nts)).ratio(),
    )


def _tienda(p: dict[str, Any]) -> tuple[str, str]:
    if p.get("tienda"):
        return str(p.get("tienda")), str(p.get("tienda_id") or "")
    return "Precios Claros", "precios_claros"


def _clave(
    p: dict[str, Any],
    size: tuple[str, int | float] | None,
    pack: tuple[int, tuple[str, int | float] | None] | None = None,
) -> tuple:
    """Sin EAN compartido: marca normalizada + tipo + balde + pack.

    1 kg y 1000 g caen en el mismo balde. 500 g no. Un pack no es la unidad.
    El mismo EAN junta aunque el texto difiera; dos EAN distintos no usan esta clave para unirse.
    """
    return (_marca_norm(p), _tipo_de(p), _balde(size), _pack_id(pack))


def _claves_compatibles(a: tuple, b: tuple) -> bool:
    if a[0] != b[0] or a[1] != b[1] or a[3] != b[3]:
        return False
    return _mismo_balde(a[2], b[2])



_SINONIMOS_TITULO = {
    "despalada": ("sin", "palo"),
    "despalado": ("sin", "palo"),
}


def _tokens_parecido(nombre: str) -> set[str]:
    """Tokens para comparar titulos sin EAN. Despalada y sin palo son lo mismo. No toca la clave."""
    out: set[str] = set()
    for t in _tokens(nombre):
        out.update(_SINONIMOS_TITULO.get(t, (t,)))
    return out


def _componentes_producto(filas: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Mismo EAN se junta. Sin EAN compartido, marca + tipo + balde. Dos EAN no se pegan.

    Cada fila sin EAN se pega sola al grupo con EAN compatible cuyo titulo mas se parece.
    Recien despues las filas sin EAN que sobran se juntan entre si, y dos publicaciones
    distintas de la misma tienda no se juntan (serian dos productos).
    """
    n = len(filas)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    vistos: dict[str, int] = {}
    for i, fila in enumerate(filas):
        ean = fila["ean"]
        if not ean:
            continue
        if ean in vistos:
            union(i, vistos[ean])
        else:
            vistos[ean] = i

    toks = [_tokens_parecido(str(f["p"].get("nombre") or f["p"].get("descripcion") or "")) for f in filas]

    def _solape(a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    ean_comps: dict[int, list[int]] = {}
    for i, fila in enumerate(filas):
        if fila["ean"]:
            ean_comps.setdefault(find(i), []).append(i)
    ean_refs = {
        root: Counter(filas[i]["clave"] for i in members).most_common(1)[0][0]
        for root, members in ean_comps.items()
    }

    sueltas: list[int] = []
    for i, fila in enumerate(filas):
        if fila["ean"]:
            continue
        candidatos: list[tuple[float, int, int]] = []
        for root, members in ean_comps.items():
            if not _claves_compatibles(fila["clave"], ean_refs[root]):
                continue
            score = max(_solape(toks[i], toks[j]) for j in members)
            candidatos.append((score, len(members), root))
        if not candidatos:
            sueltas.append(i)
            continue
        candidatos.sort(reverse=True)
        mejor = candidatos[0]
        if len(candidatos) > 1:
            segundo = candidatos[1]
            if mejor[0] <= 0 or (segundo[0] == mejor[0] and segundo[1] == mejor[1]):
                sueltas.append(i)
                continue
        union(mejor[2], i)

    def _tienda_fila(i: int) -> str:
        p = filas[i]["p"]
        return str(p.get("tienda_id") or ("" if p.get("tienda") else "precios_claros"))

    def _nombre_fila(i: int) -> str:
        p = filas[i]["p"]
        return " ".join(str(p.get("nombre") or p.get("descripcion") or "").casefold().split())

    for a in range(len(sueltas)):
        for b in range(a + 1, len(sueltas)):
            i, j = sueltas[a], sueltas[b]
            if not _claves_compatibles(filas[i]["clave"], filas[j]["clave"]):
                continue
            if _tienda_fila(i) == _tienda_fila(j) and _nombre_fila(i) != _nombre_fila(j):
                continue
            union(i, j)

    final: dict[int, list[dict[str, Any]]] = {}
    for i, fila in enumerate(filas):
        final.setdefault(find(i), []).append(fila)
    return list(final.values())


def _product_key(tienda_id: str, url: str, nombre: str, ean: str) -> str:
    if tienda_id == "precios_claros":
        return "pc:" + (ean or nombre)
    if url:
        return "url:" + url
    return (tienda_id or "tienda") + ":" + nombre


def agrupar_mismo_producto(
    q: str,
    productos: list[dict[str, Any]],
    leido: str = "",
    *,
    bancos_permitidos: list[str] | set[str] | None = None,
    con_promo: bool = True,
    supermercados_permitidos: list[str] | set[str] | None = None,
    hoy: date | None = None,
) -> list[dict[str, Any]]:
    """Agrupa el mismo EAN, o si no hay uno compartido, marca + tipo + balde.

    Dos EAN distintos no se juntan. 500 g no se junta con 1 kg. El pack no se junta
    con la unidad. El numero grande es el precio de gondola, nunca promo.total.
    """
    q_tokens = _tokens(q)
    q_tipo = _tipo_en(q)
    spec = _consulta_size(q)
    filas: list[dict[str, Any]] = []
    for p in productos:
        if not isinstance(p, dict):
            continue
        precio = _precio_item(p)
        if precio is None:
            continue
        size, pack = _medida_de(p)
        if not _size_ok(size, spec):
            continue
        if q_tipo in _TIPOS_PRODUCTO and _tipo_de(p) != q_tipo:
            continue
        if not _covers(q_tokens, _hay(p), fuzzy=True):
            continue
        nombre = str(p.get("nombre") or p.get("descripcion") or "").strip()
        if not nombre:
            continue
        filas.append(
            {
                "p": p,
                "size": size,
                "pack": pack,
                "clave": _clave(p, size, pack),
                "ean": _ean_of(p),
            }
        )

    built: list[dict[str, Any]] = []
    for grupo in _componentes_producto(filas):
        members = [f["p"] for f in grupo]
        best = max(members, key=lambda m: _rank(str(m.get("nombre") or ""), q_tokens))
        best_rank = _rank(str(best.get("nombre") or ""), q_tokens)
        if q_tokens and not any(_covers(q_tokens, _hay(m), fuzzy=True) for m in members):
            continue
        sizes = [f["size"] for f in grupo if f["size"]]
        size = _item_size(best) or (sizes[0] if sizes else None)
        eans = [f["ean"] for f in grupo if f["ean"]]
        ean = eans[0] if eans and all(e == eans[0] for e in eans) else ""
        packs = [f["pack"] for f in grupo if f["pack"]]
        pack = next((f["pack"] for f in grupo if f["p"] is best and f["pack"]), None)
        if pack is None and packs:
            pack = packs[0]
        built.append(
            {
                "clave": _clave(best, size, pack),
                "members": members,
                "best": best,
                "rank": best_rank,
                "size": size,
                "pack": pack,
                "ean": ean,
                "min_precio": min(_precio_item(m) or 0 for m in members),
            }
        )

    # Si dos productos distintos comparten el nombre más corto, el título usa la variante.
    for g in built:
        g["nombre"] = str(g["best"].get("nombre") or "")
        g["tok0"] = tuple(sorted(_tokens(g["nombre"])))
    for g in built:
        tok = g["tok0"]
        hermanos = [o for o in built if o is not g and o["tok0"] == tok]
        if not hermanos:
            continue
        ajenos: set[str] = set()
        for o in hermanos:
            for m in o["members"]:
                ajenos.update(_tokens(str(m.get("nombre") or "")))
        propios: set[str] = set()
        for m in g["members"]:
            propios.update(_tokens(str(m.get("nombre") or "")))
        unicos = propios - ajenos
        if not unicos:
            continue
        candidatos = [
            m
            for m in g["members"]
            if unicos.intersection(_tokens(str(m.get("nombre") or "")))
        ]
        if not candidatos:
            continue
        elegido = max(candidatos, key=lambda m: _rank(str(m.get("nombre") or ""), q_tokens))
        g["nombre"] = str(elegido.get("nombre") or g["nombre"])
        g["best"] = elegido

    # Relevancia primero (tipo pedido, sin variante, menos palabras de mas, mas cobertura); a igual, mas barato.
    built.sort(
        key=lambda g: (
            g["rank"][0],
            g["rank"][1],
            g["rank"][2],
            g["rank"][3],
            len(g["members"]),
            g["rank"][4],
            -g["min_precio"],
        ),
        reverse=True,
    )

    out: list[dict[str, Any]] = []
    for g in built:
        by_store: dict[str, dict[str, Any]] = {}
        for m in g["members"]:
            tienda, tienda_id = _tienda(m)
            precio = _precio_item(m)
            if precio is None:
                continue
            offer_size, offer_pack = _medida_de(m)
            if offer_pack and offer_pack[1] is None:
                pum, pum_unidad, pum_nota = None, "", _PUM_NO_DISPONIBLE
            elif g["size"] and offer_size and not _mismo_balde(offer_size, g["size"]):
                pum, pum_unidad, pum_nota = None, "", ""
            else:
                pum, pum_unidad, pum_nota = _pum_fila(precio, g["size"] or offer_size, offer_pack)
            nombre = str(m.get("nombre") or "")
            url = str(m.get("url") or "")
            ean = _ean_of(m) or g.get("ean") or ""
            lista = m.get("precio_lista")
            badge = m.get("descuento_tienda")
            ya_descuento = (
                isinstance(lista, (int, float))
                and not isinstance(lista, bool)
                and float(lista) > float(precio)
            ) or (
                isinstance(badge, (int, float))
                and not isinstance(badge, bool)
                and float(badge) > 0
            )
            if con_promo:
                if bancos_permitidos is not None:
                    promo = aplicar_oferta(
                        tienda_id or "",
                        nombre,
                        precio,
                        hoy=hoy,
                        ya_descuento=ya_descuento,
                        bancos_permitidos=bancos_permitidos,
                    )
                else:
                    promo = aplicar_oferta(
                        tienda_id or "",
                        nombre,
                        precio,
                        hoy=hoy,
                        ya_descuento=ya_descuento,
                    )
            else:
                promo = {"total": precio, "promo": None, "promos": []}
            row = {
                "tienda": tienda,
                "tienda_id": tienda_id or "precios_claros",
                "nombre": nombre,
                "marca": m.get("marca") or "",
                "precio": precio,
                "precio_lista": m.get("precio_lista"),
                "descuento_tienda": m.get("descuento_tienda"),
                "total": promo["total"],
                "promo": promo["promo"],
                "promos": promo["promos"],
                "pum": pum,
                "pum_unidad": pum_unidad,
                "pum_nota": pum_nota,
                "url": url,
                "ean": ean,
                "product_key": _product_key(tienda_id or "precios_claros", url, nombre, ean),
                "fuente": "precios_claros" if (tienda_id or "precios_claros") == "precios_claros" and not m.get("tienda") else "vtex",
            }
            if not m.get("tienda"):
                row["fuente"] = "precios_claros"
            prev = by_store.get(row["tienda_id"])
            if prev is None or _rank(nombre, q_tokens) > _rank(str(prev.get("nombre") or ""), q_tokens):
                by_store[row["tienda_id"]] = row
            elif _rank(nombre, q_tokens) == _rank(str(prev.get("nombre") or ""), q_tokens) and precio < prev["precio"]:
                by_store[row["tienda_id"]] = row
        ofertas = list(by_store.values())
        if not ofertas:
            continue
        # La marca es el precio que se paga ahora. Un total de promo no elige la card.
        piso = min(o["precio"] for o in ofertas)
        for o in ofertas:
            o["barato"] = o["precio"] == piso
        if supermercados_permitidos:
            favs = {s.casefold().strip() for s in supermercados_permitidos if s.strip()}
            ofertas.sort(
                key=lambda o: (
                    0 if o["tienda_id"].casefold() in favs else 1,
                    o["precio"],
                    _TIENDA_ORDEN.get(o["tienda_id"], 50),
                    o["tienda"],
                )
            )
        else:
            ofertas.sort(key=lambda o: (o["precio"], _TIENDA_ORDEN.get(o["tienda_id"], 50), o["tienda"]))
        baratos = [o["tienda"] for o in ofertas if o["barato"]]
        elegido = next(o for o in ofertas if o["barato"])
        best = g["best"]
        imagen = ""
        for candidato in (best, *g["members"]):
            imagen = _imagen_publicada(candidato)
            if imagen:
                break
        out.append(
            {
                "agrupado": True,
                "nombre": g["nombre"],
                "imagen": imagen,
                "marca": best.get("marca") or elegido.get("marca") or "",
                "ean": g.get("ean") or "",
                "tamano": _tamano_fila(g["size"], g.get("pack")),
                "ofertas": ofertas,
                "mas_barato": baratos,
                "tienda": elegido["tienda"],
                "tienda_id": elegido["tienda_id"],
                "precio": elegido["precio"],
                "url": elegido["url"],
                "pum": elegido.get("pum"),
                "pum_unidad": elegido.get("pum_unidad") or "",
                "pum_nota": elegido.get("pum_nota") or "",
                "leido": leido,
            }
        )
    return out


# Promos bancarias: solo lo que el HTML de un GET ya trae. No se resta del precio.
_PROMO_DIA = "https://diaonline.supermercadosdia.com.ar/medios-de-pago-y-promociones"
_PROMO_CARREFOUR = "https://www.carrefour.com.ar/medios-de-pago-y-promociones"
_PROMO_MAS = "https://www.masonline.com.ar/medios-de-pago-y-promociones"
_PROMO_MAS_ALT = "https://www.masonline.com.ar/promociones"
_DIAS = (
    ("monday", "lunes"),
    ("tuesday", "martes"),
    ("wednesday", "miércoles"),
    ("thursday", "jueves"),
    ("friday", "viernes"),
    ("saturday", "sábado"),
    ("sunday", "domingo"),
)
_PCT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_CUOTAS = re.compile(r"cuota|plan\s*z|\bcsi\b|\b3\s*ci\b", re.I)
_HOY_CARREFOUR = re.compile(
    r"Hoy con\s+(.+?)\s+(\d+(?:[.,]\d+)?)%\s*de descuento",
    re.I,
)


def _scripts_json(html: str) -> list[Any]:
    out: list[Any] = []
    for raw in re.findall(r"<script[^>]*>([\s\S]*?)</script>", html or ""):
        raw = raw.strip()
        if not raw or raw[0] not in "{[":
            continue
        try:
            out.append(json.loads(raw))
        except Exception:
            continue
    return out


def _pcts(text: str) -> list[str]:
    found: list[str] = []
    for raw in _PCT.findall(text or ""):
        try:
            n = float(raw.replace(",", "."))
        except ValueError:
            continue
        if n <= 0:
            continue
        label = str(int(n)) if n == int(n) else raw.replace(".", ",")
        if label not in found:
            found.append(label)
    return found


def _descuento_dia(title: str, terms: str) -> str:
    en_titulo = _pcts(title)
    if len(en_titulo) == 1:
        return en_titulo[0] + "%"
    if en_titulo or _CUOTAS.search(title or ""):
        return ""
    en_letra = _pcts(terms)
    if len(en_letra) == 1:
        return en_letra[0] + "%"
    return ""


def _dias_texto(days: dict[str, Any]) -> str:
    activos = [etiqueta for clave, etiqueta in _DIAS if days.get(clave)]
    if not activos:
        return ""
    if len(activos) == 7:
        return "todos los días"
    if len(activos) == 1:
        return activos[0]
    if len(activos) == 2:
        return f"{activos[0]} y {activos[1]}"
    return ", ".join(activos[:-1]) + " y " + activos[-1]


def _limpiar_md(s: str) -> str:
    s = (s or "").replace("**", "")
    return " ".join(s.split())


def parse_promos_dia(html: str) -> list[dict[str, str]]:
    vistos: set[tuple[str, str, str]] = set()
    items: list[dict[str, str]] = []
    for data in _scripts_json(html):
        if not isinstance(data, dict):
            continue
        for block in data.values():
            if not isinstance(block, dict):
                continue
            for bucket in ("content", "props"):
                content = block.get(bucket)
                cards = content.get("cards") if isinstance(content, dict) else None
                if not isinstance(cards, list):
                    continue
                for card in cards:
                    if not isinstance(card, dict) or card.get("active") is not True:
                        continue
                    dia = _dias_texto(card.get("daysToShow") or {})
                    bancos: list[str] = []
                    for banco in card.get("associatedBanks") or []:
                        if not isinstance(banco, dict):
                            continue
                        nombre = _limpiar_md(str(banco.get("__editorItemTitle") or ""))
                        if nombre and nombre not in bancos:
                            bancos.append(nombre)
                    titulo = _limpiar_md(str(card.get("__editorItemTitle") or ""))
                    banco_txt = ", ".join(bancos) or titulo
                    descuento = _descuento_dia(titulo, str(card.get("terms") or ""))
                    if not dia or not banco_txt or not descuento:
                        continue
                    clave = (dia, banco_txt, descuento)
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                    items.append({"dia": dia, "banco": banco_txt, "descuento": descuento})
    return items


def parse_promos_carrefour(html: str) -> list[dict[str, str]]:
    textos: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and "descuento" in node.casefold():
            textos.append(node)

    for data in _scripts_json(html):
        walk(data)
    for texto in textos:
        match = _HOY_CARREFOUR.search(_limpiar_md(texto))
        if not match:
            continue
        return [
            {
                "dia": "hoy",
                "banco": _limpiar_md(match.group(1)),
                "descuento": match.group(2).replace(".", ",") + "%",
            }
        ]
    return []


def parse_promos_mas(html: str) -> tuple[list[dict[str, str]], str]:
    """Ítems de /promociones. Cuotas y varios % sin día no se convierten en un descuento."""
    grupos: dict[str, list[str]] = {}
    for data in _scripts_json(html):
        if not isinstance(data, dict):
            continue
        for block in data.values():
            if not isinstance(block, dict):
                continue
            match = re.search(r"promo-payment-methods-item(\d+)", str(block.get("blockId") or ""))
            if not match:
                continue
            props = block.get("props") if isinstance(block.get("props"), dict) else {}
            texto = props.get("text") if isinstance(props, dict) else None
            if not isinstance(texto, str) or not texto.strip():
                continue
            limpio = _limpiar_md(texto)
            slot = grupos.setdefault(match.group(1), [])
            if limpio not in slot:
                slot.append(limpio)
    items: list[dict[str, str]] = []
    notas: list[str] = []
    vistos: set[tuple[str, str, str]] = set()
    for clave in sorted(grupos, key=int):
        lineas = grupos[clave]
        banco = ""
        descuento = ""
        dia = ""
        for linea in lineas:
            if not banco and not _PCT.search(linea) and "cuota" not in linea.casefold():
                banco = linea
            pct = _pcts(linea)
            if len(pct) == 1 and linea.strip().endswith("%") or re.fullmatch(r"\d+(?:[.,]\d+)?%", linea):
                descuento = pct[0] + "%"
            elif len(pct) > 1:
                notas.append(
                    f"{banco or 'Una tarjeta'} publica «{linea}» sin un solo descuento ni un día."
                )
            if "todos los días" in linea.casefold():
                dia = "todos los días"
        if "cuota" in " ".join(lineas).casefold() and not descuento:
            notas.append(f"{banco or 'Una tarjeta'} publica cuotas, no un descuento con día.")
            continue
        if banco and descuento and dia:
            fila = (dia, banco, descuento)
            if fila not in vistos:
                vistos.add(fila)
                items.append({"dia": dia, "banco": banco, "descuento": descuento})
    nota = " ".join(dict.fromkeys(notas))
    return items, nota


def _promo_vacio(tienda: str, url: str, nota: str, http: int = 0) -> dict[str, Any]:
    return {"tienda": tienda, "url": url, "http": http, "ok": False, "nota": nota, "items": []}


async def _get_html(client: httpx.AsyncClient, url: str) -> tuple[int, str, str]:
    try:
        response = await client.get(url, headers={"Accept": "text/html", "User-Agent": UA})
    except Exception as exc:
        return 0, "", str(exc)
    if response.status_code != 200:
        return response.status_code, "", f"HTTP {response.status_code}"
    return response.status_code, response.text or "", ""


async def buscar_promos() -> list[dict[str, Any]]:
    """Día, Carrefour y Mas Online. Un GET. Sin restar el descuento del precio de góndola."""
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        dia_http, dia_html, dia_err = await _get_html(client, _PROMO_DIA)
        car_http, car_html, car_err = await _get_html(client, _PROMO_CARREFOUR)
        mas_http, mas_html, mas_err = await _get_html(client, _PROMO_MAS)
        alt_http, alt_html, alt_err = await _get_html(client, _PROMO_MAS_ALT)

    if dia_err:
        dia = _promo_vacio("Día", _PROMO_DIA, dia_err, dia_http)
    else:
        items = parse_promos_dia(dia_html)
        dia = {
            "tienda": "Día",
            "url": _PROMO_DIA,
            "http": dia_http,
            "ok": bool(items),
            "nota": "" if items else "La página respondió y no publicó día, banco y descuento juntos.",
            "items": items,
        }
    if car_err:
        carrefour = _promo_vacio("Carrefour", _PROMO_CARREFOUR, car_err, car_http)
    else:
        items = parse_promos_carrefour(car_html)
        carrefour = {
            "tienda": "Carrefour",
            "url": _PROMO_CARREFOUR,
            "http": car_http,
            "ok": bool(items),
            "nota": "" if items else "La página respondió y no publicó día, banco y descuento juntos.",
            "items": items,
        }
    if alt_err and mas_err:
        mas = _promo_vacio("Mas Online", _PROMO_MAS, mas_err or alt_err, mas_http or alt_http)
    else:
        items, extra = parse_promos_mas(alt_html) if not alt_err else ([], "")
        nota = "medios-de-pago-y-promociones no trae día, banco y descuento."
        if alt_err:
            nota += " " + alt_err
        elif items or extra:
            nota += " Se leyó /promociones."
        if extra:
            nota += " " + extra
        mas = {
            "tienda": "Mas Online",
            "url": _PROMO_MAS_ALT if items else _PROMO_MAS,
            "http": alt_http if not alt_err else mas_http,
            "ok": bool(items),
            "nota": nota.strip(),
            "items": items,
        }
    return [dia, carrefour, mas]
