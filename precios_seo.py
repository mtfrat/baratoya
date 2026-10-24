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
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

try:
    from baratoya.promos_hoy import cadenas_indexables, hoy_art, nav_dias, promos_de_hoy_por_cadena
    from baratoya.super_cadenas import agrupar_mismo_producto, buscar_super
except ImportError:
    from promos_hoy import cadenas_indexables, hoy_art, nav_dias, promos_de_hoy_por_cadena
    from super_cadenas import agrupar_mismo_producto, buscar_super

ART = timezone(timedelta(hours=-3))
ORIGEN = "https://baratoya.app"
PATH_HUB = "/precios"
RUTA = Path(__file__).parent / "data" / "precios-publicos.json"
RUTA_TMP = Path("/tmp/baratoya-precios-publicos.json")
MIN_CADENAS = 2
# Un hub de commodity sale solo con 3 SKU comparables, cada uno en 3 cadenas.
MIN_SKUS_COMMODITY = 3
MIN_CADENAS_COMMODITY = 3
HORAS_FRESCURA = 24

# ≤60. La query va primero; CABA es el alcance real, el mismo que el resto del sitio.
HUB_TITLE = "Comparar precios de supermercados hoy en CABA | BaratoYa"
HUB_H1 = "Comparar precios de supermercados hoy en CABA"
HUB_INTRO = (
    "Comparar precios de supermercados hoy en CABA: el precio de góndola que publica cada cadena. "
    "Se actualiza al releer el catálogo público si la captura tiene más de un día. "
    "Entrá por categoría o por producto. Si un precio no está publicado, no lo completamos."
)
# Orden del hub de promos. Un nombre que no esté acá igual entra, al final.
_ORDEN_CADENA_PRECIO = (
    "Día",
    "Carrefour",
    "Jumbo",
    "Disco",
    "Vea",
    "Mas Online",
    "Makro",
    "Maxiconsumo",
    "Josimar",
    "El Abastecedor",
)
_ANCLAS_PROMOS = (
    ("promos bancarias de supermercados", "/promos-bancarias-supermercados"),
    ("descuentos por día", "/descuentos-supermercados"),
)
CATEGORIAS = ("Lácteos", "Almacén", "Bebidas", "Limpieza")
# /precios/<slug> es la ficha. La categoría va un segmento más abajo para no pisarla.
PATH_CATEGORIA = "/precios/categoria"
_CATEGORIA_SLUG = {
    "Lácteos": "lacteos",
    "Almacén": "almacen",
    "Bebidas": "bebidas",
    "Limpieza": "limpieza",
}
_SLUG_CATEGORIA = {slug: nombre for nombre, slug in _CATEGORIA_SLUG.items()}
CATEGORIA_TITLE = {
    "Lácteos": "Precios de lácteos hoy en supermercados | BaratoYa",
    "Almacén": "Precios de almacén hoy en supermercados | BaratoYa",
    "Bebidas": "Precios de bebidas hoy en supermercados | BaratoYa",
    "Limpieza": "Precios de limpieza hoy en supermercados | BaratoYa",
}
_CATEGORIA_INTRO = {
    "Lácteos": (
        "Leche, manteca, yogur, queso y dulce de leche. "
        "El precio de góndola que publica cada cadena, con la fecha de la captura."
    ),
    "Almacén": (
        "Aceite, yerba, harina, arroz y fideos. "
        "El número sale del catálogo público: si una cadena no lo publica, no lo completamos."
    ),
    "Bebidas": (
        "Agua, gaseosa, cerveza y té. "
        "Cada producto compara el precio de góndola en las cadenas que lo tienen publicado."
    ),
    "Limpieza": (
        "Lavandina, jabón en polvo y papel higiénico. "
        "El más barato es el menor precio publicado, con la cadena que lo muestra."
    ),
}
# /precios/<slug> es la ficha. Un hub de producto puntual (leche, yerba) usa el
# mismo segmento, con un slug corto que no puede coincidir con una ficha.
COMMODITIES: tuple[dict[str, Any], ...] = (
    {
        "slug": "leche",
        "nombre": "Leche",
        "etiqueta": "leche",
        "varios": "leches",
        "categoria": "Lácteos",
        "title": "Precio de la leche hoy en supermercados | BaratoYa",
        "anchor": "Precio de la leche hoy",
        "intro": (
            "Leche líquida, en sachet o larga vida, entera o descremada. "
            "El precio de góndola que publica cada cadena, con la fecha de la captura."
        ),
        "nota": "Manteca, yogur, queso y dulce de leche no forman parte de esta lista.",
        "prefijo": "leche-",
        "excluye_slug": ("polvo", "condensada", "chocolatada", "dulce"),
        "faq_precio": "¿Cuál es el precio de la leche hoy?",
        "faq_donde": "¿Dónde está más barata la leche?",
        "articulo_barato": "La más barata",
    },
    {
        "slug": "yerba",
        "nombre": "Yerba",
        "etiqueta": "yerba",
        "varios": "yerbas",
        "categoria": "Almacén",
        "title": "Precio de la yerba hoy en supermercados | BaratoYa",
        "anchor": "Precio de la yerba hoy",
        "intro": (
            "Yerba en paquete. "
            "El número sale del catálogo público: si una cadena no lo publica, no lo completamos."
        ),
        "nota": "",
        "prefijo": "yerba-",
        "excluye_slug": ("mate-cocido", "cancha"),
        "faq_precio": "¿Cuál es el precio de la yerba hoy?",
        "faq_donde": "¿Dónde está más barata la yerba?",
        "articulo_barato": "La más barata",
    },
    {
        "slug": "aceite",
        "nombre": "Aceite",
        "etiqueta": "aceite",
        "varios": "aceites",
        "categoria": "Almacén",
        "title": "Precio del aceite hoy en supermercados | BaratoYa",
        "anchor": "Precio del aceite hoy",
        "intro": (
            "Aceite de girasol en botella. "
            "El número sale del catálogo público: si una cadena no lo publica, no lo completamos."
        ),
        "nota": "Aceite de oliva, aceitunas y aceite en aerosol no forman parte de esta lista.",
        "prefijo": "aceite-",
        "excluye_slug": ("oliva", "aceituna", "aerosol", "spray"),
        "faq_precio": "¿Cuál es el precio del aceite hoy?",
        "faq_donde": "¿Dónde está más barato el aceite?",
        "articulo_barato": "El más barato",
    },
    {
        "slug": "harina",
        "nombre": "Harina",
        "etiqueta": "harina",
        "varios": "harinas",
        "categoria": "Almacén",
        "title": "Precio de la harina hoy en supermercados | BaratoYa",
        "anchor": "Precio de la harina hoy",
        "intro": (
            "Harina de trigo en paquete de 1 kg. "
            "El precio de góndola que publica cada cadena, con la fecha de la captura."
        ),
        "nota": "Harina leudante, integral y de maíz no forman parte de esta lista.",
        "prefijo": "harina-",
        "excluye_slug": ("leudante", "integral", "maiz", "premezcla"),
        "faq_precio": "¿Cuál es el precio de la harina hoy?",
        "faq_donde": "¿Dónde está más barata la harina?",
        "articulo_barato": "La más barata",
    },
)
_COMMODITY = {item["slug"]: item for item in COMMODITIES}
_FOCO_CATEGORIA = {
    "Lácteos": {
        "prefijo": "leche-",
        "q": "¿Cuál es el precio de la leche hoy en el supermercado?",
        "varios": "leches",
    },
    "Almacén": {
        "prefijo": "yerba-",
        "q": "¿Cuál es el precio de la yerba hoy?",
        "varios": "yerbas",
    },
    "Bebidas": {
        "prefijo": "coca-cola",
        "q": "¿Cuál es el precio de la Coca-Cola hoy en el supermercado?",
        "varios": "presentaciones",
    },
    "Limpieza": {
        "prefijo": "lavandina-",
        "q": "¿Cuál es el precio de la lavandina hoy?",
        "varios": "lavandinas",
    },
}
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
_CHOQUE_COMMODITY = {item["slug"] for item in COMMODITIES} & set(_SPEC)
if _CHOQUE_COMMODITY:
    raise RuntimeError(f"un hub de producto pisa una ficha: {sorted(_CHOQUE_COMMODITY)}")
_mem: dict[str, Any] | None = None


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


def texto_mas_barato(ofertas: list[dict[str, Any]]) -> str:
    """Precio mínimo y las cadenas que lo publican. La misma cuenta que el resumen."""
    low = min(o["precio"] for o in ofertas)
    quienes = _lista_y([o["tienda"] for o in ofertas if o["precio"] == low])
    return f"{quienes} a {peso(low)}"


def frase_mas_barato(productos: list[dict[str, Any]]) -> str:
    """El menor precio de góndola entre varios productos, con cadena y nombre."""
    low = min(o["precio"] for p in productos for o in p["ofertas"])
    partes = []
    for producto in productos:
        baratas = [o for o in producto["ofertas"] if o["precio"] == low]
        if not baratas:
            continue
        quienes = _lista_y([o["tienda"] for o in baratas])
        nombre = str(producto["nombre_visible"]).rstrip(".")
        partes.append(f"{nombre} en {quienes} a {peso(low)}")
    return _lista_y(partes)


