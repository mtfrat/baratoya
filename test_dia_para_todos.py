"""Páginas por día (28/10): descuentos sin requisitos especiales, tope y hasta cuánto comprar.

GSC 27/10: "jueves descuentos en supermercados" 0/2 @8,5; /descuentos-supermercados/jueves
0/38 @7,1 (domingo 0/56 @5,9, lunes 0/47 @7,6). El resumen mostraba el mayor % de cada
cadena aunque fuera solo para jubilados, una provincia o productos seleccionados, y no
decía hasta qué compra rinde el tope. Todo sale de las tarjetas publicadas. Sin red.
"""
from __future__ import annotations

import json
import os
import re
import unittest

os.environ["BARATOYA_PRECIOS_OFFLINE"] = "1"

from fastapi.testclient import TestClient

import app as app_mod
import promos_hoy as ph


def _it(chain, banco, percent=None, tope=None, tope_num=None, nota=None, minimo=None, canal="sucursal", days=(3,)):
    it = {"chain_id": chain, "cadena": chain.title(), "banco": banco,
          "oferta": f"{percent}%" if percent else "3 cuotas sin interés", "dias": "jueves",
          "day_ids": list(days), "canal": canal}
    if percent is not None:
        it["percent"] = float(percent)
    if tope:
        it["tope"] = tope
    if tope_num is not None:
        it["tope_num"] = float(tope_num)
    if nota:
        it["nota"] = nota
    if minimo:
        it["minimo"] = minimo
    return it


class AptaParaTodosTest(unittest.TestCase):
    def test_segmentos_y_productos_quedan_afuera(self):
        no = [
            _it("dia", "Banco de Corrientes (MásBanCo MODO)", 30, "tope $20.000", 20000, "Solo sucursales de Corrientes / clientes Banco de Corrientes"),
            _it("carrefour", "Banco Nacion", 5, "tope $5.000", 5000, "Solo jubilados BNA; Excluye rubros/productos (ver legales)"),
            _it("jumbo", "CencoPay", 25, nota="Solo productos seleccionados de galletitas; sin tope informado"),
            _it("masonline", "Credicuotas", 20, "tope $6.000", 6000, "Conflicto de tope entre card y legal; solo primera compra"),
            _it("masonline", "ANSES", 10, "tope $12.000", 12000, "Excluye rubros/productos (ver legales)"),
            _it("masonline", "MasClub (MasGO)", 20, "sin tope", nota="Excluye rubros/productos (ver legales)"),
            _it("coto", "ICBC", 20, nota="Aplican exclusiones (ver legales)"),  # sin tope publicado
            _it("coto", "Banco Ciudad", 15, "sin tope", nota="Aplican exclusiones (ver legales); Solo para un segmento de clientes"),
            _it("dia", "Naranja X"),  # cuotas
        ]
        for it in no:
            self.assertFalse(ph._apta_para_todos(it), it["banco"])

    def test_datos_faltantes_y_rubros_no_restringen(self):
        si = [
            _it("masonline", "Buepp Banco Ciudad", 35, "tope $20.000", 20000),
            _it("dia", "Personal Pay", 15, "sin tope", nota="Sin tope de reintegro", minimo="$20.000"),
            _it("carrefour", "Cuenta Digital", 20, "tope $10.000", 10000, "Excluye rubros/productos (ver legales)"),
            _it("coto", "Banco Columbia", 30, "sin tope", nota="Aplican exclusiones (ver legales); Sin tope o tope no informado"),
            _it("makro", "Cencopay", 25, "tope $20.000", 20000, "Exclusiones o restricciones (ver legales)"),
        ]
        for it in si:
            self.assertTrue(ph._apta_para_todos(it), it["banco"])


