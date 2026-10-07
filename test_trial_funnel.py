"""Trial funnel P0: await activar_trial, checkout permite trial, copy + GA hooks."""
from __future__ import annotations

from pathlib import Path

import asyncio
import inspect
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import app as app_mod
import cuentas


class ActivarTrialPersistTest(unittest.TestCase):
    def test_activar_trial_returns_iso_only_on_ok_status(self) -> None:
        class FakeResp:
            status_code = 200
            text = ""

            def json(self):
                return {"ok": True, "activado": True, "trial_ends_at": "2099-01-08T00:00:00+00:00"}

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **k):
                return FakeResp()

        uid = "11111111-1111-1111-1111-111111111111"
        with patch.object(cuentas, "cuentas_on", return_value=True), \
             patch.object(cuentas, "anon_key", return_value="anon"), \
             patch.object(cuentas, "supabase_url", return_value="https://ex.supabase.co"), \
             patch.object(cuentas.httpx, "AsyncClient", FakeClient):
            iso = asyncio.run(cuentas.activar_trial(uid, 7, token="user-tok"))
        self.assertTrue(iso)
        self.assertIn("T", iso)

    def test_activar_trial_empty_on_http_error(self) -> None:
        class FakeResp:
            status_code = 500
            text = ""

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **k):
                return FakeResp()

        uid = "11111111-1111-1111-1111-111111111111"
        with patch.object(cuentas, "cuentas_on", return_value=True), \
             patch.object(cuentas, "anon_key", return_value="anon"), \
             patch.object(cuentas, "supabase_url", return_value="https://ex.supabase.co"), \
             patch.object(cuentas.httpx, "AsyncClient", FakeClient):
            iso = asyncio.run(cuentas.activar_trial(uid, 7, token="user-tok"))
        self.assertEqual(iso, "")

    def test_leer_cuenta_awaits_activar_trial_not_create_task(self) -> None:
        src = inspect.getsource(cuentas.leer_cuenta)
        self.assertIn("await activar_trial", src)
        self.assertNotIn("create_task", src)

    def test_leer_cuenta_persists_trial(self) -> None:
        uid = "11111111-1111-1111-1111-111111111111"
        persisted = "2099-01-15T12:00:00+00:00"

        class FakeGetResp:
            status_code = 200

            def json(self):
                return [{
                    "plan": "free",
                    "searches_used": 0,
                    "paid_at": None,
                    "role": "user",
                    "prefs": {},
                    "trial_ends_at": None,
                }]

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                return FakeGetResp()

        async def fake_activar(user_id: str, days: int = 7, token: str | None = None) -> str:
            self.assertEqual(user_id, uid)
            self.assertEqual(days, 7)
            self.assertEqual(token, "tok")
            return persisted

        with patch.object(cuentas, "cupo_on", return_value=True), \
             patch.object(cuentas, "supabase_url", return_value="https://ex.supabase.co"), \
             patch.object(cuentas, "_user_headers", return_value={}), \
             patch.object(cuentas.httpx, "AsyncClient", FakeClient), \
             patch.object(cuentas, "activar_trial", side_effect=fake_activar):
            perfil = asyncio.run(cuentas.leer_cuenta("tok", uid))
        self.assertEqual(perfil["trial_ends_at"], persisted)
        self.assertTrue(perfil["trial"])
        self.assertEqual(perfil["plan"], "paid")

    def test_leer_cuenta_no_fake_trial_when_activar_fails(self) -> None:
        uid = "11111111-1111-1111-1111-111111111111"

        class FakeGetResp:
            status_code = 200

            def json(self):
                return [{
                    "plan": "free",
                    "searches_used": 0,
                    "paid_at": None,
                    "role": "user",
                    "prefs": {},
                    "trial_ends_at": None,
                }]

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                return FakeGetResp()

        async def fake_activar(user_id: str, days: int = 7, token: str | None = None) -> str:
            return ""

        with patch.object(cuentas, "cupo_on", return_value=True), \
             patch.object(cuentas, "supabase_url", return_value="https://ex.supabase.co"), \
             patch.object(cuentas, "_user_headers", return_value={}), \
             patch.object(cuentas.httpx, "AsyncClient", FakeClient), \
             patch.object(cuentas, "activar_trial", side_effect=fake_activar):
            perfil = asyncio.run(cuentas.leer_cuenta("tok", uid))
        self.assertIsNone(perfil["trial_ends_at"])
        self.assertFalse(perfil["trial"])
        self.assertFalse(perfil["trial_activo"])
        self.assertEqual(perfil["plan"], "free")