def resumen_precios(ofertas: list[dict[str, Any]]) -> str:
    low = min(o["precio"] for o in ofertas)
    high = max(o["precio"] for o in ofertas)
    monto = peso(low)
    if high == low:
        return f"Hoy el precio publicado es {monto} en todas las cadenas de esta página."
    mejor = texto_mas_barato(ofertas)
    pct = int(round((high - low) / high * 100))
    if pct <= 0:
        return f"Hoy el más barato es {mejor}, menos de 1% por debajo del más caro."
    return f"Hoy el más barato es {mejor}, {pct}% menos que el más caro."


# Relleno de góndola: se saca sólo si el título no entra en 60.
# No son la marca ni el tamaño (Sabor, Entera, Gaseosa, Original, 3%).
_RELLENO = frozenset({
    "sabor", "sabores",
    "entera", "entero",
    "gaseosa", "gaseosas",
    "original", "originales",
    "clasico", "clasica",
    "fortificada", "fortificado",
})
_UNIDADES = frozenset({
    "l", "lt", "lts", "litro", "litros",
    "ml", "cc",
    "g", "gr", "grs", "gramo", "gramos", "grm",
    "kg", "kgs", "kilo", "kilos",
    "ud", "uds", "un", "uni", "unidad", "unidades",
})
# Forma corta única en el título visible. El dato guardado no se reescribe.
_UNIDAD_CANON = {
    "l": "L", "lt": "L", "lts": "L", "litro": "L", "litros": "L",
    "ml": "ml", "cc": "ml",
    "g": "g", "gr": "g", "grs": "g", "gramo": "g", "gramos": "g", "grm": "g",
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg",
    "ud": "un", "uds": "un", "un": "un", "uni": "un",
    "unidad": "un", "unidades": "un",
}
# Conteo de empaque: se separa del número, pero se suelta antes que g/kg/ml/L/un.
_CONTEO = frozenset({"sachet", "sachets", "saquito", "saquitos"})
_SAQ = frozenset({"saq", "saqs"})
_ACRONIMOS = frozenset({"uat", "uht", "pet"})
# Acentos que las cadenas suelen perder. La marca va en _MARCAS.
_ACENTOS = {
    "jabon": "Jabón",
    "te": "Té",
    "azucar": "Azúcar",
    "atun": "Atún",
    "clasico": "Clásico",
    "clasica": "Clásica",
    "comun": "Común",
    "cafe": "Café",
    "higienico": "Higiénico",
}
# Grafía oficial. La clave está plegada (sin acento, sin guion).
# Taragüí es la marca; en el buscador también se escribe Taragui.
_MARCAS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("la", "serenisima"), "La Serenísima"),
    (("la", "virginia"), "La Virginia"),
    (("la", "campagnola"), "La Campagnola"),
    (("coca", "cola"), "Coca-Cola"),
    (("cocacola",), "Coca-Cola"),
    (("serenisima",), "Serenísima"),
    (("campagnola",), "Campagnola"),
    (("taragui",), "Taragüí"),
    (("ilolay",), "Ilolay"),
    (("tregar",), "Tregar"),
    (("natura",), "Natura"),
    (("cocinero",), "Cocinero"),
    (("canuelas",), "Cañuelas"),
    (("ledesma",), "Ledesma"),
    (("pureza",), "Pureza"),
    (("favorita",), "Favorita"),
    (("playadito",), "Playadito"),
    (("union",), "Unión"),
    (("matarazzo",), "Matarazzo"),
    (("lucchetti",), "Lucchetti"),
    (("luchetti",), "Lucchetti"),
    (("gallo",), "Gallo"),
    (("celusal",), "Celusal"),
    (("criollitas",), "Criollitas"),
    (("arcor",), "Arcor"),
    (("villavicencio",), "Villavicencio"),
    (("quilmes",), "Quilmes"),
    (("ayudin",), "Ayudín"),
    (("ala",), "Ala"),
    (("higienol",), "Higienol"),
)
_MARCAS_ORD = tuple(sorted(_MARCAS, key=lambda it: len(it[0]), reverse=True))
_UAT_PUNTEADO = re.compile(r"(?i)\bu\.a\.t\.?")
_PEGADO = re.compile(r"(\d+(?:[.,]\d+)?)(?=[A-Za-zÁÉÍÓÚÜÑáéíóúüñ])")
# Token corto que no puede cerrar el título: La, De, El, Y.
_SUELTO = frozenset({
    "la", "de", "el", "y", "e", "o", "al", "del",
    "las", "los", "lo", "le", "en", "con", "sin", "por",
})
_ARTICULO_MARCA = frozenset({"la", "el", "los", "las"})
_PCT = re.compile(r"^\d+(?:[.,]\d+)?%$")
_NUM = re.compile(r"^\d+(?:[.,]\d+)?$")
_SUFIJO_TITULO = " | BaratoYa"
_TOPE_TITULO = 60


def _bare(tok: str) -> str:
    return _fold(tok).strip(".,;:()[]\"'«»")


def _clave(tok: str) -> str:
    return _bare(tok).replace("-", "")


def _es_relleno(tok: str) -> bool:
    bare = _bare(tok)
    return bare in _RELLENO or bool(_PCT.fullmatch(bare))


def _es_numero(tok: str) -> bool:
    return bool(_NUM.fullmatch(_bare(tok)))


def _es_unidad(tok: str) -> bool:
    return _bare(tok) in _UNIDADES


def _es_conteo(tok: str) -> bool:
    return _bare(tok) in _CONTEO


def _canon_unidad(tok: str) -> str | None:
    """g, kg, ml, L o un. None si el token no es una unidad."""
    bare = tok.strip().strip(".").lower()
    return _UNIDAD_CANON.get(bare)


def _es_uat(tok: str) -> bool:
    return _fold(tok).replace(".", "") == "uat"


def _deshout(tok: str) -> str:
    """Baja un grito (CRIOLLITAS) y deja quieto un acrónimo (UAT)."""
    letras = [c for c in tok if c.isalpha()]
    if len(letras) < 2 or not all(c.isupper() for c in letras):
        return tok
    clave = re.sub(r"[^a-z]", "", _fold(tok))
    if clave in _ACRONIMOS:
        return clave.upper()
    bajo = tok.lower()
    return bajo[:1].upper() + bajo[1:]


def _acento(tok: str) -> str:
    canon = _ACENTOS.get(_fold(tok).strip("."))
    if not canon:
        return tok
    if tok[:1].islower():
        return canon[:1].lower() + canon[1:]
    return canon


def _aplicar_marcas(tokens: list[str]) -> list[str]:
    claves = [_clave(t) for t in tokens]
    out: list[str] = []
    i = 0
    while i < len(tokens):
        n = 0
        canon = ""
        for frase, escrito in _MARCAS_ORD:
            m = len(frase)
            if tuple(claves[i:i + m]) == frase:
                n = m
                canon = escrito
                break
        if n:
            out.extend(canon.split())
            i += n
            continue
        out.append(tokens[i])
        i += 1
    return out


def _nombre_visible(nombre: str) -> str:
    """Nombre para título, H1, meta y JSON-LD. No toca el dato ni el slug.

    Orden: UAT, tokens pegados (1sachet, 300g), unidad corta, marca oficial,
    palabras en mayúsculas y acentos comunes (Jabón, Té, Azúcar, Atún).
    """
    texto = " ".join(str(nombre or "").split())
    if not texto:
        return ""
    texto = _UAT_PUNTEADO.sub("UAT", texto)
    texto = _PEGADO.sub(r"\1 ", texto)
    tokens: list[str] = []
    for tok in texto.split():
        if _es_uat(tok):
            tokens.append("UAT")
            continue
        unidad = _canon_unidad(tok)
        tokens.append(unidad if unidad else tok)
    tokens = _aplicar_marcas(tokens)
    vistos: list[str] = []
    for tok in tokens:
        if _canon_unidad(tok) or _es_uat(tok):
            vistos.append(tok)
            continue
        tok = _deshout(tok)
        tok = _acento(tok)
        if _fold(tok).strip(".") in _SAQ:
            tok = "saquitos"
        vistos.append(tok)
    return " ".join(vistos)


def _es_suelto(tok: str, es_marca: bool = False) -> bool:
    """True si el token no puede quedar al final (La, De, El, Y, o ≤3 letras)."""
    bare = _bare(tok)
    if not bare or bare in _SUELTO:
        return True
    if es_marca or _es_unidad(tok) or _es_numero(tok):
        return False
    letras = re.sub(r"[^a-z]", "", bare)
    return bool(letras) and letras == bare and len(letras) <= 3


def _es_marca_guion(tok: str) -> bool:
    partes = [p for p in tok.split("-") if p]
    if len(partes) < 2:
        return False
    return all(len(re.sub(r"[^a-z]", "", _fold(p))) >= 2 for p in partes)


def _claves_marca(marca: str) -> list[str]:
    texto = _fold(marca).replace("/", " ").replace("-", " ")
    return [p.strip(".,;:") for p in texto.split() if p.strip(".,;:")]


