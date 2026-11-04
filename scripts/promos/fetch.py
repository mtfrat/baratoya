"""Descarga las fuentes PÚBLICAS a un directorio raw. Sin login, sin cookies, sin tokens.

Cada fuente se valida (HTTP 200, tamaño mínimo): si una cae, el script falla con el nombre
de la fuente en vez de armar una semana con datos viejos o vacíos.
"""
from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (compatible; BaratoYaPromos/1.0; +https://baratoya.app)"
BP_FIELDS = (
    "active,active_from,active_to,discount_percentage,discount_text_info,discounts_amount_installments,"
    "discounts_text_installments,ecommerce,express,friday,hyper,id,idBank,idCard,img,img_card,legal,market,"
    "maxi,monday,order,saturday,sub_title,sunday,thursday,title,tuesday,valid,validText,wednesday"
)
BP_FIELDS_MAS = BP_FIELDS + ",isMasClub,express_ecommerce_all"
# (archivo, url, tamaño mínimo en bytes)
PAGINAS = (
    ("dia.html", "https://diaonline.supermercadosdia.com.ar/medios-de-pago-y-promociones", 200_000),
    ("laanonima.html", "https://super.laanonima.com.ar/empresa/promociones-y-descuentos", 20_000),
    ("makro.html", "https://makro.com.ar/beneficios-bancarios/", 20_000),
    ("maxiconsumo.html", "https://www.maxiconsumo.com/promociones", 5_000),
    ("supermami.html", "https://www.supermami.com.ar/super/financiacion", 5_000),
    ("cordiez.html", "https://www.cordiez.com.ar/institucionales/medios-de-pago", 5_000),
    ("toledo.html", "https://www.toledodigital.com.ar/promociones-bancarias", 5_000),
)
JSON_SIMPLE = (
    ("cenco_jn.json", "https://www.jumbo.com.ar/api/dataentities/JN/documents/bankDiscount?_fields=value,id&an=jumboargentina", 100_000),
    ("coto_promos.json", "https://www.cotodigital.com.ar/rest/model/atg/actors/cProfileActor/getPromocionesMulticanal", 20_000),
)
VTEX = (
    ("car", "https://www.carrefour.com.ar"),
    ("mas", "https://www.masonline.com.ar"),
)


class FetchError(RuntimeError):
    pass


def _get(url: str, headers: dict[str, str] | None = None, reintentos: int = 3, con_headers: bool = False):
    h = {"User-Agent": UA, "Accept-Encoding": "gzip", "Accept": "*/*", **(headers or {})}
    ultimo: Exception | None = None
    for i in range(reintentos):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=40) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return (data, dict(r.headers)) if con_headers else data
        except (urllib.error.URLError, TimeoutError, OSError) as e:  # noqa: PERF203
            ultimo = e
            time.sleep(2 * (i + 1))
    raise FetchError(f"{url}: {ultimo}")


def _vtex_entity(base: str, entity: str, fields: str) -> list[dict]:
    """Pagina con REST-Range y verifica contra REST-Content-Range (el servidor puede devolver menos por página)."""
    out: list[dict] = []
    ini, total = 0, None
    while total is None or ini < total:
        url = f"{base}/api/dataentities/{entity}/search?_fields={fields}"
        raw, hdr = _get(url, {"REST-Range": f"resources={ini}-{ini + 299}", "Accept": "application/json"}, con_headers=True)
        lote = json.loads(raw)
        rango = {k.lower(): v for k, v in hdr.items()}.get("rest-content-range", "")  # "resources 0-151/152"
        try:
            total = int(rango.rsplit("/", 1)[1])
        except (IndexError, ValueError):
            total = ini + len(lote)
        if not lote:
            break
        out.extend(lote)
        ini += len(lote)
    if total is not None and len(out) != total:
        raise FetchError(f"{base} {entity}: {len(out)} filas leídas de {total}")
    return out


def fetch_all(raw: Path, log=print) -> None:
    raw.mkdir(parents=True, exist_ok=True)

    def guardar(nombre: str, data: bytes, minimo: int) -> None:
        if len(data) < minimo:
            raise FetchError(f"{nombre}: {len(data)} bytes (mínimo esperado {minimo}). La fuente cambió o devolvió vacío.")
        (raw / nombre).write_bytes(data)
        log(f"  fetch {nombre}: {len(data):,} bytes")

    for nombre, url, minimo in (*PAGINAS, *JSON_SIMPLE):
        guardar(nombre, _get(url), minimo)
    for pref, base in VTEX:
        bp = _vtex_entity(base, "BP", BP_FIELDS_MAS if pref == "mas" else BP_FIELDS)  # sin _where: sel() filtra por active/fechas
        fb = _vtex_entity(base, "FB", "id,image,name" + (",showInPdp" if pref == "mas" else ""))
        fc = _vtex_entity(base, "FC", "id,image,name" + (",showInPdp" if pref == "mas" else ""))
        if len(bp) < 10:
            raise FetchError(f"{base} BP: sólo {len(bp)} cards activas")
        for nombre, obj in ((f"{pref}_bp_all.json", bp), (f"{pref}_fb.json", fb), (f"{pref}_fc.json", fc)):
            guardar(nombre, json.dumps(obj, ensure_ascii=False).encode(), 100)
