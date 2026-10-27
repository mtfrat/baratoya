"""Páginas por cadena (20/10): resumen de la semana, hoy vs otras cadenas y FAQ propias.

Todo sale de las tarjetas publicadas (_items_publicos). Sin red.
"""
from __future__ import annotations

import json
import os
import re
import unittest
from datetime import date
from unittest import mock

os.environ["BARATOYA_PRECIOS_OFFLINE"] = "1"

from fastapi.testclient import TestClient

import app as app_mod
import promos_hoy
from promos_hoy import (
    SEO_PATH,
    _con_condicion,
    descripcion_cadena_hoy,
    h1_cadena_hoy,
    pagina_seo_cadena,
    resumen_semana_cadena,
    titulo_cadena,
    titulo_cadena_hoy,
)

MARTES = date(2026, 10, 20)


def _it(banco, oferta, days, percent=None, tope=None, tope_num=None, nota=None, canal="online y sucursal", chain="jumbo"):
    item = {"chain_id": chain, "cadena": "Jumbo", "banco": banco, "oferta": oferta, "dias": "", "day_ids": list(days), "canal": canal}
    if percent is not None:
        item["percent"] = float(percent)
    if tope:
        item["tope"] = tope
    if tope_num is not None:
        item["tope_num"] = float(tope_num)
    if nota:
        item["nota"] = nota
    return item


ITEMS = [
    _it("Tarjeta Naranja X", "30%", [1], 30, "tope $12.000", 12000),
    _it("CencoPay Cuenta", "40%", [4, 5], 40, "tope $15.000", 15000, "Solo galletitas, cervezas y conservas; legal incluye domingo"),
    _it("Banco Patagonia", "30%", [5], 30, "tope $40.000", 40000, "Conflicto de día: la card figura sábado"),
    _it("Cuenta DNI", "10%", [0], 10, "sin tope", None, "Sin tope de reintegro"),
    _it("Banco Córdoba", "12 cuotas sin interés", [0, 1, 2, 3, 4, 5], nota="Solo rubro electro"),
    _it("Banco Comafi", "3 cuotas sin interés", [0, 1, 2, 3, 4, 5]),
]


def _ld(html: str) -> list[dict]:
    return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


class CondicionTest(unittest.TestCase):
    def test_nota_de_tope_no_es_condicion(self):
        self.assertFalse(_con_condicion({"nota": "Sin tope de reintegro"}))
        self.assertFalse(_con_condicion({"nota": "Sin tope informado"}))
        self.assertFalse(_con_condicion({}))
        self.assertTrue(_con_condicion({"nota": "Sin tope informado; excluye electro"}))
        self.assertTrue(_con_condicion({"nota": "Solo socios Club La Voz en Jumbo Nuevocentro y web"}))
        self.assertTrue(_con_condicion({"nota": "Conflicto de canal: el legal dice solo sucursales"}))


class ResumenSemanaTest(unittest.TestCase):
    def test_cuentas_y_mayores(self):
        r = resumen_semana_cadena("Jumbo", ITEMS)
        self.assertEqual((r["n"], r["bancos_n"], r["pct_n"], r["cuotas_n"]), (6, 6, 4, 2))
        texto = " ".join(r["lineas"])
        self.assertIn("hay 6 promos de 6 bancos y billeteras: 4 con porcentaje de descuento y 2 en cuotas sin interés", texto)
        # El mayor sin condiciones no es el 40% con nota: es el 30% de Naranja X.
        self.assertIn("sin condiciones extra en la nota es 30% con Tarjeta Naranja X (martes, tope $12.000)", r["mayor_general"])
        self.assertNotIn("Patagonia", r["mayor_general"])
        self.assertIn("40% con CencoPay Cuenta (viernes y sábado, tope $15.000)", r["mayor_condicion"])
        self.assertIn("«Solo galletitas, cervezas y conservas»", r["mayor_condicion"])
        self.assertIn("El tope más alto publicado es de $40.000: Banco Patagonia, 30%, sábado (ver la nota en la tabla).", texto)
        self.assertIn("Figuran sin tope: 10% con Cuenta DNI (lunes).", texto)
        self.assertIn("No hay promos cargadas para el domingo.", texto)
        self.assertEqual(r["cuotas_cond_n"], 1)
        self.assertEqual(r["cuotas_cond_ej"], "Solo rubro electro")

    def test_no_inventa_porcentajes(self):
        for c in promos_hoy.cadenas_indexables(MARTES):
            items = [it for it in promos_hoy._items_publicos(MARTES) if it["chain_id"] == c["chain_id"]]
            r = resumen_semana_cadena(c["nombre"], items)
            publicados = {promos_hoy._pct_txt(it["percent"]) for it in items if it.get("percent")}
            for linea in r["lineas"]:
                for pct in re.findall(r"\b\d+(?:,\d+)?%", linea):
                    self.assertIn(pct, publicados, (c["slug"], linea))
                for tope in re.findall(r"\$[\d.]+", linea):
                    self.assertTrue(any(tope in str(it.get("tope") or "") for it in items), (c["slug"], linea))

    def test_vacio(self):
        self.assertEqual(resumen_semana_cadena("Jumbo", []), {})


