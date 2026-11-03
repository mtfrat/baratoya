"""Hub de commodity conocido bajo el umbral: 302 temporal a /precios, no 404."""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ["BARATOYA_PRECIOS_OFFLINE"] = "1"

from fastapi.testclient import TestClient

import app as app_mod
import precios_seo


class CommoditySinUmbralTest(unittest.TestCase):
    def test_hub_conocido_sin_datos_redirige_302(self) -> None:
        c = TestClient(app_mod.app)
        with mock.patch.object(precios_seo, "pagina_commodity", return_value=None):
            r = c.get("/precios/harina", follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["location"], "/precios")

    def test_slug_desconocido_sigue_404(self) -> None:
        c = TestClient(app_mod.app)
        r = c.get("/precios/no-existe-este-producto-xyz", follow_redirects=False)
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
