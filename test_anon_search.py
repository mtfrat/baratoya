"""Búsqueda sin cuenta: resultados reales, tope por IP/cookie, cupo de cuentas intacto,
listas/alertas/Plus siguen con login, y la migración nueva es solo service_role."""
from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import anon
import app as app_mod
import cuentas

ROOT = Path(__file__).resolve().parent
MIG = ROOT / "supabase" / "migrations" / "baratoya_anon_search.sql"
UID = "00000000-0000-0000-0000-0000000000b1"

PC_DATA = {
    "productos": [
        {"id": "7790001", "nombre": "Leche entera 1 L", "marca": "La Serenísima", "presentacion": "1.0 lt",
         "precioMin": 1100.0, "precioMax": 1500.0, "cantSucursalesDisponible": 12},
        {"id": "7790002", "nombre": "Leche descremada 1 L", "marca": "Sancor", "presentacion": "1.0 lt",
         "precioMin": 1050.0, "precioMax": 1400.0, "cantSucursalesDisponible": 9},
    ]
}


async def _pc(path, params):
    return 200, PC_DATA


async def _super(q, consultas=None):
    return {"productos": [], "q_usada": q, "fuentes": [
        {"tienda": "Dia", "tienda_id": "dia", "http": 200, "ok": True, "n": 0}]}


async def _promos():
    return []


async def _meli(q, limit=10):
    return {"tienda": "Mercado Libre", "tienda_id": "mla", "omitido": True, "productos": []}


class _Upstream:
    """Parchea las fuentes de precios (sin red) para que /api/buscar devuelva datos."""

    def __enter__(self):
        self._ps = [
            patch.object(app_mod, "pc_get", _pc),
            patch.object(app_mod, "buscar_super", _super),
            patch.object(app_mod, "buscar_promos", _promos),
            patch.object(app_mod, "buscar_meli", _meli),
        ]
        for p in self._ps:
            p.start()
        return self

    def __exit__(self, *a):
        for p in reversed(self._ps):
            p.stop()
        return False


def _sin_supabase():
    """Sin env de Supabase: cae al tope en memoria (lo que pasa si la migración no está)."""
    return patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_ANON_KEY": "", "SUPABASE_SERVICE_ROLE_KEY": ""})


