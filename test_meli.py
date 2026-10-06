"""Mercado Libre: el catálogo público está cerrado. No pega a la red."""
from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_mod
import electro
import meli


def _reset_token() -> None:
    meli._token["value"] = ""
    meli._token["exp"] = 0.0


class _Resp:
    def __init__(self, code: int, body: dict):
        self.status_code = code
        self._body = body

    def json(self) -> dict:
        return self._body


class _Client:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, data=None, headers=None):
        return _Resp(200, {"access_token": "tok", "expires_in": 3600})

    async def get(self, url, params=None, headers=None):
        return _Resp(
            403,
            {
                "message": "forbidden",
                "error": "forbidden",
                "status": 403,
                "results": [
                    {
                        "title": "Leche entera",
                        "price": 1500,
                        "permalink": "https://articulo.mercadolibre.com.ar/MLA-1",
                    }
                ],
            },
        )


class _ClientHttp:
    """Token ok y un status distinto de 403, para no pisar el aviso de catálogo cerrado."""

    def __init__(self, code: int):
        self.code = code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, data=None, headers=None):
        return _Resp(200, {"access_token": "tok", "expires_in": 3600})

    async def get(self, url, params=None, headers=None):
        return _Resp(self.code, {"results": []})


class BuscarMeliTest(unittest.TestCase):
    def setUp(self) -> None:
        _reset_token()

    def test_apagado_no_llama_a_la_api(self) -> None:
        env = {
            "MLA_PUBLIC_SEARCH": "false",
            "ENABLE_MLA": "true",
            "MERCADOLIBRE_CLIENT_ID": "app-id",
            "MERCADOLIBRE_CLIENT_SECRET": "app-secret",
        }
        with patch.dict(os.environ, env, clear=False), patch("meli.httpx.AsyncClient") as client:
            out = asyncio.run(meli.buscar_meli("leche"))
        client.assert_not_called()
        self.assertEqual(out["omitido"], "catalogo_publico_cerrado")
        self.assertEqual(out["aviso"], "")
        self.assertEqual(out["productos"], [])
        self.assertFalse(out["ok"])
        self.assertEqual(out["n"], 0)

    def test_403_aviso_honesto_sin_precios(self) -> None:
        env = {
            "MLA_PUBLIC_SEARCH": "true",
            "MERCADOLIBRE_CLIENT_ID": "app-id",
            "MERCADOLIBRE_CLIENT_SECRET": "app-secret",
        }
        with patch.dict(os.environ, env, clear=False), patch("meli.httpx.AsyncClient", _Client):
            out = asyncio.run(meli.buscar_meli("leche"))
        self.assertEqual(out["http"], 403)
        self.assertFalse(out["ok"])
        self.assertEqual(out["productos"], [])
        self.assertEqual(out["aviso"], meli.AVISO_CATALOGO_CERRADO)
        self.assertNotIn("omitido", out)
        self.assertNotIn("no dejó ver", out["aviso"])

    def test_otro_http_no_usa_el_aviso_de_catalogo(self) -> None:
        env = {
            "MLA_PUBLIC_SEARCH": "true",
            "MERCADOLIBRE_CLIENT_ID": "app-id",
            "MERCADOLIBRE_CLIENT_SECRET": "app-secret",
        }
        with patch.dict(os.environ, env, clear=False), patch("meli.httpx.AsyncClient", lambda *a, **k: _ClientHttp(500)):
            out = asyncio.run(meli.buscar_meli("leche"))
        self.assertEqual(out["http"], 500)
        self.assertEqual(out["aviso"], "búsqueda http 500")
        self.assertEqual(out["productos"], [])

    def test_probe_sin_credenciales_no_inventa(self) -> None:
        env = {
            "MLA_PUBLIC_SEARCH": "true",
            "MERCADOLIBRE_CLIENT_ID": "",
            "MERCADOLIBRE_CLIENT_SECRET": "",
        }
        with patch.dict(os.environ, env, clear=False), patch("meli.httpx.AsyncClient") as client:
            out = asyncio.run(meli.buscar_meli("leche"))
        client.assert_not_called()
        self.assertEqual(out["aviso"], "sin credenciales de la app")
        self.assertEqual(out["productos"], [])


class BusquedaSinBannerTest(unittest.TestCase):
    """Con el catálogo apagado, súper sigue y no aparece el aviso de fallo."""

    def test_buscar_omite_mla_y_deja_la_cadena(self) -> None:
        async def gate(request, q):
            return {"ok": True, "plan": "free", "used": 1, "remaining": 4, "limit": 5, "prefs": {}}

        async def super_(q, consultas=None):
            return {
                "productos": [],
                "q_usada": q,
                "fuentes": [{"tienda": "Dia", "tienda_id": "dia", "http": 200, "ok": True, "n": 1}],
            }

        async def promos():
            return []

        async def pc(path, params):
            return 200, {"productos": []}

        env = {"MLA_PUBLIC_SEARCH": "false", "ENABLE_MLA": "true"}
        with patch.dict(os.environ, env, clear=False), \
                patch.object(app_mod, "ENABLE_MLA", True), \
                patch.object(app_mod, "_exigir_busqueda", gate), \
                patch.object(app_mod, "buscar_super", super_), \
                patch.object(app_mod, "buscar_promos", promos), \
                patch.object(app_mod, "pc_get", pc), \
                patch("meli.httpx.AsyncClient") as client:
            r = TestClient(app_mod.app).get("/api/buscar?q=leche")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        cadenas = body["cadenas"]
        self.assertTrue(any(f.get("tienda_id") == "dia" for f in cadenas))
        self.assertFalse(any(f.get("tienda_id") == "mla" for f in cadenas))
        self.assertNotIn("Mercado Libre", r.text)
        self.assertNotIn(meli.AVISO_CATALOGO_CERRADO, r.text)
        client.assert_not_called()

    def test_electro_omite_fuente_mla(self) -> None:
        async def vtex(client, store, q):
            return {
                "tienda": store["nombre"],
                "tienda_id": store["id"],
                "http": 206,
                "ok": True,
                "productos": [],
            }

        env = {"MLA_PUBLIC_SEARCH": "false"}
        with patch.dict(os.environ, env, clear=False), \
                patch.object(electro, "_one", vtex), \
                patch("meli.httpx.AsyncClient") as client:
            data = asyncio.run(electro.buscar_electro("heladera"))
        ids = [f.get("tienda_id") for f in data["fuentes"]]
        self.assertNotIn("mla", ids)
        self.assertIn("fravega", ids)
        self.assertEqual(data["mla"], "catalogo_publico_cerrado")
        self.assertEqual(data["productos"], [])
        # El cliente de 15s es el de Mercado Libre. Electro abre el suyo (20s) y no busca en ML.
        self.assertEqual(client.call_count, 1)
        self.assertEqual(client.call_args.kwargs.get("timeout"), 20.0)

    def test_ui_no_pinta_banner_si_la_fuente_viene_omitida(self) -> None:
        html = Path("templates/index.html").read_text(encoding="utf-8")
        self.assertIn("if (!ml || ml.omitido) return \"\";", html)


if __name__ == "__main__":
    unittest.main()