class ParaTodosDiaTest(unittest.TestCase):
    def setUp(self):
        self.items = [
            _it("masonline", "Buepp Banco Ciudad", 35, "tope $20.000", 20000),
            _it("masonline", "Banco Credicoop MODO", 30, "tope $9.000", 9000),
            _it("dia", "Banco de Corrientes (MásBanCo MODO)", 30, "tope $20.000", 20000, "Solo sucursales de Corrientes / clientes Banco de Corrientes"),
            _it("dia", "Personal Pay", 15, "sin tope", nota="Sin tope de reintegro", minimo="$20.000", canal="online y sucursal"),
            _it("coto", "Banco Columbia", 30, "sin tope", nota="Aplican exclusiones (ver legales); Sin tope o tope no informado", canal="online"),
            _it("coto", "Visa débito (NFC)", 30, "sin tope", nota="Aplican exclusiones (ver legales); Sin tope o tope no informado"),
            _it("jumbo", "MODO", 20, "tope $25.000", 25000, minimo="$100.000", canal="online y sucursal"),
            _it("disco", "CencoPay", 25, nota="Solo productos seleccionados; sin tope informado"),
        ]
        self.filas = ph.para_todos_dia(self.items, {"masonline": "/promos-bancarias-supermercados/mas-online"})

    def test_una_fila_por_cadena_ordenada(self):
        self.assertEqual([f["chain_id"] for f in self.filas], ["masonline", "coto", "jumbo", "dia"])
        self.assertNotIn("disco", {f["chain_id"] for f in self.filas})

    def test_compra_hasta_el_tope(self):
        mo = self.filas[0]
        self.assertEqual(mo["pct_txt"], "35")
        self.assertEqual(mo["bancos_txt"], "Buepp Banco Ciudad")
        self.assertEqual(mo["tope_txt"], "$20.000")
        self.assertEqual(mo["compra_txt"], "$57.143")  # 20.000 / 0,35
        self.assertEqual(mo["href"], "/promos-bancarias-supermercados/mas-online")
        jumbo = self.filas[2]
        self.assertEqual(jumbo["compra_txt"], "$125.000")
        self.assertEqual(jumbo["minimo"], "$100.000")

    def test_empate_lista_bancos_y_sin_tope(self):
        coto = self.filas[1]
        self.assertEqual(coto["bancos_txt"], "Banco Columbia o Visa débito (NFC)")
        self.assertEqual(coto["tope_txt"], "sin tope informado")
        self.assertEqual(coto["compra_txt"], "")
        self.assertTrue(coto["excluye"])
        self.assertEqual(coto["canal"], "online y sucursal")
        dia = self.filas[3]
        self.assertEqual(dia["tope_txt"], "sin tope")
        self.assertFalse(dia["excluye"])

    def test_faq(self):
        faq = ph._faq_dia_para_todos(self.filas, "jueves")
        self.assertEqual(len(faq), 2)
        self.assertEqual(faq[0]["q"], "¿Qué descuentos de supermercado de los jueves puede usar cualquiera?")
        self.assertIn("Masonline 35% con Buepp Banco Ciudad", faq[0]["a"])
        self.assertNotIn("Corrientes", faq[0]["a"])
        self.assertEqual(faq[1]["q"], "¿Cuánto conviene gastar los jueves para aprovechar el tope del descuento?")
        self.assertIn("hasta una compra de $57.143", faq[1]["a"])
        self.assertIn("rinde hasta $125.000 y pide un mínimo de $100.000", faq[1]["a"])

    def test_minimo_mayor_que_la_compra(self):
        filas = ph.para_todos_dia([_it("jumbo", "MODO", 20, "tope $10.000", 10000, minimo="$80.000")])
        faq = ph._faq_dia_para_todos(filas, "jueves")
        self.assertIn("con el mínimo ya llegás al tope", faq[1]["a"])

    def test_sin_filas_sin_faq(self):
        self.assertEqual(ph._faq_dia_para_todos([], "jueves"), [])


class PaginaDiaRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app_mod.app)

    def test_siete_dias_renderizan(self):
        for slug in ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"):
            r = self.client.get(f"/descuentos-supermercados/{slug}")
            self.assertEqual(r.status_code, 200, slug)
            html = r.text
            self.assertEqual(len(re.findall(r"<h1[\s>]", html)), 1)
            vista = ph.pagina_seo_dia(slug)
            blocks = [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]
            faq = next(b for b in blocks if b.get("@type") == "FAQPage")
            self.assertEqual(len(faq["mainEntity"]), len(vista["faq"]))
            if vista["para_todos"]:
                self.assertIn('id="para-todos"', html)
                self.assertLess(html.index('id="resumen"'), html.index('id="para-todos"'))
                for f in vista["para_todos"]:
                    if f["compra_txt"]:
                        self.assertIn(f["compra_txt"], html)
                names = [q["name"] for q in faq["mainEntity"]]
                self.assertIn(f"¿Qué descuentos de supermercado de los {vista['plural']} puede usar cualquiera?", names)
            else:
                self.assertNotIn('id="para-todos"', html)

    def test_title_y_meta_sin_cambios(self):
        vista = ph.pagina_seo_dia("jueves")
        self.assertTrue(vista["title"].startswith("Descuentos en supermercados los jueves"))
        self.assertLessEqual(len(vista["description"]), 160)


if __name__ == "__main__":
    unittest.main()
