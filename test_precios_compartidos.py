"""Capturas de /precios compartidas entre instancias (Supabase) + captura diaria. Sin red."""
from __future__ import annotations

import asyncio
import copy
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

os.environ["BARATOYA_PRECIOS_OFFLINE"] = "1"

import httpx
from fastapi.testclient import TestClient

import app as app_mod
import precios_seo

ART = timezone(timedelta(hours=-3))


def _base_producto() -> dict:
    data = json.loads(precios_seo.RUTA.read_text(encoding="utf-8"))
    return copy.deepcopy(data["productos"][0])


def _con_fecha(prod: dict, dt: datetime) -> dict:
    out = copy.deepcopy(prod)
    out["capturado"] = dt.isoformat(timespec="seconds")
    out["capturado_texto"] = precios_seo._texto_captura(dt)
    return out


class _Resp:
    def __init__(self, status: int, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _Cliente:
    """Reemplazo de httpx.AsyncClient que registra pedidos."""

    calls: list = []
    get_payload: list = []
    get_status = 200
    post_status = 201
    falla = False

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None):
        _Cliente.calls.append(("GET", url, params, headers, None))
        if _Cliente.falla:
            raise httpx.ConnectError("caído")
        return _Resp(_Cliente.get_status, _Cliente.get_payload)

    async def post(self, url, params=None, headers=None, json=None):
        _Cliente.calls.append(("POST", url, params, headers, json))
        if _Cliente.falla:
            raise httpx.ConnectError("caído")
        return _Resp(_Cliente.post_status)


ENV = {"SUPABASE_URL": "https://ejemplo.supabase.co/", "SUPABASE_SERVICE_ROLE_KEY": "clave-de-prueba"}


class Base(unittest.TestCase):
    def setUp(self):
        precios_seo.reiniciar_cache()
        precios_seo._hidratado_en = None
        precios_seo._remoto_capturado.clear()
        _Cliente.calls = []
        _Cliente.get_payload = []
        _Cliente.get_status = 200
        _Cliente.post_status = 201
        _Cliente.falla = False
        self._tmp = mock.patch.object(precios_seo, "RUTA_TMP", precios_seo.RUTA.parent / "__no_existe__.json")
        self._tmp.start()
        self._http = mock.patch.object(precios_seo.httpx, "AsyncClient", _Cliente)
        self._http.start()

    def tearDown(self):
        self._http.stop()
        self._tmp.stop()
        precios_seo.reiniciar_cache()
        precios_seo._hidratado_en = None


class MezclaTests(Base):
    def test_remota_mas_nueva_reemplaza(self):
        prod = _base_producto()
        nuevo = _con_fecha(prod, datetime.now(ART) - timedelta(hours=1))
        self.assertEqual(precios_seo.mezclar_capturas([nuevo]), 1)
        self.assertEqual(precios_seo._crudo(prod["slug"])["capturado"], nuevo["capturado"])

    def test_remota_mas_vieja_no_pisa(self):
        prod = _base_producto()
        viejo = _con_fecha(prod, datetime.fromisoformat(prod["capturado"]) - timedelta(days=3))
        self.assertEqual(precios_seo.mezclar_capturas([viejo]), 0)
        self.assertEqual(precios_seo._crudo(prod["slug"])["capturado"], prod["capturado"])

    def test_descarta_futuro_slug_desconocido_y_sin_ofertas(self):
        prod = _base_producto()
        futuro = _con_fecha(prod, datetime.now(ART) + timedelta(days=2))
        otro = _con_fecha(prod, datetime.now(ART))
        otro["slug"] = "producto-que-no-existe"
        vacio = _con_fecha(prod, datetime.now(ART))
        vacio["ofertas"] = vacio["ofertas"][:1]
        self.assertEqual(precios_seo.mezclar_capturas([futuro, otro, vacio, None, "x"]), 0)
        self.assertEqual(precios_seo._crudo(prod["slug"])["capturado"], prod["capturado"])