class ActivarTrialHttpTest(unittest.TestCase):
    """activar_trial usa el RPC con el JWT del usuario. Nunca PATCH ni service role."""

    def _fake(self, resp_status: int, payload, calls: list):
        class FakeResp:
            status_code = resp_status
            text = str(payload)

            def json(self_inner):
                return payload

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None):
                calls.append(("post", url, (headers or {}).get("Authorization", ""), json))
                return FakeResp()

            async def patch(self, *a, **k):
                calls.append(("patch",))
                raise AssertionError("activar_trial no debe hacer PATCH")

        return FakeClient

    def _run(self, client_cls, token="user-tok"):
        with patch.object(cuentas, "cuentas_on", return_value=True), \
             patch.object(cuentas, "service_key", return_value="svc-key"), \
             patch.object(cuentas, "anon_key", return_value="anon"), \
             patch.object(cuentas, "supabase_url", return_value="https://ex.supabase.co"), \
             patch.object(cuentas.httpx, "AsyncClient", client_cls):
            return asyncio.run(cuentas.activar_trial("11111111-1111-1111-1111-111111111111", 7, token=token))

    def test_user_jwt_llama_rpc(self) -> None:
        calls: list = []
        iso = self._run(self._fake(200, {"ok": True, "activado": True, "trial_ends_at": "2099-01-08T00:00:00+00:00"}, calls))
        self.assertEqual(iso, "2099-01-08T00:00:00+00:00")
        self.assertEqual(len(calls), 1)
        kind, url, auth, body = calls[0]
        self.assertEqual(kind, "post")
        self.assertTrue(url.endswith("/rest/v1/rpc/activar_trial"))
        self.assertEqual(auth, "Bearer user-tok")
        self.assertEqual(body, {})

    def test_idempotente_devuelve_trial_existente(self) -> None:
        calls: list = []
        iso = self._run(self._fake(200, {"ok": True, "activado": False, "trial_ends_at": "2026-10-14T20:43:03+00:00"}, calls))
        self.assertEqual(iso, "2026-10-14T20:43:03+00:00")

    def test_sin_token_no_llama_ni_usa_service_role(self) -> None:
        calls: list = []
        iso = self._run(self._fake(200, {"ok": True}, calls), token=None)
        self.assertEqual(iso, "")
        self.assertEqual(calls, [])

    def test_rpc_falla_devuelve_vacio(self) -> None:
        calls: list = []
        iso = self._run(self._fake(403, {"message": "permission denied for function activar_trial"}, calls))
        self.assertEqual(iso, "")

    def test_rpc_sin_trial_devuelve_vacio(self) -> None:
        calls: list = []
        iso = self._run(self._fake(200, {"ok": True, "activado": False, "trial_ends_at": None}, calls))
        self.assertEqual(iso, "")


