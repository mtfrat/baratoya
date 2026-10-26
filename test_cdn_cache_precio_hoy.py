"""CDN cache de páginas públicas, memo de promos y ficha de precio con promos de hoy. Sin red."""
from __future__ import annotations

import asyncio
import json
import os
import re
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

os.environ["BARATOYA_PRECIOS_OFFLINE"] = "1"

from fastapi.testclient import TestClient

import app as app_mod
import precios_seo
import promos_hoy

ART = timezone(timedelta(hours=-3))


def _smaxage(header: str) -> int:
    m = re.search(r"s-maxage=(\d+)", header)
    return int(m.group(1)) if m else -1


class CacheControlTests(unittest.TestCase):
    def test_hasta_medianoche_argentina(self):
        h = app_mod.cache_control_publico(datetime(2026, 10, 19, 20, 0, tzinfo=ART))
        self.assertEqual(_smaxage(h), 4 * 3600)
        self.assertIn("max-age=0", h)
        self.assertIn("stale-while-revalidate=86400", h)
        self.assertIn("public", h)

    def test_utc_se_pasa_a_argentina(self):
        # 02:30 UTC = 23:30 ART: quedan 30 minutos hasta el corte de Argentina.
        h = app_mod.cache_control_publico(datetime(2026, 10, 20, 2, 30, tzinfo=timezone.utc))
        self.assertEqual(_smaxage(h), 1800)

    def test_minimo_un_minuto(self):
        h = app_mod.cache_control_publico(datetime(2026, 10, 19, 23, 59, 50, tzinfo=ART))
        self.assertEqual(_smaxage(h), 60)

    def test_rutas(self):
        for path in ("/", "/precios", "/precios/leche", "/promos-bancarias-supermercados/coto",
                     "/descuentos-supermercados/lunes", "/sitemap.xml", "/planes"):
            self.assertTrue(app_mod.es_publica_cacheable(path), path)
        for path in ("/admin", "/admin/usuarios", "/api/promos", "/api/buscar", "/health", "/preciosx"):
            self.assertFalse(app_mod.es_publica_cacheable(path), path)


class MiddlewareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app_mod.app).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_publicas_con_s_maxage(self):
        slug = precios_seo.vistas_publicadas()[0]["slug"]
        for path in ("/", "/promos-bancarias-supermercados", "/descuentos-supermercados/lunes",
                     "/precios", f"/precios/{slug}", "/sitemap.xml"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertGreater(_smaxage(r.headers.get("cache-control", "")), 0, path)
        head = self.client.head("/sitemap.xml")
        self.assertGreater(_smaxage(head.headers.get("cache-control", "")), 0)

    def test_privadas_y_errores_sin_cdn(self):
        r = self.client.get("/precios/no-existe-este-producto")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(_smaxage(r.headers.get("cache-control", "")), -1)
        r = self.client.get("/health")
        self.assertEqual(_smaxage(r.headers.get("cache-control", "")), -1)
        r = self.client.get("/admin")
        self.assertEqual(_smaxage(r.headers.get("cache-control", "")), -1)


class CdnCortoTests(unittest.TestCase):
    def test_corto_tope_5_min(self):
        h = app_mod.cache_control_publico(datetime(2026, 10, 19, 9, 0, tzinfo=ART), corto=True)
        self.assertEqual(_smaxage(h), 300)
        h = app_mod.cache_control_publico(datetime(2026, 10, 19, 23, 58, tzinfo=ART), corto=True)
        self.assertEqual(_smaxage(h), 120)

    def test_precios_con_lectura_pendiente_pide_cache_corto(self):
        slug = precios_seo.vistas_publicadas()[0]["slug"]
        with TestClient(app_mod.app) as c:
            with mock.patch.object(precios_seo, "asegurar_producto", mock.AsyncMock(return_value=False)), \
                 mock.patch.object(precios_seo, "asegurar_hub", mock.AsyncMock(return_value=False)):
                for path in (f"/precios/{slug}", "/precios"):
                    r = c.get(path)
                    self.assertEqual(r.status_code, 200)
                    self.assertLessEqual(_smaxage(r.headers["cache-control"]), 300, path)
            with mock.patch.object(precios_seo, "asegurar_producto", mock.AsyncMock(return_value=True)):
                r = c.get(f"/precios/{slug}")
                self.assertEqual(_smaxage(r.headers["cache-control"]), _smaxage(app_mod.cache_control_publico()))

    def test_refrescar_informa_pendientes(self):
        async def correr():
            async def lento(spec):
                await asyncio.sleep(0.2)
                return None
            precios_seo._en_curso.clear()
            precios_seo._fallo.clear()
            slug = precios_seo.CATALOGO[1]["slug"]
            with mock.patch.object(precios_seo, "_offline", return_value=False), \
                 mock.patch.object(precios_seo, "_vencido", return_value=True), \
                 mock.patch.object(precios_seo, "leer_en_vivo", side_effect=lento):
                self.assertFalse(await precios_seo._refrescar([slug], espera=0.01))
                await asyncio.sleep(0.3)
            self.assertTrue(await precios_seo._refrescar([], espera=0.01))
        asyncio.run(correr())


class MemoPromosTests(unittest.TestCase):
    def setUp(self):
        promos_hoy._ITEMS_MEMO = None

    def test_una_cuenta_por_dia_y_carga(self):
        hoy = date(2026, 10, 19)
        real = promos_hoy._items_publicos_calc
        with mock.patch.object(promos_hoy, "_items_publicos_calc", side_effect=real) as calc:
            a = promos_hoy._items_publicos(hoy)
            for _ in range(50):
                promos_hoy.cadenas_indexables(hoy)
            self.assertEqual(calc.call_count, 1)
            promos_hoy._items_publicos(hoy + timedelta(days=1))
            self.assertEqual(calc.call_count, 2)
            nuevos = list(promos_hoy.cargar())
            with mock.patch.object(promos_hoy, "cargar", lambda forzar=False: nuevos):
                promos_hoy._items_publicos(hoy + timedelta(days=1))
            self.assertEqual(calc.call_count, 3)
        self.assertEqual(a, real(hoy))

    def test_copias(self):
        hoy = date(2026, 10, 19)
        a = promos_hoy._items_publicos(hoy)
        self.assertTrue(a)
        a[0]["banco"] = "TOCADO"
        a[0]["day_ids"].append(99)
        b = promos_hoy._items_publicos(hoy)
        self.assertNotEqual(b[0]["banco"], "TOCADO")
        self.assertNotIn(99, b[0]["day_ids"])


class RefrescoNoBloqueaTests(unittest.TestCase):
    def setUp(self):
        precios_seo._en_curso.clear()
        precios_seo._fallo.clear()

    def test_espera_acotada_y_tarea_compartida(self):
        slug = precios_seo.CATALOGO[0]["slug"]
        llamadas = []

        async def lento(spec):
            llamadas.append(spec["slug"])
            await asyncio.sleep(0.3)
            return None

        async def correr():
            with mock.patch.object(precios_seo, "_offline", return_value=False), \
                 mock.patch.object(precios_seo, "_vencido", return_value=True), \
                 mock.patch.object(precios_seo, "leer_en_vivo", side_effect=lento), \
                 mock.patch.object(precios_seo, "ESPERA_REQUEST_S", 0.02):
                t0 = asyncio.get_running_loop().time()
                await asyncio.gather(precios_seo.asegurar_producto(slug), precios_seo.asegurar_producto(slug))
                tardo = asyncio.get_running_loop().time() - t0
                self.assertLess(tardo, 0.2)
                await asyncio.sleep(0.4)  # la lectura sigue sola y termina
                self.assertEqual(llamadas, [slug])
                # Falló (None): no se reintenta dentro del backoff.
                await precios_seo.asegurar_producto(slug)
                self.assertEqual(llamadas, [slug])
                self.assertIn(slug, precios_seo._fallo)

        asyncio.run(correr())


class FichaHoyTests(unittest.TestCase):
    hoy = date(2026, 10, 19)  # lunes

    def test_unidad_de_medida(self):
        self.assertEqual(precios_seo.unidad_de_medida("900 ml"), ("litro", 0.9))
        self.assertEqual(precios_seo.unidad_de_medida("1 kg"), ("kilo", 1.0))
        self.assertEqual(precios_seo.unidad_de_medida("200 g"), ("kilo", 0.2))
        self.assertIsNone(precios_seo.unidad_de_medida("pack x4"))
        self.assertIsNone(precios_seo.unidad_de_medida("pack x25, 50 g"))

    def _ficha_con_medida(self):
        for v in precios_seo.vistas_publicadas():
            m = precios_seo.unidad_de_medida(v.get("tamano") or "")
            if m and abs(m[1] - 1) > 1e-9:
                return precios_seo.pagina_producto(v["slug"], self.hoy), m
        self.skipTest("sin ficha con envase distinto de 1 L / 1 kg")

    def test_precio_por_litro_es_cuenta_de_la_tabla(self):
        vista, (unidad, base) = self._ficha_con_medida()
        self.assertEqual(vista["unidad"], unidad)
        for o in vista["ofertas"]:
            self.assertEqual(o["unidad_txt"], precios_seo.peso(round(o["precio"] / base)))
        self.assertTrue(any(q["q"].startswith(f"¿Cuánto sale el {unidad} de") for q in vista["faq"]))

    def test_promos_de_hoy_salen_del_archivo(self):
        por_cadena = promos_hoy.promos_de_hoy_por_cadena(self.hoy)
        items = [it for it in promos_hoy._items_publicos(self.hoy) if 0 in it["day_ids"]]
        for v in precios_seo.vistas_publicadas():
            vista = precios_seo.pagina_producto(v["slug"], self.hoy)
            tiendas = {o["tienda_id"] for o in vista["ofertas"]}
            for p in vista["promos_hoy"]:
                info = next(i for i in por_cadena.values() if i["href"] == p["href"])
                self.assertIn(info["chain_id"], tiendas)
                propios = [it for it in items if it["chain_id"] == info["chain_id"]]
                self.assertEqual(info["n"], len(propios))
                pcts = [it["percent"] for it in propios if "percent" in it]
                if pcts:
                    self.assertIn(f"hasta {promos_hoy._pct_publico(max(pcts))}%", p["linea"])
            # FAQ JSON-LD = FAQ visible
            ld = json.loads(vista["ld_faq"])
            self.assertEqual([q["name"] for q in ld["mainEntity"]], [q["q"] for q in vista["faq"]])
            self.assertTrue(any(q["q"].startswith("¿Qué supermercado tiene promo bancaria hoy") for q in vista["faq"]))

    def test_html_ficha(self):
        vista, (unidad, _b) = self._ficha_con_medida()
        with TestClient(app_mod.app) as c:
            html = c.get(vista["href"]).text
        self.assertIn(f"Por {unidad}</th>", html)
        self.assertIn("Promos bancarias hoy", html)
        self.assertIn('href="/descuentos-supermercados/', html)
        self.assertEqual(html.count("application/ld+json"), 3)


if __name__ == "__main__":
    unittest.main()