def _indices_marca(tokens: list[str], marca: str) -> set[int]:
    """Dónde está la marca en el nombre: el campo `marca`, un guion (Coca-Cola) o La + palabra."""
    claves = [_clave(t) for t in tokens]
    idxs: set[int] = set()
    keys = _claves_marca(marca)
    if keys:
        n, m = len(claves), len(keys)
        for i in range(n - m + 1):
            if claves[i:i + m] == keys:
                idxs.update(range(i, i + m))
        if not idxs:
            for i, clave in enumerate(claves):
                if any(len(key) >= 4 and clave == key for key in keys):
                    idxs.add(i)
    for i, tok in enumerate(tokens):
        if _es_marca_guion(tok):
            idxs.add(i)
    for i in range(len(tokens) - 1):
        letras = re.sub(r"[^a-z]", "", claves[i + 1])
        if claves[i] in _ARTICULO_MARCA and len(letras) > 3:
            idxs.add(i)
            idxs.add(i + 1)
    for frase, _escrito in _MARCAS_ORD:
        m = len(frase)
        for i in range(len(claves) - m + 1):
            if tuple(claves[i:i + m]) == frase:
                idxs.update(range(i, i + m))
    return idxs


def _cierra_mal(partes: list[str], es_marca: bool = False) -> bool:
    """El título no puede cerrar en La/De/El/Y ni en una unidad sin su número."""
    if not partes:
        return False
    last = partes[-1]
    if _es_unidad(last):
        prev = partes[-2] if len(partes) > 1 else ""
        return not _es_numero(prev)
    return _es_suelto(last, es_marca)


def _corte_duro(texto: str, budget: int) -> str:
    """Último recurso: corta en un espacio y no deja número sin unidad ni token suelto."""
    if len(texto) <= budget:
        return texto.strip()
    recorte = texto[:budget]
    if budget < len(texto) and not texto[budget].isspace():
        recorte = recorte.rsplit(" ", 1)[0] or texto[:budget]
    partes = recorte.split()
    resto = texto[len(" ".join(partes)):].strip() if partes else ""
    while _cierra_mal(partes):
        partes.pop()
    if partes and _es_numero(partes[-1]):
        siguiente = resto.split()[0] if resto else ""
        if siguiente and _es_unidad(siguiente):
            partes.pop()
    while _cierra_mal(partes):
        partes.pop()
    return " ".join(partes).strip()


def _acortar_nombre(nombre: str, marca: str, budget: int) -> str:
    tokens = nombre.split()
    if not tokens:
        return ""
    marca_idx = _indices_marca(tokens, marca)
    items: list[dict[str, Any]] = []
    for i, tok in enumerate(tokens):
        items.append({"t": tok, "brand": i in marca_idx, "pair": None})
    for i in range(len(items) - 1):
        if _es_numero(items[i]["t"]) and (
            _es_unidad(items[i + 1]["t"]) or _es_conteo(items[i + 1]["t"])
        ):
            items[i]["pair"] = i
            items[i + 1]["pair"] = i
    # 1) Sacar relleno antes de cortar. La marca y el par número+unidad se quedan.
    sin_relleno = [
        it for it in items
        if it["brand"] or it["pair"] is not None or not _es_relleno(it["t"])
    ]
    if sin_relleno:
        items = sin_relleno

    def texto() -> str:
        return " ".join(it["t"] for it in items)

    def drop_index(idx: int) -> None:
        it = items[idx]
        if it["pair"] is not None:
            pid = it["pair"]
            items[:] = [x for x in items if x["pair"] != pid]
            return
        if it["brand"]:
            a = idx
            while a > 0 and items[a - 1]["brand"]:
                a -= 1
            b = idx
            while b + 1 < len(items) and items[b + 1]["brand"]:
                b += 1
            del items[a:b + 1]
            return
        del items[idx]

    def _par_canonico(it: dict[str, Any]) -> bool:
        if it["pair"] is None:
            return False
        pid = it["pair"]
        return any(x["pair"] == pid and _es_unidad(x["t"]) for x in items)

    # 2) Si sigue largo, soltar descriptores desde el final. La marca espera
    #    y el par número+unidad (1 L, 400 g, 4 un) también, hasta que no quede
    #    otra cosa. Un sachet o "25 saquitos" sale antes que ese par.
    while items and len(texto()) > budget:
        idx = next(
            (
                i for i in range(len(items) - 1, -1, -1)
                if not items[i]["brand"] and not _par_canonico(items[i])
            ),
            None,
        )
        if idx is None:
            idx = next((i for i in range(len(items) - 1, -1, -1) if not items[i]["brand"]), None)
        if idx is None:
            idx = len(items) - 1
        drop_index(idx)

    while _cierra_mal([it["t"] for it in items], bool(items and items[-1]["brand"])):
        items.pop()
    while items and _es_numero(items[-1]["t"]) and items[-1]["pair"] is not None:
        if any(x is not items[-1] and x["pair"] == items[-1]["pair"] for x in items):
            break
        items.pop()

    corto = texto()
    if len(corto) > budget:
        corto = _corte_duro(corto, budget)
    return corto


def _titulo(nombre: str, marca: str = "") -> str:
    """Precio {nombre} hoy | BaratoYa, siempre con la marca BaratoYa y a lo sumo 60 caracteres.

    El nombre pasa antes por `_nombre_visible` (marca, unidad, mayúsculas). Si no
    entra, primero saca relleno genérico y después recorta. No termina en un
    token suelto (La, De, El, Y), no separa un número de su unidad y prefiere
    conservar la marca del producto antes que un descriptor.
    """
    nombre = _nombre_visible(nombre)
    completo = f"Precio {nombre} hoy{_SUFIJO_TITULO}"
    if len(completo) <= _TOPE_TITULO:
        return completo
    budget = _TOPE_TITULO - len("Precio ") - len(" hoy") - len(_SUFIJO_TITULO)
    corto = _acortar_nombre(nombre, marca, budget).strip()
    if not corto:
        base = nombre.split()
        corto = (base[0] if base else nombre)[:budget].strip()
    titulo = f"Precio {corto} hoy{_SUFIJO_TITULO}"
    if len(titulo) > _TOPE_TITULO:
        corto = _corte_duro(corto, budget)
        titulo = f"Precio {corto} hoy{_SUFIJO_TITULO}"
    return titulo


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


def _href_categoria(categoria: str) -> str:
    return f"{PATH_CATEGORIA}/{_CATEGORIA_SLUG[categoria]}"


def _producto_en_commodity(slug: str, spec: dict[str, Any]) -> bool:
    if not str(slug).startswith(spec["prefijo"]):
        return False
    plano = _fold(slug).replace("_", "-")
    return not any(tok in plano for tok in spec.get("excluye_slug") or ())


def _commodity_por_producto(slug: str) -> dict[str, Any] | None:
    for spec in COMMODITIES:
        if _producto_en_commodity(slug, spec):
            return spec
    return None


def _href_commodity(spec: dict[str, Any]) -> str:
    return f"{PATH_HUB}/{spec['slug']}"


def _migas_producto(
    categoria: str,
    categoria_href: str,
    visible: str,
    canonical: str,
    commodity_nombre: str,
    commodity_href: str,
) -> list[dict[str, Any]]:
    migas = [
        ("Inicio", ORIGEN + "/"),
        ("Comparar precios", ORIGEN + PATH_HUB),
        (categoria, ORIGEN + categoria_href),
    ]
    if commodity_href:
        migas.append((commodity_nombre, ORIGEN + commodity_href))
    migas.append((visible, canonical))
    return [
        {"@type": "ListItem", "position": i, "name": nombre, "item": url}
        for i, (nombre, url) in enumerate(migas, start=1)
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
    mas_barato = texto_mas_barato(ofertas)
    promos = _promos(ofertas)
    visible = _nombre_visible(nombre)
    faq = _faq(visible, resumen, len(ofertas), texto, promos)
    href = f"{PATH_HUB}/{spec['slug']}"
    categoria_href = _href_categoria(spec["categoria"])
    commodity = _commodity_por_producto(spec["slug"])
    commodity_href = _href_commodity(commodity) if commodity else ""
    commodity_nombre = commodity["nombre"] if commodity else ""
    commodity_anchor = commodity["anchor"] if commodity else ""
    canonical = ORIGEN + href
    marca = str(raw.get("marca") or "").strip()
    title = _titulo(visible, marca)
    description = _descripcion(visible, ofertas, resumen)
    product: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": visible,
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
        "categoria_href": categoria_href,
        "commodity_href": commodity_href,
        "commodity_nombre": commodity_nombre,
        "commodity_anchor": commodity_anchor,
        "mas_barato": mas_barato,
        "nombre": nombre,
        "nombre_visible": visible,
        "marca": marca,
        "tamano": str(raw.get("tamano") or "").strip(),
        "ean": str(raw.get("ean") or ""),
        "title": title,
        "description": description,
        "h1": f"Precio de {visible} hoy en supermercados",
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
            "itemListElement": _migas_producto(
                spec["categoria"],
                categoria_href,
                visible,
                canonical,
                commodity_nombre,
                commodity_href,
            ),
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


def _viejo(iso: str | None, del_dia: bool = False) -> bool:
    """Más de 24 h. Con del_dia (cron diario), también si se capturó antes de hoy (ART).

    El cron corre a las 07:00 ART; la captura del día anterior suele ser de las 09:00, o sea
    22 h: con solo el corte de 24 h el cron no releía nada y las fechas quedaban en ayer.
    """
    if not iso:
        return True
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ART)
    ahora = datetime.now(ART)
    if del_dia and dt.astimezone(ART).date() < ahora.date():
        return True
    return ahora - dt > timedelta(hours=HORAS_FRESCURA)


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