class AnonBusquedaTest(unittest.TestCase):
    def setUp(self) -> None:
        anon._mem_reset()

    def test_anonimo_busca_y_ve_resultados(self) -> None:
        with _sin_supabase(), _Upstream():
            client = TestClient(app_mod.app)
            r = client.get("/api/buscar?q=leche", headers={"x-real-ip": "200.1.1.1"})
        self.assertEqual(r.status_code, 200, r.text)
        j = r.json()
        self.assertEqual(j["fuente"], "precios_claros_live")
        self.assertEqual(len(j["data"]["productos"]), 2)
        self.assertTrue(j["cuenta"]["anon"])
        self.assertEqual(j["cuenta"]["plan"], "anon")
        self.assertEqual(j["cuenta"]["remaining"], anon.hour_limit() - 1)
        # cookie firmada emitida, httponly
        sc = r.headers.get("set-cookie", "")
        self.assertIn(anon.COOKIE + "=", sc)
        self.assertIn("HttpOnly", sc)
        self.assertIn("no-store", r.headers.get("cache-control", ""))

    def test_anonimo_no_consume_cupo_de_cuenta(self) -> None:
        consumir = AsyncMock()
        with _sin_supabase(), _Upstream(), patch.object(cuentas, "consumir", consumir), \
                patch.object(cuentas, "usuario", AsyncMock()) as usuario:
            client = TestClient(app_mod.app)
            r = client.get("/api/buscar?q=yerba", headers={"x-real-ip": "200.1.1.2"})
        self.assertEqual(r.status_code, 200)
        consumir.assert_not_called()
        usuario.assert_not_called()

    def test_tope_por_hora_por_ip_da_429_con_cta(self) -> None:
        with _sin_supabase(), _Upstream(), patch.dict(os.environ, {"ANON_SEARCH_HOUR_LIMIT": "3"}):
            client = TestClient(app_mod.app)
            for i in range(3):
                client.cookies.clear()  # aunque borre la cookie, cuenta la IP
                r = client.get(f"/api/buscar?q=leche{i}", headers={"x-forwarded-for": "200.9.9.9, 10.0.0.1"})
                self.assertEqual(r.status_code, 200, r.text)
            client.cookies.clear()
            r = client.get("/api/buscar?q=leche", headers={"x-forwarded-for": "200.9.9.9"})
            self.assertEqual(r.status_code, 429)
            j = r.json()
            self.assertEqual(j["reason"], "anon_limit")
            self.assertEqual(j["scope"], "hour")
            self.assertEqual(j["cta"], "Creá tu cuenta gratis")
            self.assertIn("cuenta gratis", j["error"])
            self.assertEqual(r.headers.get("retry-after"), "3600")
            # otra IP sigue pudiendo
            client.cookies.clear()
            r = client.get("/api/buscar?q=leche", headers={"x-forwarded-for": "200.9.9.10"})
            self.assertEqual(r.status_code, 200)

    def test_tope_por_cookie_aunque_cambie_la_ip(self) -> None:
        with _sin_supabase(), _Upstream(), patch.dict(os.environ, {"ANON_SEARCH_HOUR_LIMIT": "2"}):
            client = TestClient(app_mod.app, base_url="https://testserver")  # cookie Secure
            for i in range(2):
                r = client.get("/api/buscar?q=arroz", headers={"x-real-ip": f"201.0.0.{i}"})
                self.assertEqual(r.status_code, 200)
            r = client.get("/api/buscar?q=arroz", headers={"x-real-ip": "201.0.0.99"})
            self.assertEqual(r.status_code, 429)

    def test_tope_por_dia(self) -> None:
        with patch.dict(os.environ, {"ANON_SEARCH_HOUR_LIMIT": "100", "ANON_SEARCH_DAY_LIMIT": "2"}):
            k = ["ip:x"]
            t0 = 1_000_000.0
            self.assertTrue(anon._mem_hit(k, "a", t0)["ok"])
            self.assertTrue(anon._mem_hit(k, "a", t0 + 7200)["ok"])
            res = anon._mem_hit(k, "a", t0 + 9000)
            self.assertFalse(res["ok"])
            self.assertEqual(res["reason"], "rate_day")
            self.assertTrue(anon._mem_hit(k, "a", t0 + 86401 + 7200)["ok"])  # pasó el día

    def test_cookie_firmada_no_se_puede_falsificar(self) -> None:
        aid, raw = anon.nueva_cookie()
        self.assertEqual(anon.leer_cookie(raw), aid)
        self.assertIsNone(anon.leer_cookie(aid + ".deadbeefdeadbeefdeadbeef"))
        self.assertIsNone(anon.leer_cookie("../x.y"))
        self.assertIsNone(anon.leer_cookie(None))

    def test_ip_no_se_guarda_en_claro(self) -> None:
        h = anon.ip_hash("200.1.1.1")
        self.assertEqual(len(h), 32)
        self.assertTrue(re.fullmatch(r"[0-9a-f]{32}", h))
        self.assertNotEqual(h, anon.ip_hash("200.1.1.2"))
        self.assertEqual(anon.client_ip({"x-real-ip": "1.2.3.4", "x-forwarded-for": "9.9.9.9"}), "1.2.3.4")
        self.assertEqual(anon.client_ip({"x-forwarded-for": "9.9.9.9, 10.0.0.1"}), "9.9.9.9")
        self.assertEqual(anon.client_ip({}, "127.0.0.1"), "127.0.0.1")


