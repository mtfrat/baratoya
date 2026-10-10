"""Páginas públicas de precio por producto.

Los precios salen de los catálogos públicos que ya consulta `buscar_super`
(Día, Carrefour, Jumbo, Disco, Vea, Mas Online y las otras cadenas cableadas).
El catálogo de abajo es solo la búsqueda: marca, variante y tamaño. El número
lo pone la respuesta. Con menos de dos cadenas no se publica la página.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from baratoya.promos_hoy import cadenas_indexables
    from baratoya.super_cadenas import agrupar_mismo_producto, buscar_super
except ImportError:
    from promos_hoy import cadenas_indexables
    from super_cadenas import agrupar_mismo_producto, buscar_super

ART = timezone(timedelta(hours=-3))
ORIGEN = "https://baratoya.app"
PATH_HUB = "/precios"
RUTA = Path(__file__).parent / "data" / "precios-publicos.json"
RUTA_TMP = Path("/tmp/baratoya-precios-publicos.json")
MIN_CADENAS = 2
HORAS_FRESCURA = 24
CACHE_CONTROL = "public, max-age=300, s-maxage=86400, stale-while-revalidate=86400"

HUB_TITLE = "Comparar precios de supermercados hoy | BaratoYa"
HUB_H1 = "Comparar precios de supermercados hoy"
CATEGORIAS = ("Lácteos", "Almacén", "Bebidas", "Limpieza")
_MESES = "ene feb mar abr may jun jul ago sep oct nov dic".split()

# Qué buscar. Sin precios: si el catálogo no trae dos cadenas, la página no sale.
CATALOGO: list[dict[str, Any]] = [
    {"slug": "leche-la-serenisima-sachet-1l", "categoria": "Lácteos", "q": "leche entera la serenisima sachet 1 l", "incluye": ["sachet", "entera"], "excluye": ["protein", "proteina", "descremada", "zero", "lactosa", "barista", "chocolatada"]},
    {"slug": "leche-la-serenisima-clasica-1l", "categoria": "Lácteos", "q": "leche la serenisima clasica 1 l", "incluye": ["clasica"], "excluye": ["liviana", "larga", "descremada", "sachet", "protein", "proteina"]},
    {"slug": "leche-la-serenisima-descremada-1l", "categoria": "Lácteos", "q": "leche la serenisima descremada 1 l", "incluye": ["descremada"], "excluye": ["sachet", "zero", "lactosa", "protein", "proteina", "chocolatada"]},
    {"slug": "leche-la-serenisima-descremada-sachet-1l", "categoria": "Lácteos", "q": "leche la serenisima descremada 1 l", "incluye": ["descremada", "sachet"], "excluye": ["zero", "lactosa", "protein", "proteina", "chocolatada"]},
    {"slug": "leche-tregar-entera-1l", "categoria": "Lácteos", "q": "leche tregar entera 1 l", "incluye": ["entera"], "excluye": ["descremada", "chocolatada", "chocoltada"]},
    {"slug": "leche-ilolay-entera-1l", "categoria": "Lácteos", "q": "leche ilolay entera 1 l", "incluye": ["entera"], "excluye": ["descremada", "chocolatada"]},
    {"slug": "manteca-la-serenisima-200g", "categoria": "Lácteos", "q": "manteca la serenisima 200 g", "incluye": [], "excluye": ["light", "untable"]},
    {"slug": "dulce-de-leche-la-serenisima-400g", "categoria": "Lácteos", "q": "dulce de leche la serenisima 400 g", "incluye": ["clasico"], "excluye": ["colonial", "repostero"]},
    {"slug": "yogur-ser-frutilla-190g", "categoria": "Lácteos", "q": "yogur firme ser frutilla 190 g", "incluye": ["firme", "frutilla"], "excluye": ["bebible", "vainilla"]},
    {"slug": "queso-rallado-la-serenisima-130g", "categoria": "Lácteos", "q": "queso rallado la serenisima 130 g", "incluye": [], "excluye": ["reggianito"]},
    {"slug": "aceite-natura-girasol-1-5l", "categoria": "Almacén", "q": "aceite natura 1.5 l", "incluye": ["girasol"], "excluye": ["oliva", "mezcla"]},
    {"slug": "aceite-cocinero-girasol-900ml", "categoria": "Almacén", "q": "aceite cocinero 900 ml", "incluye": ["girasol"], "excluye": ["oliva"]},
    {"slug": "aceite-canuelas-girasol-900ml", "categoria": "Almacén", "q": "aceite canuelas 900 ml", "incluye": ["girasol"], "excluye": ["oliva"]},
    {"slug": "aceite-oliva-natura-500ml", "categoria": "Almacén", "q": "aceite de oliva natura 500 ml", "incluye": ["oliva"], "excluye": ["fuerte", "virgen"]},
    {"slug": "azucar-ledesma-1kg", "categoria": "Almacén", "q": "azucar ledesma 1 kg", "incluye": ["molida"], "excluye": []},
    {"slug": "harina-pureza-0000-1kg", "categoria": "Almacén", "q": "harina pureza 0000 1 kg", "incluye": ["0000"], "excluye": []},
    {"slug": "harina-favorita-000-1kg", "categoria": "Almacén", "q": "harina favorita 000 1 kg", "incluye": ["000"], "excluye": ["0000"]},
    {"slug": "harina-favorita-0000-1kg", "categoria": "Almacén", "q": "harina favorita 0000 1 kg", "incluye": ["0000"], "excluye": []},
    {"slug": "yerba-taragui-1kg", "categoria": "Almacén", "q": "yerba taragui 1 kg", "incluye": [], "excluye": ["sin palo", "4flex", "hierbas"]},
    {"slug": "yerba-playadito-1kg", "categoria": "Almacén", "q": "yerba playadito 1 kg", "incluye": [], "excluye": ["hierbas"]},
    {"slug": "yerba-union-suave-1kg", "categoria": "Almacén", "q": "yerba union suave 1 kg", "incluye": ["suave"], "excluye": ["liviana"]},
    {"slug": "fideos-matarazzo-spaghetti-500g", "categoria": "Almacén", "q": "fideos matarazzo spaghetti 500 g", "incluye": ["spaghetti"], "excluye": ["sin tacc", "integral", "rina"]},
    {"slug": "fideos-lucchetti-spaghetti-500g", "categoria": "Almacén", "q": "fideos lucchetti spaghetti 500 g", "incluye": ["spaghetti"], "excluye": ["huevo", "integral"]},
    {"slug": "arroz-gallo-largo-fino-1kg", "categoria": "Almacén", "q": "arroz largo fino gallo 1 kg", "incluye": ["largo fino"], "excluye": ["oro", "parboil"]},
    {"slug": "arroz-gallo-oro-1kg", "categoria": "Almacén", "q": "arroz gallo oro 1 kg", "incluye": ["oro"], "excluye": ["largo fino"]},
    {"slug": "cafe-la-virginia-500g", "categoria": "Almacén", "q": "cafe la virginia 500 g", "incluye": [], "excluye": ["expresso", "espresso", "capsula", "capsulas"]},
    {"slug": "sal-fina-celusal-500g", "categoria": "Almacén", "q": "sal celusal 500 g", "incluye": ["fina"], "excluye": ["gruesa", "entrefina"]},
    {"slug": "atun-la-campagnola-aceite-170g", "categoria": "Almacén", "q": "atun la campagnola 170 g", "incluye": ["aceite"], "excluye": ["natural"]},
    {"slug": "mayonesa-natura-475g", "categoria": "Almacén", "q": "mayonesa natura 475 g", "incluye": [], "excluye": ["light"]},
    {"slug": "galletitas-criollitas-300g", "categoria": "Almacén", "q": "galletitas criollitas 300 g", "incluye": [], "excluye": []},
    {"slug": "arvejas-secas-arcor-300g", "categoria": "Almacén", "q": "arvejas arcor", "incluye": ["secas"], "excluye": []},
    {"slug": "mermelada-durazno-la-campagnola-454g", "categoria": "Almacén", "q": "mermelada la campagnola durazno", "incluye": ["durazno"], "excluye": ["light", "diet"]},
    {"slug": "agua-villavicencio-sin-gas-2l", "categoria": "Bebidas", "q": "agua villavicencio 2 l", "incluye": ["sin gas"], "excluye": ["gasificada", "sabor", "saborizada"]},
    {"slug": "coca-cola-original-2-25l", "categoria": "Bebidas", "q": "gaseosa coca cola original 2.25 l", "incluye": ["original"], "excluye": ["zero", "sin azucar", "light"]},
    {"slug": "cerveza-quilmes-1l", "categoria": "Bebidas", "q": "cerveza quilmes 1 l", "incluye": [], "excluye": ["ipa", "stout", "bock", "negra"]},
    {"slug": "te-la-virginia-comun", "categoria": "Bebidas", "q": "te la virginia", "incluye": ["comun"], "excluye": ["boldo", "manzanilla", "verde", "rojo", "hierbas"]},
    {"slug": "lavandina-ayudin-original-1l", "categoria": "Limpieza", "q": "lavandina ayudin 1 l", "incluye": ["original"], "excluye": ["antisplash", "ropa", "gel"]},
    {"slug": "jabon-en-polvo-ala-bicarbonato-800g", "categoria": "Limpieza", "q": "jabon en polvo ala", "incluye": ["bicarbonato", "800"], "excluye": ["3 kg", "3kg", "matic"]},
    {"slug": "papel-higienico-higienol-4un", "categoria": "Limpieza", "q": "papel higienico higienol", "incluye": [], "excluye": ["30 m", "80 m"]},
]

MUESTRA_SLUGS = (
    "leche-la-serenisima-sachet-1l",
    "aceite-natura-girasol-1-5l",
    "azucar-ledesma-1kg",
    "yerba-taragui-1kg",
    "fideos-matarazzo-spaghetti-500g",
    "arroz-gallo-largo-fino-1kg",
    "cafe-la-virginia-500g",
    "coca-cola-original-2-25l",
)

_SPEC = {item["slug"]: item for item in CATALOGO}
_mem: dict[str, Any] | None = None
_lock = asyncio.Lock()


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.casefold()


def _pasa(nombre: str, incluye: list[str], excluye: list[str]) -> bool:
    plano = _fold(nombre)
    if any(_fold(t) in plano for t in excluye if t):
        return False
    return all(_fold(t) in plano for t in incluye if t)


def peso(n: float) -> str:
    """$1.955 o $1.259,40. Separador de miles argentino."""
    n = round(float(n) + 1e-9, 2)
    entero = int(n)
    cent = int(round((n - entero) * 100))
    if cent == 100:
        entero += 1
        cent = 0
    miles = f"{entero:,}".replace(",", ".")
    if cent == 0:
        return f"${miles}"
    return f"${miles},{cent:02d}"


def precio_schema(n: float) -> str:
    return f"{round(float(n) + 1e-9, 2):.2f}"


def _lista_y(nombres: list[str]) -> str:
    if len(nombres) == 1:
        return nombres[0]
    if len(nombres) == 2:
        return f"{nombres[0]} y {nombres[1]}"
    return ", ".join(nombres[:-1]) + " y " + nombres[-1]


def resumen_precios(ofertas: list[dict[str, Any]]) -> str:
    low = min(o["precio"] for o in ofertas)
    high = max(o["precio"] for o in ofertas)
    quienes = _lista_y([o["tienda"] for o in ofertas if o["precio"] == low])
    monto = peso(low)
    if high == low:
        return f"Hoy el precio publicado es {monto} en todas las cadenas de esta página."
    pct = int(round((high - low) / high * 100))
    if pct <= 0:
        return f"Hoy el más barato es {quienes} a {monto}, menos de 1% por debajo del más caro."
    return f"Hoy el más barato es {quienes} a {monto}, {pct}% menos que el más caro."


def _titulo(nombre: str) -> str:
    for texto in (f"Precio {nombre} hoy | BaratoYa", f"Precio {nombre} hoy"):
        if len(texto) <= 60:
            return texto
    lugar = 60 - len("Precio ") - len(" hoy")
    corto = nombre[:lugar].rsplit(" ", 1)[0].strip() or nombre[:lugar].strip()
    return f"Precio {corto} hoy"


def _descripcion(nombre: str, ofertas: list[dict[str, Any]], resumen: str) -> str:
    low = min(o["precio"] for o in ofertas)
    barato = _lista_y([o["tienda"] for o in ofertas if o["precio"] == low])
    n = len(ofertas)
    candidatos = [
        f"Precio de {nombre} hoy: desde {peso(low)} en {barato}. Comparación en {n} supermercados, con fecha de captura.",
        f"{nombre}: desde {peso(low)} en {barato}. Precio de góndola en {n} supermercados, con fecha de captura.",
        f"Desde {peso(low)} en {barato}. {resumen}",
    ]
    for texto in candidatos:
        if len(texto) <= 155:
            return texto
    return candidatos[-1][:155].rsplit(" ", 1)[0].rstrip(".,;") + "."


def _ld(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def _ofertas_validas(rows: list[Any]) -> list[dict[str, Any]]:
    by: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        precio = row.get("precio")
        if isinstance(precio, bool) or not isinstance(precio, (int, float)) or precio <= 0:
            continue
        tid = str(row.get("tienda_id") or "").strip()
        tienda = str(row.get("tienda") or "").strip()
        if not tid or not tienda:
            continue
        url = str(row.get("url") or "")
        if not url.startswith("https://"):
            url = ""
        item = {
            "tienda": tienda,
            "tienda_id": tid,
            "precio": round(float(precio) + 1e-9, 2),
            "nombre": " ".join(str(row.get("nombre") or "").split()),
            "url": url,
        }
        prev = by.get(tid)
        if prev is None or item["precio"] < prev["precio"]:
            by[tid] = item
    out = list(by.values())
    out.sort(key=lambda o: (o["precio"], o["tienda"]))
    return out


def elegir_grupo(
    grupos: list[dict[str, Any]],
    spec: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    incluye = list(spec.get("incluye") or [])
    excluye = list(spec.get("excluye") or [])
    for grupo in grupos:
        nombre = str(grupo.get("nombre") or "")
        if not nombre or not _pasa(nombre, incluye, excluye):
            continue
        ofertas = _ofertas_validas(grupo.get("ofertas") or [])
        if len(ofertas) < MIN_CADENAS:
            continue
        return grupo, ofertas
    return None, []


def _texto_captura(dt: datetime) -> str:
    return f"{dt.day} {_MESES[dt.month - 1]} {dt.year}, {dt:%H:%M} (Buenos Aires)"


def _fecha_corta(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    return f"{dt.day} {_MESES[dt.month - 1]} {dt.year}"


def _lastmod(iso: str) -> str:
    return datetime.fromisoformat(iso).date().isoformat()


def armar_captura(
    spec: dict[str, Any],
    grupo: dict[str, Any],
    ofertas: list[dict[str, Any]],
    cuando: datetime,
) -> dict[str, Any] | None:
    nombre = " ".join(str(grupo.get("nombre") or "").split())
    if not nombre or len(ofertas) < MIN_CADENAS:
        return None
    ean = re.sub(r"\D", "", str(grupo.get("ean") or ""))
    return {
        "slug": spec["slug"],
        "categoria": spec["categoria"],
        "nombre": nombre,
        "marca": str(grupo.get("marca") or "").strip(),
        "tamano": str(grupo.get("tamano") or "").strip(),
        "ean": ean,
        "capturado": cuando.isoformat(timespec="seconds"),
        "capturado_texto": _texto_captura(cuando),
        "ofertas": ofertas,
    }


def _promos(ofertas: list[dict[str, Any]]) -> list[dict[str, str]]:
    indice = {c["chain_id"]: c for c in cadenas_indexables()}
    links: list[dict[str, str]] = []
    vistos: set[str] = set()
    for oferta in ofertas:
        cadena = indice.get(oferta["tienda_id"])
        if not cadena or cadena["href"] in vistos:
            continue
        vistos.add(cadena["href"])
        links.append({"nombre": cadena["nombre"], "href": cadena["href"]})
    return links


def _faq(
    nombre: str,
    resumen: str,
    n: int,
    capturado_texto: str,
    promos: list[dict[str, str]],
) -> list[dict[str, str]]:
    if promos:
        nombres = _lista_y([p["nombre"] for p in promos])
        promo_txt = (
            f"No. Acá está el precio de góndola del catálogo público. "
            f"Las promos bancarias de {nombres} están en sus páginas."
        )
    else:
        promo_txt = (
            "No. Acá está el precio de góndola del catálogo público. "
            "Las promos bancarias de supermercados están en otra página."
        )
    return [
        {
            "q": f"¿Cuánto sale {nombre} hoy?",
            "a": f"Captura del {capturado_texto}. {resumen} Hay precio en {n} supermercados.",
        },
        {
            "q": f"¿Dónde está más barato {nombre}?",
            "a": (
                f"{resumen} Es el precio de góndola que publica cada cadena, "
                "no el de una sucursal ni el precio con promo bancaria."
            ),
        },
        {"q": "¿El precio incluye promos bancarias?", "a": promo_txt},
    ]


def _gtin(ean: str) -> dict[str, str]:
    digits = re.sub(r"\D", "", ean or "")
    if len(digits) in {8, 12, 13, 14}:
        return {f"gtin{len(digits)}": digits}
    return {}


def armar_vista(spec: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any] | None:
    """Vista de una página. None si el dato no alcanza para publicarla."""
    nombre = " ".join(str(raw.get("nombre") or "").split())
    if not nombre or not _pasa(nombre, list(spec.get("incluye") or []), list(spec.get("excluye") or [])):
        return None
    ofertas = _ofertas_validas(raw.get("ofertas") or [])
    if len(ofertas) < MIN_CADENAS:
        return None
    capturado = str(raw.get("capturado") or "")
    try:
        datetime.fromisoformat(capturado)
    except ValueError:
        return None
    texto = str(raw.get("capturado_texto") or _texto_captura(datetime.fromisoformat(capturado)))
    low = min(o["precio"] for o in ofertas)
    high = max(o["precio"] for o in ofertas)
    resumen = resumen_precios(ofertas)
    promos = _promos(ofertas)
    faq = _faq(nombre, resumen, len(ofertas), texto, promos)
    href = f"{PATH_HUB}/{spec['slug']}"
    canonical = ORIGEN + href
    title = _titulo(nombre)
    description = _descripcion(nombre, ofertas, resumen)
    marca = str(raw.get("marca") or "").strip()
    product: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": nombre,
        "description": description,
        "category": spec["categoria"],
    }
    if marca:
        product["brand"] = {"@type": "Brand", "name": marca}
    product.update(_gtin(str(raw.get("ean") or "")))
    offers = []
    for oferta in ofertas:
        offer: dict[str, Any] = {
            "@type": "Offer",
            "price": precio_schema(oferta["precio"]),
            "priceCurrency": "ARS",
            "availability": "https://schema.org/InStock",
            "seller": {"@type": "Organization", "name": oferta["tienda"]},
        }
        if oferta["url"]:
            offer["url"] = oferta["url"]
        offers.append(offer)
    product["offers"] = {
        "@type": "AggregateOffer",
        "lowPrice": precio_schema(low),
        "highPrice": precio_schema(high),
        "offerCount": len(ofertas),
        "priceCurrency": "ARS",
        "offers": offers,
    }
    filas = []
    for oferta in ofertas:
        filas.append({
            **oferta,
            "precio_txt": peso(oferta["precio"]),
            "barato": oferta["precio"] == low,
            "fecha": _fecha_corta(capturado),
        })
    return {
        "slug": spec["slug"],
        "categoria": spec["categoria"],
        "nombre": nombre,
        "marca": marca,
        "tamano": str(raw.get("tamano") or "").strip(),
        "ean": str(raw.get("ean") or ""),
        "title": title,
        "description": description,
        "h1": f"Precio de {nombre} hoy en supermercados",
        "canonical": canonical,
        "href": href,
        "resumen": resumen,
        "capturado": capturado,
        "capturado_texto": texto,
        "fecha": _fecha_corta(capturado),
        "lastmod": _lastmod(capturado),
        "ofertas": filas,
        "n": len(filas),
        "low": low,
        "high": high,
        "promos": promos,
        "faq": faq,
        "ld_product": _ld(product),
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
                {"@type": "ListItem", "position": 1, "name": "Inicio", "item": ORIGEN + "/"},
                {"@type": "ListItem", "position": 2, "name": "Comparar precios", "item": ORIGEN + PATH_HUB},
                {"@type": "ListItem", "position": 3, "name": nombre, "item": canonical},
            ],
        }),
    }


def reiniciar_cache() -> None:
    global _mem
    _mem = None


def _mezclar_tmp(data: dict[str, Any]) -> None:
    if not RUTA_TMP.is_file():
        return
    try:
        alt = json.loads(RUTA_TMP.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(alt, dict) or not isinstance(alt.get("productos"), list):
        return
    by = {p.get("slug"): p for p in data.get("productos") or [] if isinstance(p, dict)}
    for prod in alt["productos"]:
        if not isinstance(prod, dict) or not prod.get("slug"):
            continue
        prev = by.get(prod["slug"])
        if prev is None or str(prod.get("capturado") or "") > str(prev.get("capturado") or ""):
            by[prod["slug"]] = prod
    data["productos"] = list(by.values())


def cargar() -> dict[str, Any]:
    global _mem
    if _mem is not None:
        return _mem
    try:
        data = json.loads(RUTA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {"productos": []}
    if not isinstance(data, dict):
        data = {"productos": []}
    if not isinstance(data.get("productos"), list):
        data["productos"] = []
    _mezclar_tmp(data)
    _mem = data
    return data


def _persistir(data: dict[str, Any]) -> None:
    texto = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    try:
        RUTA.write_text(texto, encoding="utf-8")
        return
    except OSError:
        pass
    try:
        RUTA_TMP.write_text(texto, encoding="utf-8")
    except OSError:
        pass


def _crudo(slug: str) -> dict[str, Any] | None:
    for prod in cargar().get("productos") or []:
        if isinstance(prod, dict) and prod.get("slug") == slug:
            return prod
    return None


def _viejo(iso: str | None) -> bool:
    if not iso:
        return True
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ART)
    return datetime.now(ART) - dt > timedelta(hours=HORAS_FRESCURA)


def vistas_publicadas() -> list[dict[str, Any]]:
    by = {
        p.get("slug"): p
        for p in cargar().get("productos") or []
        if isinstance(p, dict)
    }
    out: list[dict[str, Any]] = []
    for spec in CATALOGO:
        raw = by.get(spec["slug"])
        if not isinstance(raw, dict):
            continue
        vista = armar_vista(spec, raw)
        if vista is not None:
            out.append(vista)
    return out


def _con_otros(vista: dict[str, Any], todas: list[dict[str, Any]]) -> dict[str, Any]:
    vista = dict(vista)
    vista["otros"] = [
        {"href": otra["href"], "nombre": otra["nombre"]}
        for otra in todas
        if otra["categoria"] == vista["categoria"] and otra["slug"] != vista["slug"]
    ][:6]
    return vista


def pagina_precios() -> dict[str, Any]:
    productos = vistas_publicadas()
    grupos = []
    for categoria in CATEGORIAS:
        items = [p for p in productos if p["categoria"] == categoria]
        if items:
            grupos.append({"categoria": categoria, "productos": items})
    n = len(productos)
    if productos:
        reciente = max(productos, key=lambda p: p["capturado"])
        actualizado = reciente["capturado_texto"]
        lastmod = max(p["lastmod"] for p in productos)
    else:
        actualizado = ""
        lastmod = ""
    description = (
        f"Precios de {n} productos básicos en supermercados. "
        "El más barato sale del catálogo público, con la fecha de captura."
    )
    if len(description) > 155:
        description = description[:155].rsplit(" ", 1)[0].rstrip(".,;") + "."
    faq = [
        {
            "q": "¿Cómo se comparan los precios?",
            "a": (
                f"Esta página lista {n} productos con precio de góndola en al menos dos cadenas. "
                "El número sale del catálogo público que ya consulta BaratoYa. No se escribe un precio a mano."
            ),
        },
        {
            "q": "¿El precio incluye promos bancarias?",
            "a": (
                "No. Es el precio de góndola, sin descuento de banco. "
                "Las promos bancarias de supermercados están en su propia página."
            ),
        },
        {
            "q": "¿De cuándo es el precio?",
            "a": (
                "Cada producto muestra la fecha y la hora de la captura, en hora de Buenos Aires. "
                "Si la captura tiene más de un día, la página vuelve a leer el catálogo."
            ),
        },
    ]
    return {
        "title": HUB_TITLE,
        "description": description,
        "h1": HUB_H1,
        "canonical": ORIGEN + PATH_HUB,
        "n": n,
        "grupos": grupos,
        "actualizado": actualizado,
        "lastmod": lastmod,
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
                {"@type": "ListItem", "position": 1, "name": "Inicio", "item": ORIGEN + "/"},
                {"@type": "ListItem", "position": 2, "name": "Comparar precios", "item": ORIGEN + PATH_HUB},
            ],
        }),
    }


def pagina_producto(slug: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[a-z0-9-]{3,80}", slug or ""):
        return None
    todas = vistas_publicadas()
    for vista in todas:
        if vista["slug"] == slug:
            return _con_otros(vista, todas)
    return None


def muestra_home() -> list[dict[str, str]]:
    by = {p["slug"]: p for p in vistas_publicadas()}
    out = []
    for slug in MUESTRA_SLUGS:
        vista = by.get(slug)
        if vista:
            out.append({"href": vista["href"], "nombre": vista["nombre"]})
    return out


def urls_sitemap() -> list[tuple[str, str]]:
    productos = vistas_publicadas()
    if not productos:
        return []
    last = max(p["lastmod"] for p in productos)
    urls = [(ORIGEN + PATH_HUB, last)]
    for vista in productos:
        urls.append((vista["canonical"], vista["lastmod"]))
    return urls


def _offline() -> bool:
    return os.getenv("BARATOYA_PRECIOS_OFFLINE") == "1"


async def leer_en_vivo(spec: dict[str, Any]) -> dict[str, Any] | None:
    cuando = datetime.now(ART)
    data = await buscar_super(spec["q"], [spec["q"]])
    grupos = agrupar_mismo_producto(
        spec["q"],
        data.get("productos") or [],
        leido=cuando.isoformat(timespec="seconds"),
        con_promo=False,
    )
    grupo, ofertas = elegir_grupo(grupos, spec)
    if grupo is None:
        return None
    return armar_captura(spec, grupo, ofertas, cuando)


def _reemplazar(prod: dict[str, Any]) -> None:
    data = cargar()
    productos = [p for p in data.get("productos") or [] if isinstance(p, dict) and p.get("slug") != prod["slug"]]
    productos.append(prod)
    data["productos"] = productos
    _persistir(data)


async def asegurar_producto(slug: str) -> None:
    """Si la captura de este producto tiene más de un día, vuelve a leer el catálogo."""
    if _offline():
        return
    spec = _SPEC.get(slug)
    if spec is None:
        return
    actual = _crudo(slug)
    if actual is not None and not _viejo(str(actual.get("capturado") or "")):
        return
    async with _lock:
        actual = _crudo(slug)
        if actual is not None and not _viejo(str(actual.get("capturado") or "")):
            return
        try:
            nuevo = await asyncio.wait_for(leer_en_vivo(spec), timeout=25)
        except Exception:
            return
        if nuevo is None:
            return
        _reemplazar(nuevo)


async def _refrescar_varios(slugs: list[str]) -> None:
    sem = asyncio.Semaphore(4)

    async def uno(slug: str) -> None:
        async with sem:
            await asegurar_producto(slug)

    await asyncio.gather(*[uno(slug) for slug in slugs])


async def asegurar_hub() -> None:
    """Relee los productos vencidos. Si no alcanza el tiempo, queda la captura anterior."""
    if _offline():
        return
    slugs = []
    for spec in CATALOGO:
        actual = _crudo(spec["slug"])
        if actual is None or _viejo(str(actual.get("capturado") or "")):
            slugs.append(spec["slug"])
    if not slugs:
        return
    try:
        await asyncio.wait_for(_refrescar_varios(slugs), timeout=15)
    except asyncio.TimeoutError:
        return


async def capturar_todo() -> dict[str, Any]:
    sem = asyncio.Semaphore(3)

    async def uno(spec: dict[str, Any]) -> dict[str, Any] | None:
        async with sem:
            try:
                prod = await leer_en_vivo(spec)
            except Exception as exc:
                print(f"ERR {spec['slug']} {exc}")
                return None
            if prod is None:
                print(f"SKIP {spec['slug']} {spec['q']}")
                return None
            low = min(o["precio"] for o in prod["ofertas"])
            print(f"OK {spec['slug']} n={len(prod['ofertas'])} {prod['nombre']} desde {low}")
            return prod

    crudos = [p for p in await asyncio.gather(*[uno(spec) for spec in CATALOGO]) if p]
    orden = {spec["slug"]: i for i, spec in enumerate(CATALOGO)}
    crudos.sort(key=lambda p: orden[p["slug"]])
    vistos: set[str] = set()
    productos = []
    for prod in crudos:
        ean = prod.get("ean") or ""
        if ean and ean in vistos:
            print(f"DUP {prod['slug']} {ean}")
            continue
        if ean:
            vistos.add(ean)
        productos.append(prod)
    return {
        "fuente": "catalogos_publicos",
        "nota": (
            "Precios de góndola leídos con buscar_super, el mismo camino que la búsqueda "
            "de la app (catálogos VTEX públicos). No hay precios escritos a mano. "
            "Un producto con menos de dos cadenas no entra."
        ),
        "productos": productos,
    }


def guardar_captura(data: dict[str, Any], ruta: Path | None = None) -> None:
    dest = ruta or RUTA
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reiniciar_cache()


if __name__ == "__main__":
    captura = asyncio.run(capturar_todo())
    guardar_captura(captura)
    print(f"publicados {len(captura['productos'])} -> {RUTA}")