OTROS_MAX = 8


def _con_otros(vista: dict[str, Any], todas: list[dict[str, Any]]) -> dict[str, Any]:
    """Otros productos de la categoría, en ventana circular desde esta ficha.

    Antes eran siempre los 6 primeros de la categoría: las fichas del final no
    recibían enlaces entre fichas. La ventana arranca en la siguiente y da la
    vuelta, así cada ficha queda enlazada desde las anteriores.
    """
    vista = dict(vista)
    misma = [otra for otra in todas if otra["categoria"] == vista["categoria"]]
    slugs = [otra["slug"] for otra in misma]
    i = slugs.index(vista["slug"]) if vista["slug"] in slugs else -1
    rotada = misma[i + 1:] + misma[:max(i, 0)] if i >= 0 else misma
    vista["otros"] = [
        {"href": otra["href"], "nombre": otra.get("nombre_visible") or otra["nombre"]}
        for otra in rotada
        if otra["slug"] != vista["slug"]
    ][:OTROS_MAX]
    return vista


def cadenas_en_precios(productos: list[dict[str, Any]]) -> list[str]:
    """Cadenas que publican al menos un precio. Sin inventar una que no esté."""
    presentes: set[str] = set()
    for producto in productos:
        for oferta in producto["ofertas"]:
            tienda = str(oferta.get("tienda") or "").strip()
            if tienda:
                presentes.add(tienda)
    orden = [nombre for nombre in _ORDEN_CADENA_PRECIO if nombre in presentes]
    resto = sorted(presentes - set(orden))
    return orden + resto


def _anclar(texto: str, anclas: tuple[tuple[str, str], ...]) -> str:
    html = texto
    for frase, href in anclas:
        if frase not in html:
            raise ValueError(f"ancla ausente: {frase}")
        html = html.replace(frase, f'<a href="{href}">{frase}</a>', 1)
    return html


def _descripcion_hub(n: int) -> str:
    """120–155. La query, CABA, que el precio se actualiza, y el CTA."""
    prod = "producto" if n == 1 else "productos"
    texto = (
        f"Comparar precios de supermercados hoy en CABA: {n} {prod} de góndola. "
        "El precio se actualiza con el catálogo público. Entrá por categoría o por producto."
    )
    if len(texto) > 155 or '"' in texto or "<" in texto:
        texto = texto[:155].rsplit(" ", 1)[0].rstrip(".,;") + "."
    return texto


def _faq_hub(n: int, cadenas: list[str], actualizado: str) -> list[dict[str, str]]:
    if n == 1:
        cuantos = "1 producto con precio de góndola"
    elif n:
        cuantos = f"{n} productos con precio de góndola"
    else:
        cuantos = "los productos con precio de góndola"
    if cadenas:
        quienes = (
            f"En esta página hay precio de {_lista_y(cadenas)}. "
            "Cada ficha incluye solo las cadenas que publican ese producto. "
            "Si una no lo muestra, no entra."
        )
    else:
        quienes = (
            "Entran las cadenas que publican el producto en el catálogo de CABA. "
            "Si una no muestra el precio, no la completamos."
        )
    cuando = (
        "Si la captura tiene más de un día, esta página vuelve a leer el catálogo público. "
        "Cada ficha muestra la fecha y la hora, en hora de Buenos Aires."
    )
    if actualizado:
        cuando += f" La captura más reciente es del {actualizado}."
    diferencia = (
        "No. El número de esta página es el precio de góndola, sin descuento de banco ni promo del día. "
        "Las promos bancarias de supermercados y los descuentos por día están en otras páginas "
        "y no cambian este precio."
    )
    return [
        {
            "q": "¿Cómo comparar precios de supermercados?",
            "a": (
                f"En esta página, por producto: {cuantos} en al menos dos cadenas de CABA. "
                "Entrá a una categoría o a una ficha. El número sale del catálogo público. "
                "Si una cadena no publica el precio, no lo completamos."
            ),
        },
        {
            "q": "¿Qué cadenas entran en la comparación?",
            "a": quienes,
        },
        {
            "q": "¿Cada cuánto se actualizan los precios?",
            "a": cuando,
        },
        {
            "q": "¿En qué se diferencia de las promos bancarias?",
            "a": diferencia,
            "html": _anclar(diferencia, _ANCLAS_PROMOS),
        },
    ]


def _relacionados() -> list[dict[str, str]]:
    """El día de hoy y las promos de Coto y Carrefour, si esas páginas existen."""
    hoy = next(d for d in nav_dias() if d["hoy"])
    por_slug = {c["slug"]: c for c in cadenas_indexables()}
    salida = [{
        "href": hoy["href"],
        "texto": "descuentos en supermercados hoy",
        "nota": hoy["nombre"],
    }]
    for slug, texto in (
        ("coto", "promos bancarias Coto"),
        ("carrefour", "promos bancarias Carrefour"),
    ):
        cadena = por_slug.get(slug)
        if cadena:
            salida.append({"href": cadena["href"], "texto": texto, "nota": ""})
    return salida


def _lastmod_hub(productos: list[dict[str, Any]]) -> str:
    """La captura más nueva, o el día en Argentina si el enlace de hoy es más reciente.

    El enlace al día de la semana cambia con el calendario. Una lastmod
    clavada en la captura se queda atrás.
    """
    hoy = datetime.now(ART).date().isoformat()
    if not productos:
        return hoy
    return max(hoy, *(p["lastmod"] for p in productos))


def pagina_precios() -> dict[str, Any]:
    productos = vistas_publicadas()
    grupos = []
    for categoria in CATEGORIAS:
        items = [p for p in productos if p["categoria"] == categoria]
        if items:
            grupos.append({
                "categoria": categoria,
                "href": _href_categoria(categoria),
                "productos": items,
                "commodities": enlaces_commodity(items, categoria),
            })
    n = len(productos)
    if productos:
        reciente = max(productos, key=lambda p: p["capturado"])
        actualizado = reciente["capturado_texto"]
    else:
        actualizado = ""
    cadenas = cadenas_en_precios(productos)
    faq = _faq_hub(n, cadenas, actualizado)
    return {
        "title": HUB_TITLE,
        "description": _descripcion_hub(n),
        "h1": HUB_H1,
        "intro": HUB_INTRO,
        "canonical": ORIGEN + PATH_HUB,
        "n": n,
        "grupos": grupos,
        "cadenas": cadenas,
        "relacionados": _relacionados(),
        "commodities": enlaces_commodity(productos),
        "actualizado": actualizado,
        "lastmod": _lastmod_hub(productos),
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


def _n_cadenas(productos: list[dict[str, Any]]) -> int:
    ids: set[str] = set()
    for producto in productos:
        for oferta in producto["ofertas"]:
            ids.add(str(oferta.get("tienda_id") or oferta["tienda"]))
    return len(ids)


def _descripcion_categoria(etiqueta: str, n: int, cadenas: int) -> str:
    """120–158 caracteres, con la cantidad real de productos y de cadenas."""
    prod = "producto" if n == 1 else "productos"
    cad = "supermercado" if cadenas == 1 else "supermercados"
    texto = (
        f"Precios de {etiqueta} hoy: {n} {prod} en {cadenas} {cad}. "
        "El más barato de cada uno sale del catálogo público, con la cadena y la fecha de captura."
    )
    if 120 <= len(texto) <= 158:
        return texto
    if len(texto) < 120:
        texto += " No se escribe un precio a mano."
    if len(texto) > 158:
        corto = (
            f"Precios de {etiqueta}: {n} {prod} en {cadenas} {cad}. "
            "El más barato sale del catálogo público, con la cadena y la fecha de captura."
        )
        texto = corto if len(corto) <= 158 else corto[:158].rsplit(" ", 1)[0].rstrip(".,;") + "."
    return texto


def _faq_foco(categoria: str, productos: list[dict[str, Any]]) -> dict[str, str] | None:
    foco = _FOCO_CATEGORIA.get(categoria)
    if not foco:
        return None
    matches = [p for p in productos if str(p["slug"]).startswith(foco["prefijo"])]
    if not matches:
        return None
    if len(matches) == 1:
        uno = matches[0]
        respuesta = f"{uno['resumen']} Es {uno['nombre_visible'].rstrip('.')}."
    else:
        lineas = " ".join(
            f"{p['nombre_visible'].rstrip('.')}: {p['mas_barato']}." for p in matches
        )
        respuesta = f"{lineas} Son {len(matches)} {foco['varios']} con precio en al menos dos cadenas."
    return {"q": foco["q"], "a": respuesta}


def _faq_categoria(
    categoria: str,
    etiqueta: str,
    productos: list[dict[str, Any]],
    n_cadenas: int,
) -> list[dict[str, str]]:
    n = len(productos)
    prod = "producto" if n == 1 else "productos"
    cad = "supermercado" if n_cadenas == 1 else "supermercados"
    reciente = max(productos, key=lambda p: p["capturado"])
    faq = [
        {
            "q": f"¿Cuáles son los precios de {etiqueta} hoy?",
            "a": (
                f"Hay {n} {prod} de {etiqueta} con precio en {n_cadenas} {cad}. "
                "En cada ficha, el más barato es el menor precio de góndola publicado. "
                f"Captura más reciente: {reciente['capturado_texto']}."
            ),
        }
    ]
    foco = _faq_foco(categoria, productos)
    if foco:
        faq.append(foco)
    faq.extend([
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
                "Cada producto muestra la fecha de captura, en hora de Buenos Aires. "
                f"La más reciente de {etiqueta} es del {reciente['capturado_texto']}."
            ),
        },
    ])
    return faq