class AnonSupabaseTest(unittest.TestCase):
    """Con la RPC disponible se usa Supabase (atómico, compartido entre instancias)."""

    def setUp(self) -> None:
        anon._mem_reset()

    def _env(self):
        return patch.dict(os.environ, {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": "a",
                                       "SUPABASE_SERVICE_ROLE_KEY": "s"})

    def test_rpc_ok_registra_y_usa_supabase(self) -> None:
        calls = []

        class R:
            status_code = 200
            text = ""

            def json(self):
                return {"ok": True, "hour": 4, "day": 7, "hour_limit": 10, "day_limit": 30}

        class C:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, headers=None, json=None):
                calls.append((url, headers, json))
                return R()

        with self._env(), patch.object(anon.httpx, "AsyncClient", C):
            import asyncio
            res = asyncio.run(anon.registrar({"x-real-ip": "200.2.2.2"}, {}, None, "leche"))
        self.assertTrue(res["ok"])
        self.assertEqual(res["storage"], "supabase")
        url, headers, body = calls[0]
        self.assertTrue(url.endswith("/rest/v1/rpc/anon_search_hit"))
        self.assertEqual(headers["Authorization"], "Bearer s")  # service_role
        self.assertEqual(body["p_query"], "leche")
        self.assertEqual(len(body["p_ip_hash"]), 32)
        self.assertNotIn("200.2.2.2", str(body))
        self.assertEqual(body["p_hour_limit"], 10)
        self.assertEqual(body["p_day_limit"], 30)

    def test_rpc_tope_devuelve_429(self) -> None:
        async def fake_rpc(iph, aid, q):
            return {"ok": False, "reason": "rate_day", "hour": 3, "day": 30, "hour_limit": 10,
                    "day_limit": 30, "storage": "supabase"}

        with self._env(), _Upstream(), patch.object(anon, "_rpc_hit", fake_rpc):
            r = TestClient(app_mod.app).get("/api/buscar?q=leche")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["scope"], "day")
        self.assertIn("30", r.json()["error"])

    def test_sin_migracion_degrada_a_memoria(self) -> None:
        """PostgREST da 404 (PGRST202) si la RPC no existe: se busca igual, tope en memoria."""

        class R:
            status_code = 404
            text = '{"code":"PGRST202","message":"Could not find the function public.anon_search_hit"}'

            def json(self):
                return {}

        class C:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **k): return R()

        with self._env(), _Upstream(), patch.object(anon.httpx, "AsyncClient", C):
            r = TestClient(app_mod.app).get("/api/buscar?q=leche", headers={"x-real-ip": "200.3.3.3"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(r.json()["data"]["productos"]), 2)


class CuentaSinCambiosTest(unittest.TestCase):
    """Con sesión el flujo es el de antes: consume_search/trial/Plus, sin tope anónimo."""

    def test_logueado_usa_consumir_y_no_el_tope_anonimo(self) -> None:
        quota = {"ok": True, "plan": "free", "used": 2, "remaining": 3, "limit": 5}
        consumir = AsyncMock(return_value=dict(quota))
        registrar = AsyncMock()
        env = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": "a", "SUPABASE_SERVICE_ROLE_KEY": "s"}
        with patch.dict(os.environ, env), _Upstream(), \
                patch.object(cuentas, "usuario", AsyncMock(return_value={"id": UID, "email": "u@x.com"})), \
                patch.object(cuentas, "consumir", consumir), \
                patch.object(cuentas, "leer_cuenta", AsyncMock(return_value={"prefs": cuentas.DEFAULT_PREFS})), \
                patch.object(anon, "registrar", registrar):
            r = TestClient(app_mod.app).get("/api/buscar?q=leche", headers={"Authorization": "Bearer t"})
        self.assertEqual(r.status_code, 200, r.text)
        consumir.assert_awaited_once_with(UID, "leche")
        registrar.assert_not_called()
        c = r.json()["cuenta"]
        self.assertEqual(c["plan"], "free")
        self.assertEqual(c["remaining"], 3)
        self.assertNotIn("anon", c)
        self.assertNotIn(anon.COOKIE, r.headers.get("set-cookie", ""))

    def test_logueado_sin_cupo_sigue_402(self) -> None:
        consumir = AsyncMock(return_value={"ok": False, "reason": "quota", "plan": "free", "used": 5, "limit": 5})
        env = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": "a", "SUPABASE_SERVICE_ROLE_KEY": "s"}
        with patch.dict(os.environ, env), \
                patch.object(cuentas, "usuario", AsyncMock(return_value={"id": UID, "email": "u@x.com"})), \
                patch.object(cuentas, "consumir", consumir):
            r = TestClient(app_mod.app).get("/api/buscar?q=leche", headers={"Authorization": "Bearer t"})
        self.assertEqual(r.status_code, 402)
        self.assertEqual(r.json()["reason"], "quota")


class GatedSiguenConLoginTest(unittest.TestCase):
    def test_listas_alertas_plus_requieren_login(self) -> None:
        env = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": "a", "SUPABASE_SERVICE_ROLE_KEY": "s"}
        with patch.dict(os.environ, env):
            client = TestClient(app_mod.app)
            casos = [
                ("get", "/api/lista", None),
                ("post", "/api/lista", {"nombre": "Leche", "tienda": "Dia", "precio": 1000, "url": "", "fuente": "vtex", "product_key": "dia:leche"}),
                ("get", "/api/alertas", None),
                ("post", "/api/alertas/revisar", {}),
                ("post", "/api/cuenta/checkout", {}),
                ("post", "/api/cuenta/activar-trial", {}),
                ("get", "/api/cuenta", None),
                ("get", "/api/cuenta/busquedas", None),
            ]
            for metodo, path, body in casos:
                r = client.get(path) if metodo == "get" else client.post(path, json=body)
                self.assertEqual(r.status_code, 401, f"{metodo} {path} -> {r.status_code} {r.text[:200]}")

    def test_home_sin_muro_de_busqueda_y_con_cta_de_cuenta(self) -> None:
        r = TestClient(app_mod.app).get("/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Para buscar hace falta entrar", r.text)
        self.assertIn("Buscá sin cuenta", r.text)
        self.assertIn('id="anon-cta"', r.text)
        self.assertIn("Creá tu cuenta gratis", r.text)
        self.assertIn("anon_limit", r.text)


class MigracionAnonTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sql = MIG.read_text()

    def test_tabla_nueva_con_grants_explicitos_y_rls(self) -> None:
        s = re.sub(r"\s+", " ", self.sql.lower())
        self.assertIn("create table if not exists public.anon_search_events", s)
        self.assertIn("alter table public.anon_search_events enable row level security", s)
        self.assertIn("revoke all on table public.anon_search_events from public, anon, authenticated", s)
        self.assertIn("grant select, insert, delete on table public.anon_search_events to service_role", s)
        self.assertNotRegex(s, r"grant [^;]* to (anon|authenticated)")
        self.assertNotIn("create policy", s)

    def test_rpc_solo_service_role_y_admin_stats_mantiene_exclusiones(self) -> None:
        s = re.sub(r"\s+", " ", self.sql.lower())
        self.assertIn("revoke all on function public.anon_search_hit(text, text, text, integer, integer) from public, anon, authenticated", s)
        self.assertIn("grant execute on function public.anon_search_hit(text, text, text, integer, integer) to service_role", s)
        self.assertIn("not p.is_test and coalesce(p.role, 'user') <> 'admin'", s)
        self.assertIn("'busquedas_sin_cuenta', n_anon", s)
        self.assertIn("revoke all on function public.admin_stats() from public, anon, authenticated", s)

    def test_no_guarda_ip_en_claro(self) -> None:
        s = self.sql.lower()
        self.assertIn("ip_hash", s)
        self.assertNotRegex(s, r"\bip_addr|\binet\b|\bip text")


if __name__ == "__main__":
    unittest.main()
