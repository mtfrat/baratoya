"""Plus pago vence a los 30 días (Checkout Pro es pago único, no suscripción)."""
from __future__ import annotations

import asyncio
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_mod
import cuentas

ROOT = Path(__file__).resolve().parent
SQL = re.sub(r"\s+", " ", (ROOT / "supabase" / "migrations" / "baratoya_plus_expiry.sql").read_text(encoding="utf-8")).lower()
UID = "11111111-1111-1111-1111-111111111111"


def _iso(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


class _Resp:
    def __init__(self, status: int, payload=None) -> None:
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class PlanEfectivoTest(unittest.TestCase):
    def test_pago_vigente_es_plus(self) -> None:
        c = cuentas.calcular_plan_efectivo("paid", _iso(-3), None, "user", _iso(27))
        self.assertEqual(c["plan_efectivo"], "paid")
        self.assertTrue(c["plus_activo"])
        self.assertFalse(c["plus_vencido"])

    def test_pago_vencido_vuelve_a_free(self) -> None:
        c = cuentas.calcular_plan_efectivo("paid", _iso(-40), _iso(-45), "user", _iso(-10))
        self.assertEqual(c["plan_efectivo"], "free")
        self.assertFalse(c["plus_activo"])
        self.assertTrue(c["plus_vencido"])

    def test_paid_sin_paid_until_no_es_eterno(self) -> None:
        c = cuentas.calcular_plan_efectivo("paid", _iso(-400), None, "user", None)
        self.assertEqual(c["plan_efectivo"], "free")
        self.assertTrue(c["plus_vencido"])

    def test_admin_sigue_sin_tope(self) -> None:
        self.assertEqual(cuentas.calcular_plan_efectivo("free", None, None, "admin")["plan_efectivo"], "paid")

    def test_puede_renovar(self) -> None:
        self.assertTrue(cuentas.puede_renovar(None))
        self.assertTrue(cuentas.puede_renovar(_iso(-1)))
        self.assertTrue(cuentas.puede_renovar(_iso(5)))
        self.assertFalse(cuentas.puede_renovar(_iso(20)))


class LeerCuentaTest(unittest.TestCase):
    def _leer(self, row: dict):
        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                return _Resp(200, [row])

        async def no_trial(*a, **k):
            return ""

        with patch.object(cuentas, "supabase_url", return_value="https://ex.supabase.co"), \
             patch.object(cuentas, "_user_headers", return_value={}), \
             patch.object(cuentas.httpx, "AsyncClient", FakeClient), \
             patch.object(cuentas, "activar_trial", side_effect=no_trial):
            return asyncio.run(cuentas.leer_cuenta("tok", UID))

    def test_plus_hasta_fecha(self) -> None:
        hasta = _iso(20)
        perfil = self._leer({"plan": "paid", "searches_used": 5, "paid_at": _iso(-10), "role": "user",
                             "prefs": {}, "trial_ends_at": _iso(-20), "paid_until": hasta})
        self.assertEqual(perfil["plan"], "paid")
        self.assertTrue(perfil["plus_activo"])
        self.assertEqual(perfil["paid_until"], hasta)
        self.assertIn("ART", perfil["paid_until_texto"])
        self.assertFalse(perfil["puede_renovar"])

    def test_vencido_vuelve_a_cupo_free(self) -> None:
        perfil = self._leer({"plan": "paid", "searches_used": 2, "paid_at": _iso(-40), "role": "user",
                             "prefs": {}, "trial_ends_at": _iso(-50), "paid_until": _iso(-10)})
        self.assertEqual(perfil["plan"], "free")
        self.assertTrue(perfil["plus_vencido"])
        self.assertEqual(perfil["remaining"], 3)
        self.assertTrue(perfil["puede_renovar"])


class CheckoutRenovarTest(unittest.TestCase):
    def _post(self, perfil: dict, crear=None):
        async def fake_usuario(token):
            return {"id": UID, "email": "a@ex.com"}

        async def fake_leer(token, uid):
            return perfil

        async def fake_crear(uid, email):
            return {"ok": True, "status": 200, "init_point": "https://mp.test/pay"}

        with patch.object(cuentas, "cuentas_on", return_value=True), \
             patch.object(cuentas, "bearer", return_value="tok"), \
             patch.object(cuentas, "usuario", side_effect=fake_usuario), \
             patch.object(cuentas, "leer_cuenta", side_effect=fake_leer), \
             patch.object(cuentas, "crear_preferencia", side_effect=crear or fake_crear):
            return TestClient(app_mod.app).post("/api/cuenta/checkout")

    def test_vencido_puede_pagar_de_nuevo(self) -> None:
        r = self._post({"plan": "free", "paid_at": _iso(-40), "plus_activo": False, "plus_vencido": True, "puede_renovar": True})
        self.assertEqual(r.json().get("init_point"), "https://mp.test/pay")

    def test_por_vencer_puede_renovar(self) -> None:
        r = self._post({"plan": "paid", "paid_at": _iso(-25), "plus_activo": True, "puede_renovar": True})
        self.assertEqual(r.json().get("init_point"), "https://mp.test/pay")

    def test_vigente_lejos_bloquea_con_fecha(self) -> None:
        r = self._post({"plan": "paid", "paid_at": _iso(-2), "plus_activo": True, "puede_renovar": False,
                        "paid_until_texto": "13 nov 2026, 21:46 ART"})
        self.assertTrue(r.json().get("already"))
        self.assertIn("Plus está activo hasta 13 nov 2026", r.json().get("error"))


class WebhookIdempotenteTest(unittest.TestCase):
    def _aviso(self, marked: dict):
        pago = {"status": "approved", "currency_id": "ARS", "external_reference": UID,
                "transaction_amount": cuentas.plan_cents() / 100}

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                return _Resp(200, pago)

        async def fake_marcar(uid, pid):
            return marked

        with patch.object(cuentas, "cobro_on", return_value=True), \
             patch.object(cuentas, "cupo_on", return_value=True), \
             patch.object(cuentas, "mp_token", return_value="x"), \
             patch.object(cuentas.httpx, "AsyncClient", FakeClient), \
             patch.object(cuentas, "marcar_pago", side_effect=fake_marcar):
            return asyncio.run(cuentas.procesar_aviso({}, {"type": "payment", "data": {"id": "123456"}}))

    def test_primer_aviso_devuelve_paid_until(self) -> None:
        res = self._aviso({"ok": True, "plan": "paid", "duplicate": False, "paid_until": "2026-11-13T00:00:00+00:00"})
        self.assertEqual(res["status"], 200)
        self.assertEqual(res["body"]["paid_until"], "2026-11-13T00:00:00+00:00")
        self.assertNotIn("duplicate", res["body"])

    def test_aviso_repetido_no_falla_y_marca_duplicate(self) -> None:
        res = self._aviso({"ok": True, "plan": "paid", "duplicate": True, "paid_until": "2026-11-13T00:00:00+00:00"})
        self.assertEqual(res["status"], 200)
        self.assertTrue(res["body"]["duplicate"])


class MigracionTest(unittest.TestCase):
    def test_columna_backfill_y_tabla_pagos(self) -> None:
        self.assertIn("add column if not exists paid_until timestamptz", SQL)
        self.assertIn("set paid_until = paid_at + interval '30 days' where paid_at is not null and paid_until is null", SQL)
        self.assertIn("payment_id text primary key", SQL)
        self.assertIn("revoke all on table public.mp_payments from public, anon, authenticated", SQL)

    def test_mark_profile_paid_idempotente_y_suma_dias(self) -> None:
        self.assertIn("on conflict (payment_id) do nothing", SQL)
        self.assertIn("'duplicate', true", SQL)
        self.assertIn("greatest(coalesce(prev, now()), now()) + make_interval(days => d)", SQL)
        self.assertIn("grant execute on function public.mark_profile_paid(uuid, text, integer) to service_role", SQL)

    def test_consume_search_respeta_vencimiento(self) -> None:
        self.assertIn("prof.plan = 'paid' and prof.paid_until is not null and prof.paid_until > now()", SQL)

    def test_paid_until_protegido_por_trigger(self) -> None:
        self.assertIn("new.paid_until is distinct from old.paid_until", SQL)
        for col in ("trial_ends_at", "plan", "is_test", "role", "paid_at", "mp_payment_id", "searches_used"):
            self.assertIn(f"new.{col} is distinct from old.{col}", SQL)
        self.assertIn("errcode = '42501'", SQL)


class UiTest(unittest.TestCase):
    def test_home_tiene_plus_hasta_y_renovar(self) -> None:
        html = TestClient(app_mod.app).get("/").text
        self.assertIn('"Plus hasta " + cj.paid_until_texto', html)
        self.assertIn('id="plus-renovar"', html)
        self.assertIn("Renovar Plus", html)


if __name__ == "__main__":
    unittest.main()