def _armar_categoria(nombre: str, todas: list[dict[str, Any]]) -> dict[str, Any] | None:
    productos = [p for p in todas if p["categoria"] == nombre]
    if not productos:
        return None
    etiqueta = nombre.casefold()
    n = len(productos)
    cadenas = _n_cadenas(productos)
    title = CATEGORIA_TITLE[nombre]
    h1 = title.removesuffix(" | BaratoYa")
    href = _href_categoria(nombre)
    canonical = ORIGEN + href
    reciente = max(productos, key=lambda p: p["capturado"])
    faq = _faq_categoria(nombre, etiqueta, productos, cadenas)
    otras = [
        {"href": _href_categoria(otra), "nombre": otra}
        for otra in CATEGORIAS
        if otra != nombre and any(p["categoria"] == otra for p in todas)
    ]
    return {
        "title": title,
        "description": _descripcion_categoria(etiqueta, n, cadenas),
        "h1": h1,
        "canonical": canonical,
        "href": href,
        "categoria": nombre,
        "titulo_miga": nombre,
        "etiqueta": etiqueta,
        "intro": _CATEGORIA_INTRO[nombre],
        "nota": "",
        "padre": None,
        "commodities": enlaces_commodity(productos, nombre),
        "n": n,
        "n_cadenas": cadenas,
        "productos_txt": f"{n} {'producto' if n == 1 else 'productos'}",
        "cadenas_txt": f"{cadenas} {'supermercado' if cadenas == 1 else 'supermercados'}",
        "productos": productos,
        "actualizado": reciente["capturado_texto"],
        "lastmod": max(p["lastmod"] for p in productos),
        "faq": faq,
        "otras": otras,
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
        "ld_itemlist": _ld({
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": h1,
            "numberOfItems": n,
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i,
                    "name": p["nombre_visible"],
                    "url": p["canonical"],
                }
                for i, p in enumerate(productos, start=1)
            ],
        }),
        "ld_breadcrumb": _ld({
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Inicio", "item": ORIGEN + "/"},
                {"@type": "ListItem", "position": 2, "name": "Precios", "item": ORIGEN + PATH_HUB},
                {"@type": "ListItem", "position": 3, "name": nombre, "item": canonical},
            ],
        }),
    }