class MetaCadenaHoyTest(unittest.TestCase):
    def test_titulo_h1_y_meta(self):
        self.assertEqual(titulo_cadena_hoy("Jumbo"), "Promociones bancarias Jumbo hoy: bancos y topes | BaratoYa")
        self.assertEqual(titulo_cadena_hoy("Maxiconsumo"), "Promociones bancarias Maxiconsumo hoy | BaratoYa")
        for nombre in ("Día", "Jumbo", "Disco", "Vea", "Mas Online", "Makro", "Maxiconsumo"):
            self.assertLessEqual(len(titulo_cadena_hoy(nombre)), 60)
        self.assertEqual(h1_cadena_hoy("Día", "martes"), "Promociones bancarias Día hoy, martes")
        d = descripcion_cadena_hoy("Jumbo", "martes", 24, {"pct": "30%", "bancos": "Tarjeta Naranja X"})
        self.assertTrue(d.startswith("Promociones bancarias Jumbo hoy (martes) en CABA: hasta 30% con Tarjeta Naranja X."))
        self.assertLessEqual(len(d), 155)
        sin = descripcion_cadena_hoy("Jumbo", "martes", 24, None)
        self.assertNotIn("%", sin)
        self.assertLessEqual(len(sin), 155)
        # Sin promos hoy: la meta de siempre, sin %.
        self.assertNotIn("%", descripcion_cadena_hoy("Jumbo", "domingo", 0, None))

    def test_meta_usa_el_mayor_sin_condiciones(self):
        vie = date(2026, 10, 23)
        with mock.patch.object(promos_hoy, "_items_publicos", return_value=[dict(it) for it in ITEMS]):
            v = pagina_seo_cadena("jumbo", vie)
        # El viernes el único % es el 40% con condición: no va a la meta.
        self.assertNotIn("40%", v["description"])
        self.assertEqual(v["h1"], "Promociones bancarias Jumbo hoy, viernes")
        fila = next(f for f in v["resumen"]["mejor_por_dia"] if f["dia"] == "viernes")
        self.assertEqual(fila["condicion"], "con condiciones publicadas")
        sab = next(f for f in v["resumen"]["mejor_por_dia"] if f["dia"] == "sábado")
        self.assertNotIn("general_pct", sab)  # el 30% de Patagonia también tiene nota
        with mock.patch.object(promos_hoy, "_items_publicos", return_value=[dict(it) for it in ITEMS]):
            v = pagina_seo_cadena("jumbo", MARTES)
        self.assertIn("hasta 30% con Tarjeta Naranja X", v["description"])
        self.assertEqual(v["dia_href"], "/descuentos-supermercados/martes")
        self.assertEqual([it["banco"] for it in v["hoy_pct"]], ["Tarjeta Naranja X"])
        self.assertEqual({it["banco"] for it in v["hoy_cuotas"]}, {"Banco Córdoba", "Banco Comafi"})
        preguntas = [q["q"] for q in v["faq"]]
        for q in ("¿Cuál es el mayor descuento en Jumbo esta semana?", "¿Jumbo tiene cuotas sin interés?", "¿Qué promos de Jumbo no tienen tope?"):
            self.assertIn(q, preguntas)
        cuotas = next(q["a"] for q in v["faq"] if q["q"] == "¿Jumbo tiene cuotas sin interés?")
        self.assertIn("2 promos en cuotas sin interés, con Banco Comafi y Banco Córdoba", cuotas)
        self.assertIn("1 tiene condiciones publicadas (por ejemplo: «Solo rubro electro»)", cuotas)

    def test_coto_y_carrefour_conservan_title_h1(self):
        for slug, nombre in (("coto", "Coto"), ("carrefour", "Carrefour")):
            v = pagina_seo_cadena(slug, MARTES)
            self.assertEqual(v["title"], titulo_cadena(nombre))
            self.assertEqual(v["h1"], f"Promociones bancarias en {nombre} hoy")
            self.assertTrue(v["description"].startswith(f"Promociones bancarias del supermercado {nombre} hoy"))


class HtmlCadenaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app_mod.app)

    def test_jumbo_y_dia(self):
        for slug in ("jumbo", "dia"):
            r = self.client.get(f"{SEO_PATH}/{slug}")
            self.assertEqual(r.status_code, 200, slug)
            # CDN cache de PR #31/#32 sigue igual.
            self.assertRegex(r.headers.get("cache-control", ""), r"s-maxage=\d+")
            v = pagina_seo_cadena(slug)
            html = r.text
            nombre = v["nombre"]
            self.assertIn(f"<title>{v['title']}</title>", html)
            self.assertIn(f"<h1>{v['h1']}</h1>", html)
            self.assertIn(f"Promociones bancarias {nombre} hoy", v["title"])
            self.assertIn(f"Promociones bancarias {nombre} hoy", v["h1"])
            # Un día sin % publicado (p. ej. domingo en Jumbo) cae en la meta de respaldo.
            self.assertTrue(
                v["description"].startswith(f"Promociones bancarias {nombre} hoy (")
                or v["description"].startswith(f"Promociones bancarias del supermercado {nombre} hoy ("),
                v["description"],
            )
            self.assertIn(f'<h2 id="semana">Resumen de la semana en {nombre}</h2>', html)
            for linea in v["semana"]["lineas"]:
                self.assertIn(linea.replace("«", "«"), html)
            self.assertIn(f'<h2 id="hoy-cadenas">Hoy, {v["dia"]}: {nombre} y las otras cadenas</h2>', html)
            self.assertIn(f'href="{v["dia_href"]}"', html)
            seccion = html.split('id="hoy-cadenas"', 1)[1].split("</ul>", 1)[0]
            for c in v["hoy_cadenas"]:
                if c["propia"] and not c["n"]:
                    self.assertIn(f"<strong>{c['nombre']}</strong> (esta página): sin promos cargadas hoy", seccion)
                    self.assertNotIn(f'href="{c["href"]}"', seccion)
                elif c["propia"]:
                    self.assertIn(f"<strong>{c['nombre']}</strong> (esta página): {c['n']} promo", seccion)
                    self.assertNotIn(f'href="{c["href"]}"', seccion)
                else:
                    self.assertIn(f'href="{c["href"]}"', seccion)
            if v["hoy_pct"]:
                self.assertIn("<h3>Con porcentaje de descuento</h3>", html)
            if v["hoy_cuotas"]:
                self.assertIn("<h3>En cuotas sin interés</h3>", html)
            faq = next(b for b in _ld(html) if b["@type"] == "FAQPage")
            nombres = [q["name"] for q in faq["mainEntity"]]
            self.assertIn(f"¿Cuál es el mayor descuento en {nombre} esta semana?", nombres)
            self.assertIn(f"¿{nombre} tiene cuotas sin interés?", nombres)
            self.assertEqual(nombres, [q["q"] for q in v["faq"]])


if __name__ == "__main__":
    unittest.main()


class FechaDatosNoFuturaTest(unittest.TestCase):
    """20/10: promos que arrancan el 23/10 daban "Actualizado el 23 de octubre" y <lastmod> futuro."""

    def test_no_pasa_de_hoy(self):
        self.assertLessEqual(promos_hoy.fecha_datos_promos(MARTES), MARTES)
        self.assertEqual(promos_hoy.lastmod_promos(MARTES), MARTES.isoformat())
        filas = [{"valid_from": "2026-10-19"}, {"valid_from": "2026-10-23"}]
        with mock.patch.object(promos_hoy, "DATA") as data:
            ruta = data.__truediv__.return_value
            ruta.exists.return_value = True
            ruta.read_text.return_value = json.dumps(filas)
            self.assertEqual(promos_hoy.fecha_datos_promos(MARTES), date(2026, 10, 19))
            self.assertEqual(promos_hoy.fecha_datos_promos(date(2026, 10, 24)), date(2026, 10, 23))

    def test_sitemap_sin_lastmod_futuro(self):
        client = TestClient(app_mod.app)
        hoy = promos_hoy.hoy_art().isoformat()
        for lastmod in re.findall(r"<lastmod>([^<]+)</lastmod>", client.get("/sitemap.xml").text):
            self.assertLessEqual(lastmod[:10], hoy)
