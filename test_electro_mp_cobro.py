"""Electro oculto, statement_descriptor de MP y textos según COBRO_ON. No pega a la red."""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_mod
import cuentas


class ElectroOcultoTest(unittest.TestCase):
    def test_home_sin_boton_electro_y_api_sigue(self) -> None:
        c = TestClient(app_mod.app)
        html = c.get("/").text
        self.assertNotIn('id="mode-electro"', html)
        self.assertNotIn(">Electro</button>", html)
        self.assertIn('getElementById("mode-electro")?.', html)
        self.assertIn('id="buscar"', html)
        self.assertNotEqual(c.get("/api/electro?q=heladera").status_code, 404)


class StatementDescriptorTest(unittest.TestCase):
    def test_preferencia_lleva_baratoya(self) -> None:
        enviado: dict = {}

        class FakeResp:
            status_code = 201

            def json(self):
                return {"id": "pref-1", "init_point": "https://mp.test/init"}

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None):
                enviado.update(json or {})
                return FakeResp()

        with patch.object(cuentas, "cobro_on", return_value=True), \
             patch.object(cuentas, "cupo_on", return_value=True), \
             patch.object(cuentas, "public_base", return_value="https://baratoya.app"), \
             patch.object(cuentas, "mp_token", return_value="APP_USR-x"), \
             patch.object(cuentas.httpx, "AsyncClient", FakeClient):
            asyncio.run(cuentas.crear_preferencia("u-1", "a@example.com"))
        self.assertEqual(enviado.get("statement_descriptor"), "BARATOYA")
        self.assertEqual(enviado.get("auto_return"), "approved")


class CobroTextosTest(unittest.TestCase):
    def _get(self, path: str, on: bool) -> str:
        with patch.object(cuentas, "cobro_on", return_value=on):
            return TestClient(app_mod.app).get(path).text

    def test_legales_siguen_flag(self) -> None:
        for on in (True, False):
            t = self._get("/terminos", on)
            p = self._get("/privacidad", on)
            self.assertNotIn("cuando el cobro está activo", t + p)
            self.assertNotIn("cuando exista", p)
            if on:
                self.assertIn("el pago se procesa mediante Mercado Pago.", t)
                self.assertIn("El cobro lo hace Mercado Pago.", p)
                self.assertNotIn("todavía no está activo", t + p)
            else:
                self.assertIn("todavía no está activo", t)
                self.assertIn("El cobro todavía no está activo", p)

    def test_mensaje_tope_cliente_depende_de_cobro(self) -> None:
        html = self._get("/", True)
        self.assertIn('CUENTA.cobro ? "Para seguir sin tope', html)


if __name__ == "__main__":
    unittest.main()