class HidratarTests(Base):
    def test_sin_claves_no_llama_a_nadie(self):
        with mock.patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}):
            self.assertEqual(asyncio.run(precios_seo.hidratar()), 0)
            self.assertFalse(asyncio.run(precios_seo.guardar_remoto(_base_producto())))
        self.assertEqual(_Cliente.calls, [])

    def test_hidrata_y_respeta_intervalo(self):
        prod = _base_producto()
        nuevo = _con_fecha(prod, datetime.now(ART) - timedelta(minutes=30))
        _Cliente.get_payload = [{"captura": nuevo}]
        with mock.patch.dict(os.environ, ENV):
            self.assertEqual(asyncio.run(precios_seo.hidratar()), 1)
            self.assertEqual(asyncio.run(precios_seo.hidratar()), 0)  # dentro de los 10 min
        gets = [c for c in _Cliente.calls if c[0] == "GET"]
        self.assertEqual(len(gets), 1)
        self.assertEqual(gets[0][1], "https://ejemplo.supabase.co/rest/v1/precios_publicos")
        self.assertEqual(gets[0][3]["Authorization"], "Bearer clave-de-prueba")
        self.assertFalse(precios_seo._vencido(prod["slug"]))

    def test_supabase_caido_no_rompe(self):
        _Cliente.falla = True
        with mock.patch.dict(os.environ, ENV):
            self.assertEqual(asyncio.run(precios_seo.hidratar()), 0)
            self.assertFalse(asyncio.run(precios_seo.guardar_remoto(_con_fecha(_base_producto(), datetime.now(ART)))))

    def test_error_http_no_rompe(self):
        _Cliente.get_status = 500
        with mock.patch.dict(os.environ, ENV):
            self.assertEqual(asyncio.run(precios_seo.hidratar()), 0)


class GuardarTests(Base):
    def test_upsert_por_slug(self):
        prod = _con_fecha(_base_producto(), datetime.now(ART))
        with mock.patch.dict(os.environ, ENV):
            self.assertTrue(asyncio.run(precios_seo.guardar_remoto(prod)))
        metodo, url, params, headers, body = _Cliente.calls[-1]
        self.assertEqual(metodo, "POST")
        self.assertEqual(params, {"on_conflict": "slug"})
        self.assertIn("resolution=merge-duplicates", headers["Prefer"])
        self.assertEqual(body["slug"], prod["slug"])
        self.assertEqual(body["capturado"], prod["capturado"])
        self.assertEqual(body["captura"], prod)

    def test_lectura_en_vivo_se_guarda(self):
        prod = _base_producto()
        spec = precios_seo._SPEC[prod["slug"]]
        nuevo = _con_fecha(prod, datetime.now(ART))

        async def leer(_spec):
            return nuevo

        async def correr():
            precios_seo._en_curso.clear()
            precios_seo._fallo.clear()
            await precios_seo._leer_y_guardar(spec)

        with mock.patch.dict(os.environ, ENV), \
                mock.patch.object(precios_seo, "leer_en_vivo", leer), \
                mock.patch.object(precios_seo, "_persistir", lambda data: None):
            asyncio.run(correr())
        posts = [c for c in _Cliente.calls if c[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][4]["capturado"], nuevo["capturado"])


class SitemapTests(Base):
    def test_lastmod_sale_de_la_captura_compartida(self):
        prod = _base_producto()
        hoy = datetime.now(ART)
        _Cliente.get_payload = [{"captura": _con_fecha(prod, hoy - timedelta(minutes=5))}]
        with mock.patch.dict(os.environ, ENV):
            with TestClient(app_mod.app) as client:
                r = client.get("/sitemap.xml")
        self.assertEqual(r.status_code, 200)
        loc = f"<loc>{precios_seo.ORIGEN}/precios/{prod['slug']}</loc><lastmod>{hoy.date().isoformat()}</lastmod>"
        self.assertIn(loc, r.text)
        for last in __import__("re").findall(r"<lastmod>([^<]+)</lastmod>", r.text):
            self.assertLessEqual(last[:10], hoy.date().isoformat())


class CronTests(Base):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app_mod.app).__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        super().tearDown()

    def test_sin_secreto_responde_resumen_sin_cache(self):
        with mock.patch.dict(os.environ, {"CRON_SECRET": ""}):
            r = self.client.get("/api/cron/precios")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["productos"], len(precios_seo.CATALOGO))
        self.assertIn("subidas", body)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertIn("noindex", r.headers.get("x-robots-tag", ""))

    def test_con_secreto_exige_header(self):
        with mock.patch.dict(os.environ, {"CRON_SECRET": "s3cr3t"}):
            self.assertEqual(self.client.get("/api/cron/precios").status_code, 401)
            ok = self.client.get("/api/cron/precios", headers={"Authorization": "Bearer s3cr3t"})
        self.assertEqual(ok.status_code, 200)

    def test_cron_en_vercel_json(self):
        v = json.loads((precios_seo.RUTA.parent.parent / "vercel.json").read_text(encoding="utf-8"))
        self.assertIn({"path": "/api/cron/precios", "schedule": "0 10 * * *"}, v["crons"])
        self.assertFalse(app_mod.es_publica_cacheable("/api/cron/precios"))