def pagina_categoria(slug: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[a-z0-9-]{3,40}", slug or ""):
        return None
    nombre = _SLUG_CATEGORIA.get(slug)
    if nombre is None:
        return None
    return _armar_categoria(nombre, vistas_publicadas())


def paginas_categoria() -> list[dict[str, Any]]:
    todas = vistas_publicadas()
    out: list[dict[str, Any]] = []
    for nombre in CATEGORIAS:
        pagina = _armar_categoria(nombre, todas)
        if pagina is not None:
            out.append(pagina)
    return out


def enlaces_categoria() -> list[dict[str, str]]:
    publicados = {p["categoria"] for p in vistas_publicadas()}
    return [
        {"href": _href_categoria(nombre), "nombre": nombre, "etiqueta": nombre.casefold()}
        for nombre in CATEGORIAS
        if nombre in publicados
    ]


def commodity_conocida(slug: str) -> bool:
    if not re.fullmatch(r"[a-z0-9-]{3,40}", slug or ""):
        return False
    return slug in _COMMODITY


def _productos_commodity(spec: dict[str, Any], todas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """SKU del hub: el prefijo, sin lo que el filtro saca, y con precio en 3 cadenas."""
    return [
        p for p in todas
        if _producto_en_commodity(p["slug"], spec) and int(p.get("n") or 0) >= MIN_CADENAS_COMMODITY
    ]


def _hub_publicado(productos: list[dict[str, Any]]) -> bool:
    return (
        len(productos) >= MIN_SKUS_COMMODITY
        and _n_cadenas(productos) >= MIN_CADENAS_COMMODITY
    )


def enlaces_commodity(
    productos: list[dict[str, Any]] | None = None,
    categoria: str | None = None,
) -> list[dict[str, str]]:
    if productos is None:
        productos = vistas_publicadas()
    out: list[dict[str, str]] = []
    for spec in COMMODITIES:
        if categoria is not None and spec["categoria"] != categoria:
            continue
        if not _hub_publicado(_productos_commodity(spec, productos)):
            continue
        out.append({
            "href": _href_commodity(spec),
            "nombre": spec["nombre"],
            "etiqueta": spec["etiqueta"],
            "anchor": spec["anchor"],
            "categoria": spec["categoria"],
        })
    return out


def _captura_menor_precio(productos: list[dict[str, Any]]) -> str:
    """Fecha de captura del menor precio de góndola, no la más nueva de la lista."""
    low = min(o["precio"] for p in productos for o in p["ofertas"])
    fechas: list[str] = []
    for producto in productos:
        if any(o["precio"] == low for o in producto["ofertas"]):
            texto = str(producto["capturado_texto"])
            if texto not in fechas:
                fechas.append(texto)
    return _lista_y(fechas)


def _faq_commodity(
    spec: dict[str, Any],
    productos: list[dict[str, Any]],
    n_cadenas: int,
) -> list[dict[str, str]]:
    n = len(productos)
    prod = spec["varios"] if n != 1 else spec["etiqueta"]
    cad = "supermercado" if n_cadenas == 1 else "supermercados"
    reciente = max(productos, key=lambda p: p["capturado"])
    frase = frase_mas_barato(productos)
    captura = _captura_menor_precio(productos)
    return [
        {
            "q": spec["faq_precio"],
            "a": (
                f"El menor precio publicado es {frase}. "
                f"Se capturó el {captura}. "
                f"Hay {n} {prod} en {n_cadenas} {cad}. "
                f"Captura más reciente: {reciente['capturado_texto']}."
            ),
        },
        {
            "q": spec["faq_donde"],
            "a": (
                f"{spec['articulo_barato']} de esta lista es {frase}. "
                f"Se capturó el {captura}. "
                "Es el precio de góndola que publica la cadena, "
                "no el de una sucursal ni el precio con promo bancaria."
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
                "Cada producto muestra la fecha de captura, en hora de Buenos Aires. "
                f"La más reciente de esta lista es del {reciente['capturado_texto']}."
            ),
        },
    ]


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


def _de_la(spec: dict[str, Any]) -> str:
    """"de la leche" / "del aceite", a partir del anchor ("Precio del aceite hoy")."""
    return spec["anchor"].removeprefix("Precio ").removesuffix(" hoy")


def _medidas_commodity(productos: list[dict[str, Any]]) -> dict[str, tuple[str, float]] | None:
    """Unidad y base de cada producto. None si alguno no es un solo peso o volumen,
    o si no todos usan la misma unidad: ahí no se compara por litro o kilo."""
    out: dict[str, tuple[str, float]] = {}
    for p in productos:
        medida = unidad_de_medida(str(p.get("tamano") or ""))
        if medida is None:
            return None
        out[p["slug"]] = medida
    if len({u for u, _ in out.values()}) != 1:
        return None
    return out


def _por_cadena_commodity(
    productos: list[dict[str, Any]],
    medidas: dict[str, tuple[str, float]] | None,
) -> list[dict[str, Any]]:
    """Por cadena: el producto más barato que publica (por litro/kilo si se puede comparar).

    Sale de las mismas ofertas que la lista de productos: no se agrega ningún precio.
    """
    by: dict[str, dict[str, Any]] = {}
    for p in productos:
        base = medidas[p["slug"]][1] if medidas else 1.0
        for o in p["ofertas"]:
            clave = o["precio"] / base
            fila = by.get(o["tienda_id"])
            if fila is None:
                by[o["tienda_id"]] = fila = {
                    "tienda": o["tienda"],
                    "tienda_id": o["tienda_id"],
                    "n": 0,
                    "_clave": None,
                }
            fila["n"] += 1
            if fila["_clave"] is None or clave < fila["_clave"] or (
                clave == fila["_clave"] and o["precio"] < fila["precio"]
            ):
                fila.update({
                    "_clave": clave,
                    "precio": o["precio"],
                    "precio_txt": peso(o["precio"]),
                    "producto": p["nombre_visible"],
                    "href": p["href"],
                    "tamano": p.get("tamano") or "",
                    "unidad_valor": _precio_unidad(o["precio"], base) if medidas else None,
                })
    filas = sorted(by.values(), key=lambda f: (f["_clave"], f["tienda"].casefold()))
    low = filas[0]["_clave"] if filas else None
    for f in filas:
        f["barato"] = f["_clave"] == low
        f["unidad_txt"] = peso(f["unidad_valor"]) if f["unidad_valor"] is not None else ""
        f["n_txt"] = f"{f['n']} de {len(productos)} productos"
        del f["_clave"]
    return filas


def _diferencias_commodity(productos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Producto por producto: menor y mayor precio publicado y la diferencia por envase."""
    out = []
    for p in productos:
        low, high = p["low"], p["high"]
        out.append({
            "producto": p["nombre_visible"],
            "href": p["href"],
            "low_txt": peso(low),
            "low_tiendas": _lista_y([o["tienda"] for o in p["ofertas"] if o["precio"] == low]),
            "high_txt": peso(high),
            "high_tiendas": _lista_y([o["tienda"] for o in p["ofertas"] if o["precio"] == high]),
            "dif": high - low,
            "dif_txt": peso(high - low),
            "n": p["n"],
        })
    return out


def _faq_extra_commodity(
    spec: dict[str, Any],
    productos: list[dict[str, Any]],
    medidas: dict[str, tuple[str, float]] | None,
    diferencias: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Dos preguntas más, con los números de la tabla: precio por litro/kilo y diferencia entre cadenas."""
    out: list[dict[str, str]] = []
    de_la = _de_la(spec)
    if medidas:
        unidad = next(iter(medidas.values()))[0]
        precios = [
            (_precio_unidad(o["precio"], medidas[p["slug"]][1]), o, p)
            for p in productos for o in p["ofertas"]
        ]
        low = min(v for v, _, _ in precios)
        high = max(v for v, _, _ in precios)
        def _quienes(valor: float) -> str:
            partes = []
            for v, o, p in precios:
                if v != valor:
                    continue
                texto = f"{p['nombre_visible']} en {o['tienda']}"
                if abs(medidas[p["slug"]][1] - 1.0) > 1e-9:
                    texto += f" ({peso(o['precio'])} el envase de {p['tamano']})"
                if texto not in partes:
                    partes.append(texto)
            return _lista_y(partes[:3]) + (" y otros" if len(partes) > 3 else "")
        out.append({
            "q": f"¿Cuánto sale el {unidad} de {spec['etiqueta']} hoy?",
            "a": (
                f"Desde {peso(low)} el {unidad}: {_quienes(low)}. "
                f"El más caro de esta lista es {peso(high)} el {unidad}: {_quienes(high)}. "
                "Es precio de góndola, sin promo bancaria."
            ),
        })
    con_dif = [d for d in diferencias if d["dif"] > 0]
    if con_dif:
        mayor = max(con_dif, key=lambda d: d["dif"])
        texto = (
            f"Depende del producto. La mayor diferencia de hoy es en {mayor['producto']}: "
            f"{mayor['low_txt']} en {mayor['low_tiendas']} y {mayor['high_txt']} en {mayor['high_tiendas']}, "
            f"{mayor['dif_txt']} por envase."
        )
        menor = min(con_dif, key=lambda d: d["dif"])
        if menor is not mayor:
            texto += f" La menor es en {menor['producto']}: {menor['dif_txt']} por envase."
        out.append({"q": f"¿Cuánto cambia el precio {de_la} entre supermercados?", "a": texto})
    return out


def _descripcion_commodity(
    spec: dict[str, Any],
    por_cadena: list[dict[str, Any]],
    medidas: dict[str, tuple[str, float]] | None,
    n: int,
    cadenas: int,
) -> str:
    """La respuesta en la meta: desde cuánto y dónde. Si no entra en 120–158, la de siempre."""
    base = _descripcion_categoria(spec["etiqueta"], n, cadenas)
    if not por_cadena:
        return base
    baratas = [f for f in por_cadena if f["barato"]]
    quienes = _lista_y([f["tienda"] for f in baratas])
    if medidas:
        unidad = next(iter(medidas.values()))[0]
        desde = f"desde {baratas[0]['unidad_txt']} el {unidad}"
    else:
        desde = f"desde {baratas[0]['precio_txt']}"
    prod = "producto" if n == 1 else "productos"
    cad = "supermercado" if cadenas == 1 else "supermercados"
    for texto in (
        f"Precio {_de_la(spec)} hoy: {desde} en {quienes}. {n} {prod} en {cadenas} {cad}, "
        "por cadena y con la fecha de captura.",
        f"Precio {_de_la(spec)} hoy: {desde} en {quienes}. {n} {prod} en {cadenas} {cad}.",
    ):
        if 120 <= len(texto) <= 158:
            return texto
    return base


def _armar_commodity(spec: dict[str, Any], todas: list[dict[str, Any]]) -> dict[str, Any] | None:
    productos = _productos_commodity(spec, todas)
    if not _hub_publicado(productos):
        return None
    n = len(productos)
    cadenas = _n_cadenas(productos)
    title = spec["title"]
    h1 = title.removesuffix(" | BaratoYa")
    href = _href_commodity(spec)
    canonical = ORIGEN + href
    reciente = max(productos, key=lambda p: p["capturado"])
    medidas = _medidas_commodity(productos)
    por_cadena = _por_cadena_commodity(productos, medidas)
    diferencias = _diferencias_commodity(productos)
    faq = _faq_commodity(spec, productos, cadenas)
    extra = _faq_extra_commodity(spec, productos, medidas, diferencias)
    faq = faq[:2] + extra + faq[2:]
    categoria = spec["categoria"]
    categoria_href = _href_categoria(categoria)
    return {
        "slug": spec["slug"],
        "title": title,
        "description": _descripcion_commodity(spec, por_cadena, medidas, n, cadenas),
        "h1": h1,
        "canonical": canonical,
        "href": href,
        "categoria": categoria,
        "titulo_miga": spec["nombre"],
        "es_commodity": True,
        "de_la": _de_la(spec),
        "anchor": spec["anchor"],
        "por_cadena": por_cadena,
        "baratas_txt": _lista_y([f["tienda"] for f in por_cadena if f["barato"]]),
        "unidad": next(iter(medidas.values()))[0] if medidas else "",
        "unidad_col": bool(medidas) and any(abs(b - 1.0) > 1e-9 for _, b in medidas.values()),
        "diferencias": diferencias,
        "promos_cadena": {},
        "dia_hoy": "",
        "dia_hoy_href": "",
        "etiqueta": spec["etiqueta"],
        "intro": spec["intro"],
        "nota": spec.get("nota") or "",
        "padre": {
            "href": categoria_href,
            "nombre": categoria,
            "etiqueta": categoria.casefold(),
        },
        "commodities": [],
        "n": n,
        "n_cadenas": cadenas,
        "productos_txt": f"{n} {'producto' if n == 1 else 'productos'}",
        "cadenas_txt": f"{cadenas} {'supermercado' if cadenas == 1 else 'supermercados'}",
        "productos": productos,
        "actualizado": reciente["capturado_texto"],
        "lastmod": max(p["lastmod"] for p in productos),
        "faq": faq,
        "otras": [],
        "ld_faq": _ld_faq(faq),
        "ld_itemlist": _ld({
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": h1,
            "numberOfItems": n,
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i,
                    "name": p["nombre_visible"],
                    "url": p["canonical"],
                }
                for i, p in enumerate(productos, start=1)
            ],
        }),
        "ld_breadcrumb": _ld({
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Inicio", "item": ORIGEN + "/"},
                {"@type": "ListItem", "position": 2, "name": "Precios", "item": ORIGEN + PATH_HUB},
                {"@type": "ListItem", "position": 3, "name": categoria, "item": ORIGEN + categoria_href},
                {"@type": "ListItem", "position": 4, "name": spec["nombre"], "item": canonical},
            ],
        }),
    }


def pagina_commodity(slug: str, hoy: date | None = None) -> dict[str, Any] | None:
    if not commodity_conocida(slug):
        return None
    vista = _armar_commodity(_COMMODITY[slug], vistas_publicadas())
    if vista is None:
        return None
    return _commodity_con_hoy(vista, hoy or hoy_art())


def _commodity_con_hoy(vista: dict[str, Any], hoy: date) -> dict[str, Any]:
    """Promo bancaria de hoy en cada cadena de la tabla, de las mismas tarjetas que el hub.

    No se resta del precio: cada promo tiene banco, tope y exclusiones propias.
    """
    vista = dict(vista)
    dia = next((d for d in nav_dias(hoy) if d.get("hoy")), None)
    vista["dia_hoy"] = dia["nombre"] if dia else ""
    vista["dia_hoy_href"] = dia["href"] if dia else ""
    por_cadena = promos_de_hoy_por_cadena(hoy)
    filas = []
    for fila in vista["por_cadena"]:
        info = por_cadena.get(fila["tienda_id"])
        promo = None
        if info:
            if info["top_txt"]:
                linea = f"hasta {info['top_txt']}%"
                if info["bancos_top"]:
                    linea += f" con {_lista_y(info['bancos_top'][:2])}"
                    if len(info["bancos_top"]) > 2:
                        linea += " y otros"
            elif info["cuotas_n"]:
                linea = "cuotas"
            else:
                linea = f"{info['n']} {'promo' if info['n'] == 1 else 'promos'}"
            promo = {"href": info["href"], "linea": linea}
        filas.append({**fila, "promo": promo})
    vista["por_cadena"] = filas
    return vista


