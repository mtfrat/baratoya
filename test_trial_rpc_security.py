"""Seguridad del trial: RPC activar_trial, campos protegidos, webhook MP y métricas sin cuentas de prueba."""
from __future__ import annotations

import asyncio
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import cuentas

ROOT = Path(__file__).resolve().parent
SQL = (ROOT / "supabase" / "migrations" / "baratoya_trial_rpc_protect.sql").read_text(encoding="utf-8")
UID = "11111111-1111-1111-1111-111111111111"


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).lower()


class _Resp:
    def __init__(self, status: int, payload=None, text: str = "") -> None:
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class MigracionContenidoTest(unittest.TestCase):
    def test_activar_trial_rpc_definer_idempotente(self) -> None:
        s = _norm(SQL)
        self.assertIn("create or replace function public.activar_trial() returns jsonb", s)
        self.assertIn("security definer set search_path = public", s)
        self.assertIn("uid uuid := auth.uid()", s)
        self.assertIn("if prof.trial_ends_at is null and prof.paid_at is null", s)
        self.assertIn("coalesce(prof.role, 'user') <> 'admin'", s)
        self.assertIn("set trial_ends_at = now() + interval '7 days'", s)
        self.assertIn("revoke all on function public.activar_trial() from public, anon, service_role", s)
        self.assertIn("grant execute on function public.activar_trial() to authenticated", s)

    def test_usuario_solo_edita_prefs_y_nombre(self) -> None:
        s = _norm(SQL)
        self.assertIn("revoke update on table public.profiles from anon, authenticated", s)
        self.assertIn("grant update (prefs, display_name) on table public.profiles to authenticated", s)

    def test_trigger_rechaza_campos_protegidos_y_deja_pasar_servidor(self) -> None:
        s = _norm(SQL)
        self.assertIn("if current_user in ('postgres', 'supabase_admin', 'service_role') then return new", s)
        self.assertIn("if coalesce(auth.role(), '') = 'service_role' then return new", s)
        for col in ("trial_ends_at", "plan", "is_test", "role", "paid_at", "mp_payment_id", "searches_used"):
            self.assertIn(f"new.{col} is distinct from old.{col}", s, col)
        self.assertIn("raise exception 'profiles: campo protegido", s)
        self.assertIn("errcode = '42501'", s)
        self.assertIn("new.prefs := new.prefs - 'trial_ends_at'", s)

    def test_admin_stats_excluye_test_y_admin_con_totales(self) -> None:
        s = _norm(SQL)
        self.assertIn("create or replace function public.admin_stats()", s)
        self.assertIn("not coalesce(p.is_test, false) and coalesce(p.role, 'user') <> 'admin'", s)
        self.assertIn("where not p.is_test and coalesce(p.role, 'user') <> 'admin'", s)
        for key in ("'usuarios'", "'busquedas'", "'perfiles_pagos'", "'pagos'", "'ingresos_centavos'",
                    "'usuarios_total'", "'usuarios_test'", "'usuarios_admin'", "'busquedas_total'", "'perfiles_pagos_total'"):
            self.assertIn(key, s)
        self.assertIn("grant execute on function public.admin_stats() to service_role", s)


