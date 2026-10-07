"""BaratoYa — comparador unificado Precios Claros (CABA por defecto). $0 APIs pagas."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

# Paquete (uvicorn baratoya.app:app desde micro-saas) o módulo suelto (Vercel carga app.py).
try:
    from baratoya.electro import buscar_electro
    from baratoya.meli import buscar_meli
    from baratoya.super_cadenas import STORES as SUPER_STORES
    from baratoya.super_cadenas import UA as VTEX_UA
    from baratoya.super_cadenas import _precio as _precio_oferta
    from baratoya.super_cadenas import agrupar_mismo_producto
    from baratoya.super_cadenas import buscar_promos
    from baratoya.super_cadenas import buscar_super
    from baratoya.promos_hoy import catalogo as catalogo_promos
    from baratoya.promos_hoy import promos_para_cadena
    from baratoya import cuentas
except ImportError:
    from electro import buscar_electro
    from meli import buscar_meli
    from super_cadenas import STORES as SUPER_STORES
    from super_cadenas import UA as VTEX_UA
    from super_cadenas import _precio as _precio_oferta
    from super_cadenas import agrupar_mismo_producto
    from super_cadenas import buscar_promos
    from super_cadenas import buscar_super
    from promos_hoy import catalogo as catalogo_promos
    from promos_hoy import promos_para_cadena
    import cuentas

BASE = os.getenv("PRECIOS_CLAROS_BASE", "https://d3e6htiiul5ek9.cloudfront.net/prod").rstrip("/")
API_KEY = os.getenv("PRECIOS_CLAROS_API_KEY", "").strip()
ENABLE_PAID = os.getenv("ENABLE_PAID_SCRAPERS", "false").lower() == "true"
ENABLE_MLA = os.getenv("ENABLE_MLA", "false").lower() == "true"
CABA_LAT, CABA_LNG = -34.6037, -58.3816
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
try:
    SNAPSHOT_DIR.mkdir(exist_ok=True)
except OSError:
    pass


def _sqlite_path() -> Path:
    """Local: data/ al lado del código. En Vercel el disco es de solo lectura salvo /tmp.

    /tmp no se comparte entre instancias y se borra. La lista y la lista de espera
    no sobreviven un restart ni otro contenedor. La búsqueda no usa esta base.
    """
    override = os.getenv("BARATOYA_DATA_DIR", "").strip()
    if override:
        dest = Path(override)
    else:
        dest = Path(__file__).parent / "data"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        probe = dest / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        dest = Path("/tmp/baratoya")
        dest.mkdir(parents=True, exist_ok=True)
    return dest / "lista_espera.sqlite"


DB_PATH = _sqlite_path()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_GA_ID_RE = re.compile(r"^G-[A-Z0-9]+$")
PLANES = {"lista", "historial", "no-se"}


def ga_measurement_id() -> str:
    """GA4 measurement id from GA_MEASUREMENT_ID. Empty or invalid → no gtag."""
    raw = os.getenv("GA_MEASUREMENT_ID", "").strip()
    return raw if _GA_ID_RE.fullmatch(raw) else ""


def _ga_context(_request: Request) -> dict[str, str]:
    return {"ga_id": ga_measurement_id()}


app = FastAPI(title="BaratoYa")
templates = Jinja2Templates(
    directory=str(Path(__file__).parent / "templates"),
    context_processors=[_ga_context],
)


def _render_admin(ctx: dict[str, Any]) -> str:
    return templates.get_template("admin.html").render({**ctx, "ga_id": ga_measurement_id()})


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


CANONICAL_HOST = "baratoya.app"
VERCEL_APP_HOSTS = frozenset({"baratoya.vercel.app"})


@app.middleware("http")
async def redirect_legacy_vercel_host(request: Request, call_next):
    """308 baratoya.vercel.app → baratoya.app (same path + query). Preview *.vercel.app untouched."""
    host = (request.headers.get("host") or "").split(":", 1)[0].lower()
    if host in VERCEL_APP_HOSTS:
        target = f"https://{CANONICAL_HOST}{request.url.path}"
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return RedirectResponse(url=target, status_code=308)
    return await call_next(request)




@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    """Una persona que cae en una ruta que no existe ve una página, no {"detail": ...}.
    /api y los clientes que piden JSON siguen recibiendo JSON."""
    accept = request.headers.get("accept") or ""
    if (
        exc.status_code == 404
        and not request.url.path.startswith("/api/")
        and "application/json" not in accept
    ):
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)
    return await http_exception_handler(request, exc)


@app.get("/static/brand-logos/{name}", include_in_schema=False)
async def brand_logo(name: str):
    """Logos de marcas para el filtro. Fallback local si Storage no responde."""
    safe = Path(name).name
    if not safe.endswith((".svg", ".png", ".webp")):
        raise StarletteHTTPException(status_code=404)
    path = STATIC_DIR / "brand-logos" / safe
    if not path.is_file():
        raise StarletteHTTPException(status_code=404)
    media = "image/svg+xml" if safe.endswith(".svg") else "image/png"
    return FileResponse(path, media_type=media)


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    return FileResponse(STATIC_DIR / "robots.txt", media_type="text/plain; charset=utf-8")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    return FileResponse(STATIC_DIR / "sitemap.xml", media_type="application/xml")


@app.get("/favicon.svg", include_in_schema=False)
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(
        STATIC_DIR / "favicon.svg",
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _headers() -> dict[str, str]:
    h = {"Accept": "application/json", "User-Agent": "BaratoYa/0.1 (research; $0)"}
    if API_KEY:
        h["x-api-key"] = API_KEY
    return h


async def pc_get(path: str, params: dict[str, Any]) -> tuple[int, Any]:
    url = f"{BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, params=params, headers=_headers())
            try:
                data = r.json()
            except Exception:
                data = {"raw": r.text[:500]}
            return r.status_code, data
    except Exception as e:
        return 0, {"error": str(e)}



def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS lista_espera (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            plan TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )"""
    )
    # Lista y alerta comparten la fila: email + product_key + precio al guardar.
    # No hay cuentas. El mail es solo la clave local.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS lista_compra (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL,
            product_key TEXT NOT NULL,
            nombre TEXT NOT NULL,
            tienda TEXT NOT NULL DEFAULT '',
            precio REAL NOT NULL,
            url TEXT NOT NULL DEFAULT '',
            fuente TEXT NOT NULL DEFAULT '',
            precio_actual REAL,
            bajo INTEGER NOT NULL DEFAULT 0,
            revisado_at TEXT,
            nota TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(email, product_key)
        )"""
    )
    return conn


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.casefold().split())


def _precio_num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None or isinstance(v, str):
        if isinstance(v, str):
            v = v.strip().replace(",", ".")
        else:
            return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or x <= 0 or x > 1_000_000_000:
        return None
    return x


def _email_ok(email: str) -> bool:
    return bool(EMAIL_RE.match(email)) and len(email) <= 200


def _item_out(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "email": row["email"],
        "product_key": row["product_key"],
        "nombre": row["nombre"],
        "tienda": row["tienda"],
        "precio_guardado": row["precio"],
        "url": row["url"],
        "fuente": row["fuente"],
        "precio_actual": row["precio_actual"],
        "bajo": bool(row["bajo"]),
        "revisado_at": row["revisado_at"],
        "nota": row["nota"],
        "created_at": row["created_at"],
    }


# Solo orígenes cuyo catálogo público ya está cableado. Sin Mercado Libre.
VTEX_ORIGINS = {
    "www.masonline.com.ar": "https://www.masonline.com.ar",
    "masonline.com.ar": "https://www.masonline.com.ar",
    "diaonline.supermercadosdia.com.ar": "https://diaonline.supermercadosdia.com.ar",
    "www.carrefour.com.ar": "https://www.carrefour.com.ar",
    "carrefour.com.ar": "https://www.carrefour.com.ar",
    "www.fravega.com": "https://www.fravega.com",
    "fravega.com": "https://www.fravega.com",
    "www.cetrogar.com.ar": "https://www.cetrogar.com.ar",
    "cetrogar.com.ar": "https://www.cetrogar.com.ar",
    "www.naldo.com.ar": "https://www.naldo.com.ar",
    "naldo.com.ar": "https://www.naldo.com.ar",
    "www.oncity.com": "https://www.oncity.com",
    "oncity.com": "https://www.oncity.com",
}


def _oferta(product: dict[str, Any]) -> float | None:
    price, _ok = _precio_oferta(product)
    return price


async def _precio_vtex_por_url(url: str) -> float | None:
    parsed = urlparse(url)
    origin = VTEX_ORIGINS.get(parsed.netloc.lower())
    path = parsed.path or ""
    if not origin or not path.rstrip("/").endswith("/p"):
        return None
    api = origin + "/api/catalog_system/pub/products/search" + path
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(api, headers={"Accept": "application/json", "User-Agent": VTEX_UA})
    except Exception:
        return None
    if r.status_code not in (200, 206):
        return None
    try:
        body = r.json()
    except Exception:
        return None
    if not isinstance(body, list) or not body or not isinstance(body[0], dict):
        return None
    return _oferta(body[0])


def _match_nombre(items: list[dict[str, Any]], nombre: str, tienda: str, url: str) -> float | None:
    nombre_n = _norm(nombre)
    tienda_n = _norm(tienda)
    for p in items:
        if url and (p.get("url") or "") == url:
            price = _precio_num(p.get("precio"))
            if price is not None:
                return price
    for p in items:
        if _norm(p.get("nombre") or "") != nombre_n:
            continue
        if tienda_n and _norm(p.get("tienda") or "") != tienda_n:
            continue
        price = _precio_num(p.get("precio"))
        if price is not None:
            return price
    return None


async def _precio_vtex_busqueda(nombre: str, tienda: str, url: str) -> float | None:
    if _norm(tienda) in {"mas online", "masonline", "dia", "carrefour"}:
        data = await buscar_super(nombre)
    else:
        data = await buscar_electro(nombre)
    items = data.get("productos") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    return _match_nombre(items, nombre, tienda, url)


def _pc_match(data: Any, pid: str, nombre: str) -> float | None:
    productos = data.get("productos") if isinstance(data, dict) else None
    if not isinstance(productos, list):
        return None
    nombre_n = _norm(nombre)
    by_name = None
    for p in productos:
        if not isinstance(p, dict):
            continue
        price = _precio_num(p.get("precioMin"))
        if price is None:
            continue
        if pid and str(p.get("id") or "") == pid:
            return price
        if nombre_n and _norm(p.get("nombre") or "") == nombre_n:
            by_name = price
    return by_name


async def _precio_precios_claros(nombre: str, product_key: str) -> float | None:
    pid = product_key[3:] if product_key.startswith("pc:") else ""
    words = nombre.split()
    queries: list[str] = []
    if nombre:
        queries.append(nombre)
    for n in (4, 3, 2):
        if len(words) >= n:
            q = " ".join(words[:n])
            if q not in queries:
                queries.append(q)
    for q in queries:
        code, data = await pc_get(
            "/productos",
            {"string": q, "lat": CABA_LAT, "lng": CABA_LNG, "offset": 0, "limit": 50},
        )
        if code != 200:
            continue
        hit = _pc_match(data, pid, nombre)
        if hit is not None:
            return hit
    return None


async def precio_vigente(item: dict[str, Any]) -> tuple[float | None, str]:
    """Relee el precio actual. None si no hay un número real. No manda mail."""
    fuente = (item.get("fuente") or "").strip()
    url = (item.get("url") or "").strip()
    tienda = item.get("tienda") or ""
    nombre = item.get("nombre") or ""
    key = item.get("product_key") or ""
    host = urlparse(url).netloc.lower() if url else ""

    if host in VTEX_ORIGINS:
        price = await _precio_vtex_por_url(url)
        if price is not None:
            return price, f"Releído en {tienda or 'la tienda'} (catálogo público)."
        price = await _precio_vtex_busqueda(nombre, tienda, url)
        if price is not None:
            return price, f"Releído buscando «{nombre}» en {tienda or 'la tienda'}."
        return None, "No se pudo releer un precio real en el catálogo de la tienda."

    if fuente == "precios_claros" or key.startswith("pc:") or _norm(tienda) == "precios claros":
        price = await _precio_precios_claros(nombre, key)
        if price is not None:
            return price, "Releído en Precios Claros (mínimo en CABA)."
        return None, "No se pudo releer el mínimo en Precios Claros."

    return None, "No hay una fuente conocida para releer este producto."


def _lista_rows(email: str, product_key: str | None = None) -> list[sqlite3.Row]:
    conn = _db()
    try:
        if product_key:
            cur = conn.execute(
                "SELECT * FROM lista_compra WHERE email = ? AND product_key = ? ORDER BY id",
                (email, product_key),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM lista_compra WHERE email = ? ORDER BY id",
                (email,),
            )
        return list(cur.fetchall())
    finally:
        conn.close()


async def revisar_alertas(email: str, product_key: str | None = None) -> list[dict[str, Any]]:
    """Relee cada fila y marca bajo=1 solo si el precio nuevo es menor. No envía mail."""
    rows = _lista_rows(email, product_key)
    if not rows:
        return []
    readings = await asyncio.gather(*[precio_vigente(dict(r)) for r in rows])
    now = datetime.now(timezone.utc).isoformat()
    conn = _db()
    try:
        for row, (price, detalle) in zip(rows, readings):
            if price is None:
                conn.execute(
                    "UPDATE lista_compra SET nota = ?, revisado_at = ? WHERE email = ? AND product_key = ?",
                    (detalle, now, email, row["product_key"]),
                )
            else:
                bajo = 1 if price < float(row["precio"]) else 0
                if bajo:
                    nota = detalle + " El precio es menor al guardado. No se envió ningún mail."
                else:
                    nota = detalle + " El precio no es menor. No se envió ningún mail."
                conn.execute(
                    """UPDATE lista_compra
                       SET precio_actual = ?, bajo = ?, nota = ?, revisado_at = ?
                       WHERE email = ? AND product_key = ?""",
                    (price, bajo, nota, now, email, row["product_key"]),
                )
        conn.commit()
    finally:
        conn.close()
    return [_item_out(r) for r in _lista_rows(email, product_key)]



def _merge_cadenas(data: Any, cadenas: dict[str, Any]) -> Any:
    """Suma ítems con precio real de cadenas públicas. No pisa los de Precios Claros."""
    extra = cadenas.get("productos") if isinstance(cadenas, dict) else None
    if not isinstance(extra, list) or not extra:
        if isinstance(data, dict):
            return data
        return {"productos": []}
    if not isinstance(data, dict):
        data = {"productos": []}
    else:
        data = dict(data)
    productos = data.get("productos")
    if not isinstance(productos, list):
        productos = []
    else:
        productos = list(productos)
    productos.extend(extra)
    data["productos"] = productos
    return data



_STOP = {
    "la", "el", "los", "las", "de", "del", "y", "e", "o", "u",
    "con", "para", "por", "en", "al", "un", "una", "lo", "a",
}
# Medidas de góndola: "1 Lt.", "500g", "1,5 kg". Se sacan solo si la frase entera no trae precios.
_SIZE = re.compile(
    r"(?i)(?<!\w)\d+(?:[.,]\d+)?\s*(?:litros?|lts?|lt|l|mililitros?|mls?|cc|kilos?|kgs?|gramos?|grs?|gr|g|unidades?|uds?|un|u|cm|mm|oz)\.?(?!\w)"
)
_PUNCT_Q = re.compile(r"[^\w\s]", re.UNICODE)


def _limpia_q(s: str) -> str:
    return " ".join((s or "").split())


def _sin_puntuacion_q(s: str) -> str:
    return _limpia_q(_PUNCT_Q.sub(" ", s or "").replace("_", " "))


def _sin_medidas_q(s: str) -> str:
    return _limpia_q(_SIZE.sub(" ", s or ""))


def consultas_busqueda(q: str, tope: int = 8) -> list[str]:
    """Frase original y, si hiciera falta, versiones más cortas.

    Orden: texto tal cual, sin puntuación, sin medidas (1 Lt y parecidas),
    sin artículos, y después sacando una palabra por vez. Tope para no
    martillar Precios Claros.
    """
    base = _limpia_q(q)
    out: list[str] = []

    def add(s: str) -> None:
        s = _limpia_q(s)
        if not s or len(out) >= tope:
            return
        if any(s.casefold() == prev.casefold() for prev in out):
            return
        out.append(s)

    add(base)
    add(_sin_puntuacion_q(base))
    sin_medida = _sin_puntuacion_q(_sin_medidas_q(base))
    add(sin_medida)
    tokens = [t for t in sin_medida.split() if t.casefold() not in _STOP]
    add(" ".join(tokens))
    if len(tokens) >= 2:
        for i in range(len(tokens) - 1, -1, -1):
            add(" ".join(tokens[:i] + tokens[i + 1 :]))
        if len(tokens) > 2:
            for t in tokens:
                add(t)
    return out or ([base] if base else [])


def _pc_tiene(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("productos"), list) and bool(data["productos"])


_MESES = "ene feb mar abr may jun jul ago sep oct nov dic".split()


# America/Buenos_Aires es UTC−3 todo el año. No etiquetar la hora UTC del servidor como ART.
_ART = timezone(timedelta(hours=-3))


def _leido_ahora() -> tuple[str, str]:
    """Hora de esta lectura en Buenos Aires. No es un precio ni una promo."""
    dt = datetime.now(_ART)
    texto = f"{dt.day} {_MESES[dt.month - 1]} {dt.year}, {dt:%H:%M} (Buenos Aires)"
    return dt.isoformat(timespec="seconds"), texto


def _con_cuenta(payload: dict[str, Any], quota: dict[str, Any]) -> JSONResponse:
    payload = dict(payload)
    payload["cuenta"] = _cuenta_publica(quota)
    return JSONResponse(
        payload,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


def _cuenta_publica(quota: dict[str, Any]) -> dict[str, Any]:
    role = quota.get("role") or ""
    limit = quota.get("limit")
    if limit is None and role != "admin":
        limit = cuentas.FREE_LIMIT
    return {
        "plan": quota.get("plan"),
        "role": role,
        "used": quota.get("used"),
        "remaining": quota.get("remaining"),
        "limit": limit,
        "prefs": quota.get("prefs") or cuentas.DEFAULT_PREFS,
    }


def _imagen_https(url: Any) -> str:
    if isinstance(url, str) and url.startswith("https://"):
        return url
    return ""


async def _exigir_busqueda(request: Request, q: str) -> dict[str, Any] | JSONResponse:
    """Sin bearer no se busca. El cupo de 5 corre para una cuenta normal. El admin no tiene tope."""
    token = cuentas.bearer(request.headers)
    if not token:
        return JSONResponse(
            {"ok": False, "reason": "auth", "error": "Sin sesión. Creá una cuenta gratis para ver promos y precios."},
            status_code=401,
        )
    if not cuentas.cuentas_on():
        return JSONResponse(
            {"ok": False, "reason": "auth", "error": "No se pudo verificar la sesión. No se buscó."},
            status_code=503,
        )
    try:
        user = await cuentas.usuario(token)
    except Exception:
        return JSONResponse(
            {"ok": False, "reason": "auth", "error": "No se pudo verificar la sesión. No se buscó."},
            status_code=503,
        )
    if not user:
        return JSONResponse(
            {"ok": False, "reason": "auth", "error": "La sesión no sirve. Volvé a entrar."},
            status_code=401,
        )
    if not cuentas.cupo_on():
        return JSONResponse(
            {
                "ok": False,
                "reason": "quota_unavailable",
                "error": "No se pudo contar la búsqueda en el servidor. No se buscó.",
            },
            status_code=503,
        )
    try:
        quota = await cuentas.consumir(user["id"], q)
    except Exception:
        return JSONResponse(
            {
                "ok": False,
                "reason": "quota_unavailable",
                "error": "No se pudo contar la búsqueda en el servidor. No se buscó.",
            },
            status_code=503,
        )
    if not quota.get("ok"):
        if quota.get("reason") == "quota":
            if cuentas.cobro_on():
                msg = "Usaste las 5 búsquedas. Para seguir sin tope, pasate a BaratoYa Plus en Planes (pago con Mercado Pago)."
            else:
                msg = "Usaste las 5 búsquedas. El cobro todavía no está activo, así que desde acá no se puede pagar."
            return JSONResponse(
                {
                    "ok": False,
                    "reason": "quota",
                    "error": msg,
                    "plan": quota.get("plan") or "free",
                    "used": quota.get("used"),
                    "remaining": 0,
                    "limit": quota.get("limit") or cuentas.FREE_LIMIT,
                },
                status_code=402,
            )
        return JSONResponse(
            {"ok": False, "reason": quota.get("reason") or "bad_query", "error": "Esa búsqueda no se contó."},
            status_code=400,
        )
    quota["user_id"] = user["id"]
    quota["email"] = user["email"]
    quota["token"] = token
    try:
        perfil = await cuentas.leer_cuenta(token, user["id"])
        quota["prefs"] = perfil.get("prefs") or cuentas.DEFAULT_PREFS
    except Exception:
        quota["prefs"] = cuentas.DEFAULT_PREFS
    return quota


def _presentar_super(
    q: str,
    data: Any,
    leido: str,
    *,
    bancos_permitidos: list[str] | set[str] | None = None,
    con_promo: bool = True,
    supermercados_permitidos: list[str] | set[str] | None = None,
) -> Any:
    """Un resultado por producto exacto, con un precio por tienda."""
    if not isinstance(data, dict):
        data = {"productos": []}
    else:
        data = dict(data)
    productos = data.get("productos")
    if not isinstance(productos, list):
        productos = []
    grupos = agrupar_mismo_producto(
        q,
        productos,
        leido,
        bancos_permitidos=bancos_permitidos,
        con_promo=con_promo,
        supermercados_permitidos=supermercados_permitidos,
    )
    for g in grupos:
        if isinstance(g, dict):
            g["imagen"] = _imagen_https(g.get("imagen"))
    data["productos"] = grupos
    data["total"] = len(grupos)
    return data


def _unwrap_snapshot(body: Any) -> Any:
    """last_ok.json guarda {q, lat, lng, data}. La UI espera productos en data."""
    if isinstance(body, dict) and "productos" not in body and isinstance(body.get("data"), dict):
        return body["data"]
    return body


def _admin_vista(resumen: dict[str, Any] | None) -> dict[str, Any]:
    def n(key: str) -> str:
        if not isinstance(resumen, dict) or resumen.get(key) is None:
            return "0"
        try:
            return str(int(resumen[key]))
        except (TypeError, ValueError):
            return "0"

    pagos = resumen.get("pagos") if isinstance(resumen, dict) else None
    if pagos in (None, 0):
        pagos_txt = "0"
    else:
        try:
            pagos_txt = str(int(pagos))
        except (TypeError, ValueError):
            pagos_txt = "0"
    return {
        "usuarios": n("usuarios"),
        "busquedas": n("busquedas"),
        "perfiles_pagos": n("perfiles_pagos"),
        "ingresos": "$0",
        "pagos": pagos_txt,
    }


async def _verificar_admin(request: Request) -> tuple[bool, dict[str, Any] | None]:
    token = cuentas.token_de(request.headers, request.cookies)
    user = None
    if token and cuentas.cuentas_on():
        try:
            user = await cuentas.usuario(token)
        except Exception:
            user = None
    admin_ok = False
    if user:
        try:
            admin_ok = await cuentas.es_admin(token, user["id"])
        except Exception:
            admin_ok = False
    return admin_ok, user


@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request):
    """Solo la sesión admin abre la página. Cualquier otra recibe 403."""
    admin_ok, user = await _verificar_admin(request)
    if not admin_ok:
        body = _render_admin({"ok": False, "email": "", "seccion": "403", "vista": {}})
        return HTMLResponse(body, status_code=403)
    resumen = None
    try:
        resumen = await cuentas.resumen_admin()
    except Exception:
        resumen = None
    vista = _admin_vista(resumen)
    vista["hora_art"] = cuentas.ahora_art_texto()
    vista["mp_configurado"] = cuentas.cobro_on()
    body = _render_admin(
        {"ok": True, "email": user["email"] if user else "", "seccion": "resumen", "vista": vista}
    )
    return HTMLResponse(body)


@app.get("/admin/usuarios", response_class=HTMLResponse)
async def admin_usuarios(request: Request):
    admin_ok, user = await _verificar_admin(request)
    if not admin_ok:
        body = _render_admin({"ok": False, "email": "", "seccion": "403", "vista": {}})
        return HTMLResponse(body, status_code=403)
    usuarios = await cuentas.admin_listar_usuarios()
    body = _render_admin(
        {
            "ok": True,
            "email": user["email"] if user else "",
            "seccion": "usuarios",
            "usuarios": usuarios,
            "hora_art": cuentas.ahora_art_texto(),
        }
    )
    return HTMLResponse(body)


@app.get("/admin/usuarios/{user_id}", response_class=HTMLResponse)
async def admin_usuario_detalle(request: Request, user_id: str):
    admin_ok, user = await _verificar_admin(request)
    if not admin_ok:
        body = _render_admin({"ok": False, "email": "", "seccion": "403", "vista": {}})
        return HTMLResponse(body, status_code=403)
    detalle = await cuentas.admin_detalle_usuario(user_id)
    if not detalle:
        body = _render_admin(
            {
                "ok": True,
                "email": user["email"] if user else "",
                "seccion": "usuario_no_encontrado",
                "user_id": user_id,
            }
        )
        return HTMLResponse(body, status_code=404)
    u_email = detalle["usuario"].get("email") or ""
    items_lista = [_item_out(r) for r in _lista_rows(u_email)] if u_email and "@" in u_email else []
    detalle["lista_compra"] = items_lista
    body = _render_admin(
        {
            "ok": True,
            "email": user["email"] if user else "",
            "seccion": "usuario_detalle",
            "usuario": detalle["usuario"],
            "busquedas": detalle["busquedas"],
            "lista_compra": items_lista,
            "hora_art": cuentas.ahora_art_texto(),
        }
    )
    return HTMLResponse(body)


@app.get("/admin/busquedas", response_class=HTMLResponse)
async def admin_busquedas(request: Request):
    admin_ok, user = await _verificar_admin(request)
    if not admin_ok:
        body = _render_admin({"ok": False, "email": "", "seccion": "403", "vista": {}})
        return HTMLResponse(body, status_code=403)
    busquedas = await cuentas.admin_listar_busquedas(limit=50)
    body = _render_admin(
        {
            "ok": True,
            "email": user["email"] if user else "",
            "seccion": "busquedas",
            "busquedas": busquedas,
            "hora_art": cuentas.ahora_art_texto(),
        }
    )
    return HTMLResponse(body)


@app.get("/admin/pagos", response_class=HTMLResponse)
async def admin_pagos(request: Request):
    admin_ok, user = await _verificar_admin(request)
    if not admin_ok:
        body = _render_admin({"ok": False, "email": "", "seccion": "403", "vista": {}})
        return HTMLResponse(body, status_code=403)
    pagos_info = await cuentas.admin_listar_pagos()
    body = _render_admin(
        {
            "ok": True,
            "email": user["email"] if user else "",
            "seccion": "pagos",
            "pagos": pagos_info["pagos"],
            "total_mes": pagos_info["total_mes"],
            "total_lifetime": pagos_info["total_lifetime"],
            "mp_configurado": cuentas.cobro_on(),
            "hora_art": cuentas.ahora_art_texto(),
        }
    )
    return HTMLResponse(body)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "lat": CABA_LAT,
            "lng": CABA_LNG,
            "paid_scrapers": ENABLE_PAID,
            "mla": ENABLE_MLA,
            **cuentas.pagina_publica(),
        },
    )


@app.get("/planes", response_class=HTMLResponse)
async def planes_page(request: Request):
    return templates.TemplateResponse(
        request,
        "planes.html",
        {
            **cuentas.pagina_publica(),
        },
    )


@app.get("/aviso-precios", response_class=HTMLResponse)
async def aviso_precios(request: Request):
    return templates.TemplateResponse(request, "legal.html", {"page": "aviso-precios", "cobro_on": cuentas.cobro_on()})


@app.get("/terminos", response_class=HTMLResponse)
async def terminos(request: Request):
    return templates.TemplateResponse(request, "legal.html", {"page": "terminos", "cobro_on": cuentas.cobro_on()})


@app.get("/privacidad", response_class=HTMLResponse)
async def privacidad(request: Request):
    return templates.TemplateResponse(request, "legal.html", {"page": "privacidad", "cobro_on": cuentas.cobro_on()})


@app.get("/api/sucursales")
async def sucursales(
    lat: float = Query(CABA_LAT),
    lng: float = Query(CABA_LNG),
    limit: int = Query(10, ge=1, le=50),
):
    code, data = await pc_get("/sucursales", {"lat": lat, "lng": lng, "limit": limit})
    return JSONResponse({"http": code, "fuente": "precios_claros", "data": data}, status_code=200 if code else 502)



@app.get("/api/promos")
async def promos_bancarias(
    request: Request,
    cadena: str | None = None,
    dia: str | None = None,
    precio: float | None = None,
    nombre: str | None = None,
    ya_descuento: bool = False,
):
    """Tarjetas vigentes, por día y por banco. Requiere sesión (muro de auth).
    Si se pasa cadena, devuelve las promos de esa cadena para el día elegido con precio final.
    """
    token = cuentas.token_de(request.headers, request.cookies)
    if not token:
        return JSONResponse(
            {"ok": False, "reason": "auth", "error": "Sin sesión. Creá una cuenta gratis para ver promos y precios."},
            status_code=401,
        )
    if not cuentas.cuentas_on():
        return JSONResponse(
            {"ok": False, "reason": "auth", "error": "No se pudo verificar la sesión. No se leyeron promos."},
            status_code=503,
        )
    try:
        user = await cuentas.usuario(token)
    except Exception:
        user = None
    if not user:
        return JSONResponse(
            {"ok": False, "reason": "auth", "error": "La sesión no sirve. Volvé a entrar."},
            status_code=401,
        )
    if cadena:
        return promos_para_cadena(
            cadena=cadena,
            dia=dia,
            precio=precio,
            nombre=nombre or "",
            ya_descuento=ya_descuento,
        )
    return catalogo_promos()


@app.get("/api/buscar")
async def buscar(
    request: Request,
    q: str = Query(..., min_length=1),
    lat: float = Query(CABA_LAT),
    lng: float = Query(CABA_LNG),
    offset: int = 0,
    limit: int = Query(20, ge=1, le=50),
    bancos: str | None = None,
    supermercados: str | None = None,
    con_promo: bool | None = None,
):
    # TODO: if ENABLE_PAID_SCRAPERS: merge VTEX/MLA paid paths
    # ENABLE_MLA no abre el catálogo: Mercado Libre cerró GET /sites/MLA/search
    # (403 con o sin token de app). buscar_meli no llama a la API salvo
    # MLA_PUBLIC_SEARCH=true, y entonces el 403 deja un aviso honesto.
    # No se scrapea listado.mercadolibre.com.ar ni se inventan precios.
    q = _limpia_q(q)
    if not q:
        return JSONResponse({"ok": False, "error": "Escribí un producto."}, status_code=400)
    gate = await _exigir_busqueda(request, q)
    if isinstance(gate, JSONResponse):
        return gate
    user_prefs = (gate.get("prefs") if isinstance(gate, dict) else None) or {}
    bancos_filtro = [b.strip() for b in bancos.split(",") if b.strip()] if bancos is not None else user_prefs.get("banks")
    supers_filtro = [s.strip() for s in supermercados.split(",") if s.strip()] if supermercados is not None else user_prefs.get("supermarkets")
    promo_on = con_promo if con_promo is not None else user_prefs.get("show_promo_price", True)

    def _presentar(raw_data: Any, leido_ts: str) -> Any:
        return _presentar_super(
            q,
            raw_data,
            leido_ts,
            bancos_permitidos=bancos_filtro,
            con_promo=promo_on,
            supermercados_permitidos=supers_filtro,
        )

    consultas = consultas_busqueda(q)
    cadenas_task = asyncio.create_task(buscar_super(q, consultas))
    promos_task = asyncio.create_task(buscar_promos())
    meli_task = asyncio.create_task(buscar_meli(q))
    code, data = await pc_get(
        "/productos",
        {"string": q, "lat": lat, "lng": lng, "offset": offset, "limit": limit},
    )
    q_pc = q
    if code == 200 and not _pc_tiene(data):
        for alt in consultas[1:]:
            code_alt, data_alt = await pc_get(
                "/productos",
                {"string": alt, "lat": lat, "lng": lng, "offset": offset, "limit": limit},
            )
            if code_alt == 200 and _pc_tiene(data_alt):
                code, data = code_alt, data_alt
                q_pc = alt
                break
    try:
        cadenas = await cadenas_task
    except Exception as e:
        cadenas = {
            "productos": [],
            "q_usada": q,
            "fuentes": [
                {"tienda": s["nombre"], "tienda_id": s["id"], "http": 0, "ok": False, "n": 0, "error": str(e)}
                for s in SUPER_STORES
            ],
        }
    q_mo = cadenas.get("q_usada") or q
    try:
        promos = await promos_task
    except Exception as e:
        promos = [{"tienda": "promos", "ok": False, "nota": str(e), "items": [], "url": "", "http": 0}]
    try:
        meli = await meli_task
    except Exception as e:
        meli = {"tienda": "Mercado Libre", "tienda_id": "mla", "http": 0, "ok": False, "n": 0, "productos": [], "aviso": str(e)}
    cadenas = dict(cadenas)
    # Catálogo público apagado: no sumar una fuente vacía. La UI la leería
    # como "Mercado Libre no respondió" y parecería un bug de BaratoYa.
    if not meli.get("omitido"):
        rows = meli.get("productos") if isinstance(meli.get("productos"), list) else []
        if rows:
            productos_c = list(cadenas.get("productos") or [])
            productos_c.extend(rows)
            cadenas["productos"] = productos_c
        fuentes = list(cadenas.get("fuentes") or [])
        fuentes.append({k: v for k, v in meli.items() if k != "productos"})
        cadenas["fuentes"] = fuentes
    leido, leido_texto = _leido_ahora()

    def _consulta() -> dict[str, Any]:
        return {
            "q": q,
            "q_precios_claros": q_pc,
            "q_mas_online": q_mo,
            "leido": leido,
            "leido_texto": leido_texto,
            "promos": promos,
            "bancos": bancos_filtro or [],
            "supermercados": supers_filtro or [],
            "con_promo": promo_on,
        }

    if code != 200:
        # El snapshot es una lectura vieja: no se mezcla con precios de esta request.
        if cadenas.get("productos"):
            return _con_cuenta({
                "http": 200,
                "fuente": "mas_online",
                "aviso": "Precios Claros no respondió. Solo precios leídos ahora del catálogo público de las cadenas que respondieron.",
                "cadenas": cadenas.get("fuentes") or [],
                "data": _presentar({"productos": cadenas["productos"]}, leido),
                **_consulta(),
            }, gate)
        snap = SNAPSHOT_DIR / "last_ok.json"
        if snap.exists() and (time.time() - snap.stat().st_mtime) < 12 * 3600:
            body = _unwrap_snapshot(json.loads(snap.read_text()))
            body = _presentar(body, "")
            consulta = _consulta()
            consulta["leido"] = ""
            consulta["leido_texto"] = ""
            return _con_cuenta({
                "http": code,
                "fuente": "snapshot",
                "aviso": "Live Precios Claros falló y las cadenas no trajeron precio. Mostrando el último snapshot local, que no es de esta lectura.",
                "cadenas": cadenas.get("fuentes") or [],
                "data": body,
                **consulta,
            }, gate)
        err = {
            "http": code,
            "fuente": "precios_claros",
            "error": data,
            "cadenas": cadenas.get("fuentes") or [],
            **_consulta(),
        }
        err["cuenta"] = _cuenta_publica(gate)
        return JSONResponse(
            err,
            status_code=502,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
            },
        )
    # guardar snapshot liviano (solo Precios Claros, sin mezclar otras cadenas)
    if _pc_tiene(data):
        try:
            (SNAPSHOT_DIR / "last_ok.json").write_text(
                json.dumps({"q": q_pc, "lat": lat, "lng": lng, "data": data}, ensure_ascii=False)[:500_000]
            )
        except Exception:
            pass
    productos = data.get("productos") if isinstance(data, dict) else []
    # ordenar por precioMin
    if isinstance(productos, list):
        productos = sorted(
            productos,
            key=lambda p: (p.get("precioMin") is None, p.get("precioMin") or 0),
        )
        data = dict(data)
        data["productos"] = productos
    data = _presentar(_merge_cadenas(data, cadenas), leido)
    return _con_cuenta({
        "http": code,
        "fuente": "precios_claros_live",
        "cadenas": cadenas.get("fuentes") or [],
        "data": data,
        **_consulta(),
    }, gate)


@app.get("/api/electro")
async def electro(
    request: Request,
    q: str = Query("heladera", min_length=1, max_length=80),
):
    """Electrodomésticos: VTEX público (Fravega, Cetrogar, Naldo, On City). ML no se inventa."""
    if ENABLE_PAID:
        # Sigue apagado por defecto. Este endpoint no usa scrapers pagos.
        pass
    q = _limpia_q(q)
    if not q:
        return JSONResponse({"ok": False, "error": "Escribí un producto."}, status_code=400)
    gate = await _exigir_busqueda(request, q)
    if isinstance(gate, JSONResponse):
        return gate
    data = await buscar_electro(q)
    productos = data.get("productos") if isinstance(data, dict) else None
    if isinstance(productos, list):
        for p in productos:
            if isinstance(p, dict):
                p["imagen"] = _imagen_https(p.get("imagen"))
    return _con_cuenta({"http": 200, "fuente": "vtex_publico", "data": data}, gate)



@app.get("/api/cuenta")
async def ver_cuenta(request: Request):
    if not cuentas.cuentas_on():
        return JSONResponse(
            {"ok": False, "error": "Las cuentas no están configuradas en este servidor."},
            status_code=503,
        )
    token = cuentas.bearer(request.headers)
    if not token:
        return JSONResponse({"ok": False, "reason": "auth", "error": "Sin sesión."}, status_code=401)
    user = await cuentas.usuario(token)
    if not user:
        return JSONResponse({"ok": False, "reason": "auth", "error": "La sesión no sirve."}, status_code=401)
    perfil = await cuentas.leer_cuenta(token, user["id"])
    return {
        "ok": True,
        "email": user["email"],
        "plan": perfil["plan"],
        "plan_base": perfil.get("plan_base", "free"),
        "trial": bool(perfil.get("trial")),
        "trial_activo": bool(perfil.get("trial_activo")),
        "trial_ends_at": perfil.get("trial_ends_at"),
        "trial_ends_at_texto": perfil.get("trial_ends_at_texto") or "",
        "used": perfil["used"],
        "remaining": perfil["remaining"],
        "limit": perfil["limit"],
        "admin": bool(perfil.get("admin")),
        "cobro_activo": cuentas.cobro_on(),
        "plan_label": cuentas.plan_label() if cuentas.cobro_on() else "",
        "prefs": perfil.get("prefs") or cuentas.DEFAULT_PREFS,
    }


@app.post("/api/cuenta/activar-trial")
async def activar_trial_cuenta(request: Request):
    """Persiste trial 7d Plus tras signup. Idempotente si ya hay trial_ends_at o paid_at."""
    if not cuentas.cuentas_on():
        return JSONResponse(
            {"ok": False, "error": "Las cuentas no están configuradas en este servidor."},
            status_code=503,
        )
    token = cuentas.bearer(request.headers)
    if not token:
        return JSONResponse({"ok": False, "reason": "auth", "error": "Sin sesión."}, status_code=401)
    user = await cuentas.usuario(token)
    if not user:
        return JSONResponse({"ok": False, "reason": "auth", "error": "La sesión no sirve."}, status_code=401)
    perfil = await cuentas.leer_cuenta(token, user["id"])
    return {
        "ok": True,
        "trial": bool(perfil.get("trial")),
        "trial_activo": bool(perfil.get("trial_activo")),
        "trial_ends_at": perfil.get("trial_ends_at"),
        "trial_ends_at_texto": perfil.get("trial_ends_at_texto") or "",
        "plan": perfil.get("plan"),
        "plan_base": perfil.get("plan_base", "free"),
    }


@app.get("/api/cuenta/preferencias")
async def ver_preferencias(request: Request):
    if not cuentas.cuentas_on():
        return JSONResponse({"ok": False, "error": "Las cuentas no están configuradas."}, status_code=503)
    token = cuentas.bearer(request.headers)
    if not token:
        return JSONResponse({"ok": False, "reason": "auth", "error": "Sin sesión."}, status_code=401)
    user = await cuentas.usuario(token)
    if not user:
        return JSONResponse({"ok": False, "reason": "auth", "error": "La sesión no sirve."}, status_code=401)
    perfil = await cuentas.leer_cuenta(token, user["id"])
    return {"ok": True, "prefs": perfil.get("prefs") or cuentas.DEFAULT_PREFS}


@app.post("/api/cuenta/preferencias")
async def guardar_preferencias_endpoint(request: Request):
    if not cuentas.cuentas_on():
        return JSONResponse({"ok": False, "error": "Las cuentas no están configuradas."}, status_code=503)
    token = cuentas.bearer(request.headers)
    if not token:
        return JSONResponse({"ok": False, "reason": "auth", "error": "Sin sesión."}, status_code=401)
    user = await cuentas.usuario(token)
    if not user:
        return JSONResponse({"ok": False, "reason": "auth", "error": "La sesión no sirve."}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    res = await cuentas.guardar_preferencias(token, user["id"], body)
    return res


@app.get("/api/cuenta/busquedas")
async def ver_busquedas(request: Request):
    """Búsquedas pasadas. No es un carrito y no compra en el súper."""
    if not cuentas.cuentas_on():
        return JSONResponse({"ok": False, "error": "Las cuentas no están configuradas."}, status_code=503)
    token = cuentas.bearer(request.headers)
    if not token:
        return JSONResponse({"ok": False, "reason": "auth", "error": "Sin sesión."}, status_code=401)
    user = await cuentas.usuario(token)
    if not user:
        return JSONResponse({"ok": False, "reason": "auth", "error": "La sesión no sirve."}, status_code=401)
    items = await cuentas.listar_busquedas(token, user["id"])
    return {"ok": True, "items": items}


@app.post("/api/cuenta/checkout")
async def checkout_cuenta(request: Request):
    if not cuentas.cuentas_on():
        return JSONResponse({"ok": False, "error": "Las cuentas no están configuradas."}, status_code=503)
    token = cuentas.bearer(request.headers)
    if not token:
        return JSONResponse({"ok": False, "reason": "auth", "error": "Sin sesión."}, status_code=401)
    user = await cuentas.usuario(token)
    if not user:
        return JSONResponse({"ok": False, "reason": "auth", "error": "La sesión no sirve."}, status_code=401)
    perfil = await cuentas.leer_cuenta(token, user["id"])
    # Solo bloquear si ya pagó Plus real. Trial (plan efectivo paid) sí puede suscribirse.
    if perfil.get("paid_at") or (
        perfil.get("plan_base") == "paid" and not perfil.get("trial")
    ):
        return {"ok": True, "already": True, "error": "Esta cuenta ya tiene búsquedas ilimitadas."}
    result = await cuentas.crear_preferencia(user["id"], user["email"])
    status = int(result.pop("status", 200))
    return JSONResponse(result, status_code=status)


@app.api_route("/api/mercadopago/webhook", methods=["GET", "POST"])
async def mercadopago_webhook(request: Request):
    body: dict[str, Any] = {}
    if request.method == "POST":
        ctype = request.headers.get("content-type", "")
        if "application/json" in ctype:
            try:
                parsed = await request.json()
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                body = parsed
        elif "form" in ctype:
            form = await request.form()
            body = {k: form.get(k) for k in form.keys()}
    try:
        result = await cuentas.procesar_aviso(dict(request.query_params), body)
    except Exception:
        return JSONResponse({"ok": False, "error": "No se pudo anotar el aviso."}, status_code=502)
    return JSONResponse(result["body"], status_code=result["status"])


@app.get("/health")
async def health():
    code, data = await pc_get("/sucursales", {"lat": CABA_LAT, "lng": CABA_LNG, "limit": 1})
    return {"ok": code == 200, "precios_claros_http": code, "paid_scrapers": ENABLE_PAID}


@app.post("/api/lista-espera")
async def lista_espera(request: Request):
    """Lista de espera local. No cobra, no manda mail, no prende Stripe."""
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        email = str(payload.get("email") or "")
        plan = str(payload.get("plan") or "")
    else:
        form = await request.form()
        email = str(form.get("email") or "")
        plan = str(form.get("plan") or "")
    email = email.strip().lower()
    plan = plan.strip().lower()
    if plan not in PLANES:
        plan = ""
    if not EMAIL_RE.match(email) or len(email) > 200:
        return JSONResponse(
            {"ok": False, "error": "Ese mail no sirve. Revisalo."},
            status_code=400,
        )
    conn = _db()
    try:
        cur = conn.execute("SELECT id FROM lista_espera WHERE email = ?", (email,))
        if cur.fetchone():
            conn.execute("UPDATE lista_espera SET plan = ? WHERE email = ?", (plan, email))
            conn.commit()
            return {"ok": True, "nuevo": False}
        conn.execute(
            "INSERT INTO lista_espera (email, plan, created_at) VALUES (?, ?, ?)",
            (email, plan, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return {"ok": True, "nuevo": True}
    finally:
        conn.close()


async def _email_de_sesion(request: Request) -> str | JSONResponse:
    """Lista y alertas: solo con la sesión de Supabase (igual que /api/cuenta).

    El mail sale del usuario autenticado. ?email= y el email del body se ignoran.
    """
    token = cuentas.bearer(request.headers)
    if not token:
        return JSONResponse({"ok": False, "reason": "auth", "error": "Sin sesión."}, status_code=401)
    if not cuentas.cuentas_on():
        return JSONResponse(
            {"ok": False, "error": "Las cuentas no están configuradas en este servidor."},
            status_code=503,
        )
    user = await cuentas.usuario(token)
    email = str((user or {}).get("email") or "").strip().lower()
    if not user or not _email_ok(email):
        return JSONResponse({"ok": False, "reason": "auth", "error": "La sesión no sirve."}, status_code=401)
    return email


def _leer_payload_lista(payload: dict[str, Any], email: str) -> dict[str, Any] | JSONResponse:
    nombre = " ".join(str(payload.get("nombre") or "").split())
    tienda = " ".join(str(payload.get("tienda") or "").split())
    url = str(payload.get("url") or "").strip()
    fuente = str(payload.get("fuente") or "").strip().lower()
    product_key = " ".join(str(payload.get("product_key") or "").split())
    precio = _precio_num(payload.get("precio"))
    if not nombre or len(nombre) > 300:
        return JSONResponse({"ok": False, "error": "Falta el nombre del producto."}, status_code=400)
    if not tienda or len(tienda) > 80:
        return JSONResponse({"ok": False, "error": "Falta la tienda."}, status_code=400)
    if precio is None:
        return JSONResponse({"ok": False, "error": "Ese producto no tiene un precio para guardar."}, status_code=400)
    if url and (len(url) > 500 or not url.startswith(("http://", "https://"))):
        return JSONResponse({"ok": False, "error": "La URL del producto no sirve."}, status_code=400)
    if fuente not in {"", "precios_claros", "vtex"}:
        fuente = ""
    if not product_key:
        product_key = ("url:" + url) if url else f"{fuente or tienda}:{nombre}"
    if len(product_key) > 400:
        return JSONResponse({"ok": False, "error": "La clave del producto es demasiado larga."}, status_code=400)
    return {
        "email": email,
        "nombre": nombre,
        "tienda": tienda,
        "url": url,
        "fuente": fuente,
        "product_key": product_key,
        "precio": precio,
    }


@app.post("/api/lista")
async def guardar_en_lista(request: Request):
    """Guarda un producto ya visto en la lista del usuario con sesión. No cobra."""
    email = await _email_de_sesion(request)
    if isinstance(email, JSONResponse):
        return email
    try:
        payload = await request.json()
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "Mandá JSON con nombre, tienda, precio y url."}, status_code=400)
    parsed = _leer_payload_lista(payload, email)
    if isinstance(parsed, JSONResponse):
        return parsed
    conn = _db()
    try:
        cur = conn.execute(
            "SELECT * FROM lista_compra WHERE email = ? AND product_key = ?",
            (parsed["email"], parsed["product_key"]),
        )
        ya = cur.fetchone()
        if ya:
            return {"ok": True, "nuevo": False, "aviso": "Ya estaba en la lista. El precio guardado no se cambió.", "item": _item_out(ya)}
        n = conn.execute("SELECT COUNT(*) AS n FROM lista_compra WHERE email = ?", (parsed["email"],)).fetchone()["n"]
        if n >= 100:
            return JSONResponse({"ok": False, "error": "La lista llega hasta 100 productos."}, status_code=400)
        conn.execute(
            """INSERT INTO lista_compra
               (email, product_key, nombre, tienda, precio, url, fuente, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                parsed["email"],
                parsed["product_key"],
                parsed["nombre"],
                parsed["tienda"],
                parsed["precio"],
                parsed["url"],
                parsed["fuente"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM lista_compra WHERE email = ? AND product_key = ?",
            (parsed["email"], parsed["product_key"]),
        ).fetchone()
        return {
            "ok": True,
            "nuevo": True,
            "aviso": "Guardado en tu lista.",
            "item": _item_out(row),
        }
    finally:
        conn.close()


@app.get("/api/lista")
async def ver_lista(request: Request):
    """Lista del usuario con sesión. ?email= se ignora."""
    email = await _email_de_sesion(request)
    if isinstance(email, JSONResponse):
        return email
    items = [_item_out(r) for r in _lista_rows(email)]
    return {
        "ok": True,
        "email": email,
        "aviso": "Tu lista. Solo la ve tu cuenta.",
        "items": items,
    }


@app.get("/api/alertas")
async def ver_alertas(request: Request):
    """Filas de alerta del usuario con sesión, sin releer precios y sin mandar mail. ?email= se ignora."""
    email = await _email_de_sesion(request)
    if isinstance(email, JSONResponse):
        return email
    return {
        "ok": True,
        "email": email,
        "aviso": "No se envió mail. bajo=true solo si una relectura anterior vio un precio menor.",
        "alertas": [_item_out(r) for r in _lista_rows(email)],
    }


@app.post("/api/alertas/revisar")
async def alertas_revisar(request: Request):
    """Relee el precio vigente y marca la fila si bajó. Solo con sesión; el email del body se ignora."""
    email = await _email_de_sesion(request)
    if isinstance(email, JSONResponse):
        return email
    try:
        payload = await request.json()
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        payload = {}
    product_key = str(payload.get("product_key") or "").strip() or None
    if product_key and len(product_key) > 400:
        return JSONResponse({"ok": False, "error": "La clave del producto es demasiado larga."}, status_code=400)
    alertas = await revisar_alertas(email, product_key)
    return {
        "ok": True,
        "email": email,
        "aviso": "Relectura a pedido. No hay envío de mail ni una tarea programada.",
        "alertas": alertas,
    }