def paginas_commodity() -> list[dict[str, Any]]:
    todas = vistas_publicadas()
    out: list[dict[str, Any]] = []
    for spec in COMMODITIES:
        pagina = _armar_commodity(spec, todas)
        if pagina is not None:
            out.append(pagina)
    return out


def pagina_producto(slug: str, hoy: date | None = None) -> dict[str, Any] | None:
    if not re.fullmatch(r"[a-z0-9-]{3,80}", slug or ""):
        return None
    todas = vistas_publicadas()
    for vista in todas:
        if vista["slug"] == slug:
            return _con_hoy(_con_otros(vista, todas), hoy or hoy_art())
    return None


_TAMANO_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(ml|l|g|kg)\s*$", re.IGNORECASE)
_UNIDAD = {"ml": ("litro", 0.001), "l": ("litro", 1.0), "g": ("kilo", 0.001), "kg": ("kilo", 1.0)}


def unidad_de_medida(tamano: str) -> tuple[str, float] | None:
    """("litro", 0.9) para "900 ml". None si el envase no es un solo peso o volumen (packs)."""
    m = _TAMANO_RE.match(tamano or "")
    if not m:
        return None
    cantidad = float(m.group(1).replace(",", "."))
    unidad, factor = _UNIDAD[m.group(2).lower()]
    base = cantidad * factor
    if base <= 0:
        return None
    return unidad, base


def _precio_unidad(precio: float, base: float) -> float:
    return round(precio / base)


def _con_hoy(vista: dict[str, Any], hoy: date) -> dict[str, Any]:
    """Lo que responde la ficha además del precio: litro/kilo, diferencia y promos de hoy.

    Todo sale de la captura y del archivo de promos. No se resta ninguna promo al precio:
    cada una tiene banco, tope y exclusiones propias.
    """
    vista = dict(vista)
    nombre = vista.get("nombre_visible") or vista["nombre"]
    ofertas = vista["ofertas"]
    low, high = vista["low"], vista["high"]
    dia = next((d for d in nav_dias(hoy) if d.get("hoy")), None)
    dia_nombre = dia["nombre"] if dia else ""
    vista["dia_hoy"] = dia_nombre
    vista["dia_hoy_href"] = dia["href"] if dia else ""

    # Precio por litro o kilo: solo si el envase no es ya 1 L / 1 kg.
    medida = unidad_de_medida(str(vista.get("tamano") or ""))
    vista["unidad"] = ""
    vista["unidad_txt"] = ""
    if medida and abs(medida[1] - 1.0) > 1e-9:
        unidad, base = medida
        vista["unidad"] = unidad
        filas = []
        for o in ofertas:
            filas.append({**o, "unidad_txt": peso(_precio_unidad(o["precio"], base))})
        vista["ofertas"] = filas
        baratas = [o["tienda"] for o in ofertas if o["precio"] == low]
        vista["unidad_txt"] = (
            f"El {unidad} sale desde {peso(_precio_unidad(low, base))} en {_lista_y(baratas)} "
            f"({peso(low)} el envase de {vista['tamano']})."
        )
    elif medida:
        vista["unidad"] = ""
        vista["unidad_txt"] = f"El envase es de {vista['tamano']}: el precio de la tabla ya es el precio por {medida[0]}."

    vista["diferencia_txt"] = ""
    if high > low:
        vista["diferencia_txt"] = (
            f"Entre el más barato y el más caro de esta tabla hay {peso(high - low)} de diferencia por envase."
        )

    # Promos bancarias publicadas para hoy en las cadenas de la tabla.
    por_cadena = promos_de_hoy_por_cadena(hoy)
    promos_hoy: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for o in sorted(ofertas, key=lambda x: x["precio"]):
        info = por_cadena.get(o.get("tienda_id") or "")
        if not info or info["chain_id"] in vistos:
            continue
        vistos.add(info["chain_id"])
        n = info["n"]
        linea = f"{n} promo bancaria" if n == 1 else f"{n} promos bancarias"
        if info["top_txt"]:
            linea += f", hasta {info['top_txt']}%"
            if info["bancos_top"]:
                linea += f" con {_lista_y(info['bancos_top'][:3])}"
                if len(info["bancos_top"]) > 3:
                    linea += " y otros"
        elif info["cuotas_n"]:
            linea += " en cuotas"
        promos_hoy.append({"nombre": info["nombre"], "href": info["href"], "linea": linea})
    vista["promos_hoy"] = promos_hoy
    sin = [o["tienda"] for o in ofertas if (o.get("tienda_id") or "") not in por_cadena]
    vista["promos_hoy_sin"] = _lista_y(sorted(set(sin), key=str.casefold)) if sin else ""

    faq = list(vista["faq"])
    if vista["unidad"]:
        faq.insert(1, {
            "q": f"¿Cuánto sale el {vista['unidad']} de {nombre}?",
            "a": f"Captura del {vista['capturado_texto']}. {vista['unidad_txt']}",
        })
    if dia_nombre:
        if promos_hoy:
            partes = "; ".join(f"{p['nombre']}: {p['linea']}" for p in promos_hoy)
            resp = (
                f"Hoy {dia_nombre}, entre las cadenas de esta página: {partes}. "
                "Cada promo tiene su banco o billetera, tope, compra mínima y exclusiones: "
                "no está restada del precio de la tabla."
            )
        else:
            resp = (
                f"Hoy {dia_nombre} ninguna de las cadenas de esta página tiene una promo "
                "bancaria publicada. El precio de la tabla es el de góndola."
            )
        faq.append({"q": f"¿Qué supermercado tiene promo bancaria hoy para comprar {nombre}?", "a": resp})
    vista["faq"] = faq
    vista["ld_faq"] = _ld_faq(faq)
    return vista


def muestra_home() -> list[dict[str, str]]:
    by = {p["slug"]: p for p in vistas_publicadas()}
    out = []
    for slug in MUESTRA_SLUGS:
        vista = by.get(slug)
        if vista:
            out.append({"href": vista["href"], "nombre": vista.get("nombre_visible") or vista["nombre"]})
    return out


def urls_sitemap() -> list[tuple[str, str]]:
    productos = vistas_publicadas()
    if not productos:
        return []
    urls = [(ORIGEN + PATH_HUB, _lastmod_hub(productos))]
    for pagina in paginas_categoria():
        urls.append((pagina["canonical"], pagina["lastmod"]))
    for pagina in paginas_commodity():
        urls.append((pagina["canonical"], pagina["lastmod"]))
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


# Capturas compartidas entre instancias (Supabase, tabla public.precios_publicos).
# Antes cada instancia de Vercel guardaba sus lecturas en su propio /tmp: una instancia nueva
# (cada deploy, cada escalado) arrancaba con la foto del repo (10/10) y el sitemap y las fichas
# alternaban entre esa fecha y la de hoy según qué instancia respondía. Ahora cada lectura en
# vivo se guarda también en Supabase y toda instancia la levanta antes de armar la página.
# Sin claves, o con Supabase caído, todo sigue como antes (foto del repo + /tmp).
TABLA_REMOTA = "precios_publicos"
HIDRATAR_CADA_S = 600.0
REMOTO_TIMEOUT_S = 3.0
_hidratado_en: float | None = None
# capturado de cada slug según la última lectura de Supabase (o el último upsert que respondió OK).
_remoto_capturado: dict[str, datetime] = {}
_hidratar_lock: asyncio.Lock | None = None
_hidratar_loop: Any = None


def _remoto() -> tuple[str, str] | None:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        return None
    return url, key


def _headers_remoto(key: str) -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _fecha_captura(iso: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(iso or ""))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ART)
    return dt


def _captura_valida(prod: Any) -> bool:
    """Una fila remota entra solo si tiene la forma de una captura real y no viene del futuro."""
    if not isinstance(prod, dict) or prod.get("slug") not in _SPEC:
        return False
    if not isinstance(prod.get("ofertas"), list) or len(prod["ofertas"]) < MIN_CADENAS:
        return False
    dt = _fecha_captura(prod.get("capturado"))
    if dt is None or dt > datetime.now(ART) + timedelta(minutes=5):
        return False
    return True


def mezclar_capturas(remotas: list[Any]) -> int:
    """Reemplaza en memoria cada producto cuya captura remota es más nueva. Devuelve cuántos."""
    data = cargar()
    by = {p.get("slug"): p for p in data.get("productos") or [] if isinstance(p, dict)}
    cambios = 0
    for prod in remotas:
        if not _captura_valida(prod):
            continue
        prev = by.get(prod["slug"])
        prev_dt = _fecha_captura(prev.get("capturado")) if isinstance(prev, dict) else None
        if prev_dt is not None and prev_dt >= _fecha_captura(prod["capturado"]):
            continue
        by[prod["slug"]] = prod
        cambios += 1
    if cambios:
        data["productos"] = list(by.values())
    return cambios