class PrefsNoDaTrialTest(unittest.TestCase):
    def test_leer_cuenta_ignora_trial_en_prefs(self) -> None:
        futuro = (datetime.now(timezone.utc) + timedelta(days=900)).isoformat()

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                return _Resp(200, [{"plan": "free", "searches_used": 0, "paid_at": None, "role": "user",
                                    "prefs": {"trial_ends_at": futuro}, "trial_ends_at": None}])

        async def fake_activar(user_id, days=7, token=None):
            return ""  # la base no dio trial

        with patch.object(cuentas, "supabase_url", return_value="https://ex.supabase.co"), \
             patch.object(cuentas, "_user_headers", return_value={}), \
             patch.object(cuentas.httpx, "AsyncClient", FakeClient), \
             patch.object(cuentas, "activar_trial", side_effect=fake_activar):
            perfil = asyncio.run(cuentas.leer_cuenta("tok", UID))
        self.assertEqual(perfil["plan"], "free")
        self.assertFalse(perfil["trial_activo"])
        self.assertIsNone(perfil["trial_ends_at"])

    def test_consumir_ignora_trial_en_prefs(self) -> None:
        futuro = (datetime.now(timezone.utc) + timedelta(days=900)).isoformat()
        posts: list[str] = []

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                return _Resp(200, [{"id": UID, "plan": "free", "paid_at": None, "trial_ends_at": None,
                                    "role": "user", "searches_used": 5, "prefs": {"trial_ends_at": futuro}}])

            async def post(self, url, **k):
                posts.append(url)
                return _Resp(200, {"ok": False, "reason": "quota", "plan": "free", "used": 5, "remaining": 0, "limit": 5})

        with patch.object(cuentas, "cupo_on", return_value=True), \
             patch.object(cuentas, "supabase_url", return_value="https://ex.supabase.co"), \
             patch.object(cuentas, "service_key", return_value="svc"), \
             patch.object(cuentas.httpx, "AsyncClient", FakeClient):
            res = asyncio.run(cuentas.consumir(UID, "yerba"))
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "quota")
        self.assertTrue(any(u.endswith("/rpc/consume_search") for u in posts))
        self.assertFalse(any(u.endswith("/rest/v1/searches") for u in posts))


class CaminosQueSiguenAndandoTest(unittest.TestCase):
    def test_webhook_mp_marca_pago_con_rpc_y_service_role(self) -> None:
        calls: list = []

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None):
                calls.append((url, (headers or {}).get("Authorization"), json))
                return _Resp(200, {"ok": True, "plan": "paid"})

        with patch.object(cuentas, "cupo_on", return_value=True), \
             patch.object(cuentas, "supabase_url", return_value="https://ex.supabase.co"), \
             patch.object(cuentas, "service_key", return_value="svc"), \
             patch.object(cuentas.httpx, "AsyncClient", FakeClient):
            res = asyncio.run(cuentas.marcar_pago(UID, "pay-123"))
        self.assertEqual(res, {"ok": True, "plan": "paid"})
        url, auth, body = calls[0]
        self.assertTrue(url.endswith("/rest/v1/rpc/mark_profile_paid"))
        self.assertEqual(auth, "Bearer svc")
        self.assertEqual(body, {"p_user": UID, "p_payment": "pay-123"})
        # mark_profile_paid es SECURITY DEFINER (current_user postgres): el trigger lo deja pasar.
        self.assertIn("if current_user in ('postgres', 'supabase_admin', 'service_role') then return new", _norm(SQL))

    def test_prefs_se_guardan_con_jwt_del_usuario_solo_prefs(self) -> None:
        calls: list = []

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def patch(self, url, params=None, json=None, headers=None):
                calls.append((json, (headers or {}).get("Authorization")))
                return _Resp(204)

        with patch.object(cuentas, "cuentas_on", return_value=True), \
             patch.object(cuentas, "anon_key", return_value="anon"), \
             patch.object(cuentas, "supabase_url", return_value="https://ex.supabase.co"), \
             patch.object(cuentas.httpx, "AsyncClient", FakeClient):
            res = asyncio.run(cuentas.guardar_preferencias("user-tok", UID, {"banks": ["galicia"], "trial_ends_at": "2030-01-01"}))
        self.assertTrue(res["synced"])
        body, auth = calls[0]
        self.assertEqual(set(body.keys()), {"prefs"})
        self.assertNotIn("trial_ends_at", body["prefs"])
        self.assertEqual(auth, "Bearer user-tok")

    def test_codigo_no_hace_patch_de_trial(self) -> None:
        src = (ROOT / "cuentas.py").read_text(encoding="utf-8")
        self.assertNotIn('{"trial_ends_at": fin_iso}', src)
        self.assertIn("/rest/v1/rpc/activar_trial", src)


if __name__ == "__main__":
    unittest.main()