class SincronizarTests(Base):
    def test_sube_solo_lo_fresco_que_falta_o_es_mas_nuevo(self):
        data = precios_seo.cargar()
        ahora = datetime.now(ART)
        a, b, c = (copy.deepcopy(p) for p in data["productos"][:3])
        a = _con_fecha(a, ahora - timedelta(minutes=10))   # fresco, Supabase no lo tiene
        b = _con_fecha(b, ahora - timedelta(minutes=10))   # fresco, Supabase ya lo tiene igual
        data["productos"] = [a, b, c] + data["productos"][3:]  # c sigue con la foto vieja
        precios_seo._remoto_capturado[b["slug"]] = precios_seo._fecha_captura(b["capturado"])
        with mock.patch.dict(os.environ, ENV):
            self.assertEqual(asyncio.run(precios_seo.sincronizar_remoto()), 1)
            self.assertEqual(asyncio.run(precios_seo.sincronizar_remoto()), 0)
        posts = [c_ for c_ in _Cliente.calls if c_[0] == "POST"]
        self.assertEqual([p_[4]["slug"] for p_ in posts], [a["slug"]])

    def test_sin_claves_no_sube(self):
        with mock.patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}):
            self.assertEqual(asyncio.run(precios_seo.sincronizar_remoto()), 0)


class CronDelDiaTests(Base):
    """El cron de las 07:00 ART relee lo capturado ayer aunque tenga menos de 24 h."""

    def _ayer_tarde(self) -> datetime:
        hoy0 = datetime.now(ART).replace(hour=0, minute=0, second=0, microsecond=0)
        return hoy0 - timedelta(minutes=1)

    def test_viejo_del_dia(self):
        ayer = self._ayer_tarde().isoformat(timespec="seconds")
        hoy = datetime.now(ART).isoformat(timespec="seconds")
        self.assertTrue(precios_seo._viejo(ayer, del_dia=True))
        self.assertFalse(precios_seo._viejo(hoy, del_dia=True))
        self.assertFalse(precios_seo._viejo(hoy))
        hace_22h = (datetime.now(ART) - timedelta(hours=22)).isoformat(timespec="seconds")
        self.assertFalse(precios_seo._viejo(hace_22h))  # páginas: sigue el corte de 24 h
        self.assertTrue(precios_seo._viejo((datetime.now(ART) - timedelta(hours=25)).isoformat()))

    def test_cron_relee_capturas_de_ayer(self):
        data = precios_seo.cargar()
        ayer = self._ayer_tarde()
        data["productos"] = [_con_fecha(p, ayer) for p in data["productos"]]
        leidos: list[str] = []

        async def leer(spec):
            leidos.append(spec["slug"])
            base = precios_seo._crudo(spec["slug"])
            return _con_fecha(base, datetime.now(ART))

        async def correr():
            precios_seo._en_curso.clear()
            precios_seo._fallo.clear()
            return await precios_seo.refrescar_vencidos(30)

        with mock.patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}), \
                mock.patch.object(precios_seo, "_offline", lambda: False), \
                mock.patch.object(precios_seo, "leer_en_vivo", leer), \
                mock.patch.object(precios_seo, "_persistir", lambda data: None):
            r = asyncio.run(correr())
        n = len([p for p in data["productos"] if precios_seo._SPEC.get(p["slug"])])
        self.assertEqual(r["vencidos_antes"], len(precios_seo.CATALOGO))
        self.assertEqual(r["lecturas"], len(precios_seo.CATALOGO))
        self.assertEqual(len(leidos), n)
        self.assertEqual(r["frescos"], len(precios_seo.CATALOGO))
        hoy = datetime.now(ART).date().isoformat()
        for p in precios_seo.cargar()["productos"]:
            if precios_seo._SPEC.get(p["slug"]):
                self.assertEqual(p["capturado"][:10], hoy)


if __name__ == "__main__":
    unittest.main()