def _lock_hidratar() -> asyncio.Lock:
    global _hidratar_lock, _hidratar_loop
    loop = asyncio.get_running_loop()
    if _hidratar_lock is None or _hidratar_loop is not loop:
        _hidratar_lock = asyncio.Lock()
        _hidratar_loop = loop
    return _hidratar_lock


async def hidratar(forzar: bool = False) -> int:
    """Trae las capturas guardadas por cualquier instancia. Como mucho cada 10 min por instancia."""
    global _hidratado_en
    remoto = _remoto()
    if remoto is None:
        return 0
    async with _lock_hidratar():
        if not forzar and _hidratado_en is not None and time.monotonic() - _hidratado_en < HIDRATAR_CADA_S:
            return 0
        url, key = remoto
        try:
            async with httpx.AsyncClient(timeout=REMOTO_TIMEOUT_S) as client:
                r = await client.get(
                    f"{url}/rest/v1/{TABLA_REMOTA}",
                    params={"select": "captura"},
                    headers=_headers_remoto(key),
                )
        except Exception:  # noqa: BLE001 - Supabase caído no tira la página
            _hidratado_en = time.monotonic()
            return 0
        _hidratado_en = time.monotonic()
        if r.status_code != 200:
            return 0
        try:
            filas = r.json()
        except ValueError:
            return 0
        if not isinstance(filas, list):
            return 0
        capturas = [f.get("captura") for f in filas if isinstance(f, dict)]
        _remoto_capturado.clear()
        for prod in capturas:
            if _captura_valida(prod):
                _remoto_capturado[prod["slug"]] = _fecha_captura(prod["capturado"])
        return mezclar_capturas(capturas)


async def guardar_remoto(prod: dict[str, Any]) -> bool:
    """Upsert de una captura recién leída. Best effort: si falla, la página sigue igual."""
    remoto = _remoto()
    if remoto is None or not _captura_valida(prod):
        return False
    url, key = remoto
    headers = _headers_remoto(key)
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    fila = {"slug": prod["slug"], "capturado": prod["capturado"], "captura": prod}
    try:
        async with httpx.AsyncClient(timeout=REMOTO_TIMEOUT_S) as client:
            r = await client.post(
                f"{url}/rest/v1/{TABLA_REMOTA}",
                params={"on_conflict": "slug"},
                headers=headers,
                json=fila,
            )
    except Exception:  # noqa: BLE001
        return False
    ok = r.status_code in (200, 201, 204)
    if ok:
        _remoto_capturado[prod["slug"]] = _fecha_captura(prod["capturado"])
    return ok


async def sincronizar_remoto() -> int:
    """Sube las capturas de esta instancia que Supabase no tiene o tiene más viejas.

    Una lectura que terminó después de que el request respondió puede no haber llegado a
    guardarse (la instancia se congela entre requests). El cron lo completa.
    """
    if _remoto() is None:
        return 0
    subidas = 0
    for prod in cargar().get("productos") or []:
        if not _captura_valida(prod) or _viejo(str(prod.get("capturado") or "")):
            continue
        remoto = _remoto_capturado.get(prod["slug"])
        if remoto is not None and remoto >= _fecha_captura(prod["capturado"]):
            continue
        if await guardar_remoto(prod):
            subidas += 1
    return subidas


async def refrescar_vencidos(espera: float) -> dict[str, int]:
    """Captura diaria (cron): relee todo lo que no sea de hoy (ART) y lo deja guardado."""
    await hidratar(forzar=True)
    slugs = [spec["slug"] for spec in CATALOGO]
    vencidos = [s for s in slugs if _vencido(s, del_dia=True)]
    tareas = [t for t in (_tarea_refresco(s, del_dia=True) for s in vencidos) if t is not None]
    pendientes: set[Any] = set()
    if tareas:
        _hechas, pendientes = await asyncio.wait(tareas, timeout=espera)
    frescos = sum(1 for s in slugs if not _vencido(s, del_dia=True))
    subidas = await sincronizar_remoto()
    return {
        "subidas": subidas,
        "productos": len(slugs),
        "vencidos_antes": len(vencidos),
        "lecturas": len(tareas),
        "pendientes": len(pendientes),
        "frescos": frescos,
    }


# Refresco en vivo de capturas vencidas (>24 h).
# Antes: un asyncio.Lock global ponía en fila TODAS las lecturas (el Semaphore(4) del hub no
# servía), el hub esperaba 15 s y casi siempre cortaba por tiempo, y una lectura que fallaba
# se reintentaba en cada request. Resultado: /precios tardaba 15-18 s en cada MISS.
# Ahora: una tarea por producto (la comparten los requests simultáneos), hasta 4 lecturas
# a la vez, backoff tras un fallo, y el request espera como mucho ESPERA_REQUEST_S. Si la
# lectura no terminó, la página sale con la captura anterior (con su fecha visible) y la
# tarea sigue en esa instancia; el CDN (stale-while-revalidate) hace que el usuario no espere.
ESPERA_REQUEST_S = 8.0
LECTURA_TIMEOUT_S = 25.0
REINTENTO_TRAS_FALLO_S = 900.0
LECTURAS_SIMULTANEAS = 4
_en_curso: dict[str, asyncio.Task] = {}
_fallo: dict[str, float] = {}
_sem: asyncio.Semaphore | None = None
_sem_loop: Any = None


def _semaforo() -> asyncio.Semaphore:
    global _sem, _sem_loop
    loop = asyncio.get_running_loop()
    if _sem is None or _sem_loop is not loop:
        _sem = asyncio.Semaphore(LECTURAS_SIMULTANEAS)
        _sem_loop = loop
    return _sem


def _vencido(slug: str, del_dia: bool = False) -> bool:
    actual = _crudo(slug)
    return actual is None or _viejo(str(actual.get("capturado") or ""), del_dia)


async def _leer_y_guardar(spec: dict[str, Any], del_dia: bool = False) -> None:
    slug = spec["slug"]
    async with _semaforo():
        if not _vencido(slug, del_dia):
            return
        try:
            nuevo = await asyncio.wait_for(leer_en_vivo(spec), timeout=LECTURA_TIMEOUT_S)
        except Exception:  # noqa: BLE001 - una cadena caída no tira la página
            nuevo = None
    if nuevo is None:
        _fallo[slug] = time.monotonic()
        return
    _fallo.pop(slug, None)
    _reemplazar(nuevo)
    await guardar_remoto(nuevo)


def _tarea_refresco(slug: str, del_dia: bool = False) -> asyncio.Task | None:
    """La tarea que relee este producto, o None si no hace falta (o falló hace poco)."""
    if _offline():
        return None
    spec = _SPEC.get(slug)
    if spec is None or not _vencido(slug, del_dia):
        return None
    tarea = _en_curso.get(slug)
    if tarea is not None and not tarea.done() and tarea.get_loop() is asyncio.get_running_loop():
        return tarea
    falla = _fallo.get(slug)
    if falla is not None and time.monotonic() - falla < REINTENTO_TRAS_FALLO_S:
        return None
    tarea = asyncio.create_task(_leer_y_guardar(spec, del_dia))
    _en_curso[slug] = tarea

    def _fin(t: asyncio.Task, s: str = slug) -> None:
        if _en_curso.get(s) is t:
            _en_curso.pop(s, None)
        if not t.cancelled():
            t.exception()  # evita "Task exception was never retrieved"

    tarea.add_done_callback(_fin)
    return tarea


async def _refrescar(slugs: list[str], espera: float | None = None) -> bool:
    """True si la página sale con todas las lecturas terminadas; False si alguna sigue en curso.

    Con False, app.py le pide al CDN un caché corto: la copia con la captura anterior no
    queda fija hasta la medianoche y la próxima revalidación ya trae el precio nuevo.
    """
    await hidratar()
    tareas = [t for t in (_tarea_refresco(s) for s in slugs) if t is not None]
    if not tareas:
        return True
    # asyncio.wait no cancela al vencer el plazo: la lectura sigue y la próxima página la usa.
    _hechas, pendientes = await asyncio.wait(tareas, timeout=ESPERA_REQUEST_S if espera is None else espera)
    return not pendientes


async def asegurar_producto(slug: str) -> bool:
    """Si la captura de este producto tiene más de un día, vuelve a leer el catálogo."""
    return await _refrescar([slug])


async def asegurar_hub() -> bool:
    """Relee los productos vencidos. Si no alcanza el tiempo, queda la captura anterior."""
    return await _refrescar([spec["slug"] for spec in CATALOGO])


async def asegurar_categoria(slug: str) -> bool:
    """Relee los productos vencidos de una categoría. Si no alcanza el tiempo, queda la captura."""
    nombre = _SLUG_CATEGORIA.get(slug or "")
    if nombre is None:
        return True
    return await _refrescar([spec["slug"] for spec in CATALOGO if spec["categoria"] == nombre])


async def asegurar_commodity(slug: str) -> bool:
    """Relee los productos vencidos de un hub. Si no alcanza el tiempo, queda la captura."""
    if not commodity_conocida(slug):
        return True
    spec = _COMMODITY[slug]
    return await _refrescar([item["slug"] for item in CATALOGO if _producto_en_commodity(item["slug"], spec)])


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