class CheckoutTrialAllowedTest(unittest.TestCase):
    def test_checkout_allows_active_trial(self) -> None:
        called = {"pref": False}

        async def fake_usuario(token):
            return {"id": "11111111-1111-1111-1111-111111111111", "email": "a@ex.com"}

        async def fake_leer(token, uid):
            return {
                "plan": "paid",
                "plan_base": "free",
                "trial": True,
                "trial_activo": True,
                "paid_at": None,
            }

        async def fake_pref(uid, email):
            called["pref"] = True
            return {"ok": True, "status": 200, "init_point": "https://mp.test/pay", "preference_id": "pref-9"}

        with patch.object(cuentas, "cuentas_on", return_value=True), \
             patch.object(cuentas, "bearer", return_value="tok"), \
             patch.object(cuentas, "usuario", side_effect=fake_usuario), \
             patch.object(cuentas, "leer_cuenta", side_effect=fake_leer), \
             patch.object(cuentas, "crear_preferencia", side_effect=fake_pref):
            r = TestClient(app_mod.app).post("/api/cuenta/checkout")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(called["pref"])
        self.assertEqual(r.json().get("init_point"), "https://mp.test/pay")
        self.assertEqual(r.json().get("preference_id"), "pref-9")

    def test_checkout_blocks_real_paid(self) -> None:
        async def fake_usuario(token):
            return {"id": "11111111-1111-1111-1111-111111111111", "email": "a@ex.com"}

        async def fake_leer(token, uid):
            return {
                "plan": "paid",
                "plan_base": "paid",
                "trial": False,
                "paid_at": "2026-01-01T00:00:00+00:00",
            }

        with patch.object(cuentas, "cuentas_on", return_value=True), \
             patch.object(cuentas, "bearer", return_value="tok"), \
             patch.object(cuentas, "usuario", side_effect=fake_usuario), \
             patch.object(cuentas, "leer_cuenta", side_effect=fake_leer):
            r = TestClient(app_mod.app).post("/api/cuenta/checkout")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("already"))


class CopyAndGaTest(unittest.TestCase):
    def test_home_trial_first_and_ga_hooks(self) -> None:
        html = TestClient(app_mod.app).get("/").text
        self.assertIn("Probar 7d Plus gratis", html)
        self.assertIn("Empezar 7d gratis", html)
        self.assertIn("Suscribirme", html)
        self.assertIn("¿El trial cobra solo?", html)
        self.assertIn("No hay cobro automático el día 8", html)
        self.assertIn('gtag("event", name', html)
        self.assertIn("sign_up", html)
        self.assertIn("trial_start", html)
        self.assertIn("begin_checkout", html)
        self.assertIn("/api/cuenta/activar-trial", html)
        src = Path("cuentas.py").read_text(encoding="utf-8")
        self.assertNotIn("asyncio.create_task", src)
        self.assertNotIn("Fallback en memoria", src)

    def test_planes_trial_first(self) -> None:
        html = TestClient(app_mod.app).get("/planes").text
        self.assertIn("Probar 7d Plus gratis", html)
        self.assertIn("Empezar 7d gratis", html)
        self.assertIn("view_plans", html)
        self.assertIn("begin_checkout", html)
        self.assertIn("¿El trial cobra solo?", html)


class ActivarTrialEndpointTest(unittest.TestCase):
    def test_endpoint_returns_trial_from_leer(self) -> None:
        async def fake_usuario(token):
            return {"id": "11111111-1111-1111-1111-111111111111", "email": "a@ex.com"}

        async def fake_leer(token, uid):
            return {
                "plan": "paid",
                "plan_base": "free",
                "trial": True,
                "trial_activo": True,
                "trial_ends_at": "2099-01-01T00:00:00+00:00",
                "trial_ends_at_texto": "1 ene 2099",
            }

        with patch.object(cuentas, "cuentas_on", return_value=True), \
             patch.object(cuentas, "bearer", return_value="tok"), \
             patch.object(cuentas, "usuario", side_effect=fake_usuario), \
             patch.object(cuentas, "leer_cuenta", side_effect=fake_leer):
            r = TestClient(app_mod.app).post("/api/cuenta/activar-trial")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(body.get("trial_activo"))
        self.assertEqual(body.get("trial_ends_at"), "2099-01-01T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
