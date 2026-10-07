"""Búsquedas de usuarios en trial: se insertan en public.searches y un error no se traga."""
from __future__ import annotations

import asyncio
import contextlib
import io
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import cuentas

UID = "00000000-0000-0000-0000-0000000000a1"
ROOT = Path(__file__).resolve().parent


class _Resp:
    def __init__(self, status: int, payload=None, text: str = "") -> None:
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class _Client:
    def __init__(self, profile: dict, insert_resp: _Resp, rpc_resp: _Resp | None = None) -> None:
        self.profile = profile
        self.insert_resp = insert_resp
        self.rpc_resp = rpc_resp or _Resp(200, {"ok": True, "plan": "free", "used": 1, "remaining": 4, "limit": 5})
        self.posts: list[tuple[str, dict, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        return _Resp(200, [self.profile])

    async def post(self, url, headers=None, json=None, **kwargs):
        self.posts.append((url, headers or {}, json or {}))
        if url.endswith("/rest/v1/searches"):
            return self.insert_resp
        return self.rpc_resp


def _perfil_trial() -> dict:
    fin = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    return {"id": UID, "plan": "free", "paid_at": None, "trial_ends_at": fin, "role": "user", "searches_used": 0}


def _run(client: _Client) -> tuple[dict, str]:
    out = io.StringIO()
    with patch.object(cuentas, "cupo_on", return_value=True), \
         patch.object(cuentas, "supabase_url", return_value="https://x.supabase.co"), \
         patch.object(cuentas, "service_key", return_value="svc-key-no-se-loguea"), \
         patch("httpx.AsyncClient", return_value=client), \
         contextlib.redirect_stdout(out):
        res = asyncio.run(cuentas.consumir(UID, "  yerba playadito 1kg  "))
    return res, out.getvalue()


class TrialSearchLoggingTest(unittest.TestCase):
    def test_trial_inserta_busqueda_con_service_role(self) -> None:
        client = _Client(_perfil_trial(), _Resp(201, None, ""))
        res, log = _run(client)
        self.assertTrue(res["ok"])
        self.assertTrue(res["trial"])
        inserts = [p for p in client.posts if p[0].endswith("/rest/v1/searches")]
        self.assertEqual(len(inserts), 1)
        url, headers, body = inserts[0]
        self.assertEqual(body, {"user_id": UID, "query": "yerba playadito 1kg"})
        self.assertEqual(headers.get("Authorization"), "Bearer svc-key-no-se-loguea")
        # El trial no pasa por el RPC de cupo.
        self.assertFalse(any("consume_search" in p[0] for p in client.posts))
        self.assertNotIn("searches insert", log)

    def test_trial_insert_no_2xx_se_loguea_sin_secretos(self) -> None:
        err = '{"code":"42501","message":"permission denied for table searches"}'
        client = _Client(_perfil_trial(), _Resp(403, None, err))
        res, log = _run(client)
        # La búsqueda sigue (no se castiga al usuario), pero el error queda en el log.
        self.assertTrue(res["ok"])
        self.assertIn("searches insert HTTP 403", log)
        self.assertIn("42501", log)
        self.assertIn("user=00000000…", log)
        self.assertNotIn("svc-key-no-se-loguea", log)

    def test_free_sigue_usando_rpc_consume_search(self) -> None:
        perfil = {"id": UID, "plan": "free", "paid_at": None, "trial_ends_at": None, "role": "user", "searches_used": 0}
        client = _Client(perfil, _Resp(201))
        res, _log = _run(client)
        self.assertTrue(res["ok"])
        self.assertEqual(res["remaining"], 4)
        self.assertTrue(any(p[0].endswith("/rest/v1/rpc/consume_search") for p in client.posts))
        self.assertFalse(any(p[0].endswith("/rest/v1/searches") for p in client.posts))

    def test_migracion_da_grants_a_searches(self) -> None:
        sql = (ROOT / "supabase" / "migrations" / "baratoya_searches_grants.sql").read_text(encoding="utf-8")
        self.assertIn("grant select, insert on table public.searches to service_role", sql)
        self.assertIn("grant select on table public.searches to authenticated", sql)
        self.assertIn("revoke insert, update, delete on table public.searches from anon, authenticated", sql)

    def test_migracion_is_test_protegida(self) -> None:
        sql = (ROOT / "supabase" / "migrations" / "baratoya_profiles_is_test.sql").read_text(encoding="utf-8")
        self.assertIn("add column if not exists is_test boolean not null default false", sql)
        self.assertIn("new.is_test := old.is_test", sql)


if __name__ == "__main__":
    unittest.main()
