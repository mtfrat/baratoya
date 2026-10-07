"""Correcciones antes de tráfico de comunidad: solo CABA, copy honesto, promos que no se acumulan."""
from __future__ import annotations

import asyncio
import re
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import promos_hoy
import super_cadenas
from promos_hoy import FUERA_DE_CABA, _base, _no_acumula, aplicar_oferta, puede_restar

ROOT = Path(__file__).resolve().parent
NO_CABA_RE = re.compile(r"cordiez|toledo|an[oó]nima|super\s*mami|comod[ií]n", re.IGNORECASE)
MARTES = date(2026, 10, 6)


def _rec(**kw):
    base = dict(
        chain_id="dia",
        cadena="Día",
        banco="Banco X",
        percent=20.0,
        days={MARTES.weekday()},
        canal="online y sucursal",
        cap=50000.0,
    )
    base.update(kw)
    return _base(**base)


class SoloCabaTest(unittest.TestCase):
    def test_cadenas_fuera_de_caba(self) -> None:
        self.assertEqual(FUERA_DE_CABA, {"cordiez", "toledo", "laanonima", "supermami", "comodin"})

    def test_stores_no_consulta_fuera_de_caba(self) -> None:
        ids = {s["id"] for s in super_cadenas.STORES}
        self.assertFalse(ids & FUERA_DE_CABA, ids)
        self.assertIn("jumbo", ids)
        self.assertIn("josimar", ids)

    def test_buscar_super_no_llama_la_anonima_ni_super_mami(self) -> None:
        llamadas: list[str] = []

        async def fake_one(client, store, q):
            llamadas.append(store["id"])
            return {"tienda": store["nombre"], "tienda_id": store["id"], "http": 200, "ok": False, "productos": []}

        def fake_extra(tid):
            async def _f(client, q):
                llamadas.append(tid)
                return {"tienda": tid, "tienda_id": tid, "http": 200, "ok": False, "productos": []}
            return _f

        with patch.object(super_cadenas, "_one", fake_one), \
             patch.object(super_cadenas, "_fetch_la_anonima", fake_extra("laanonima")), \
             patch.object(super_cadenas, "_fetch_super_mami", fake_extra("supermami")), \
             patch.object(super_cadenas, "_fetch_coto", fake_extra("cotodigital")):
            res = asyncio.run(super_cadenas.buscar_super("yerba"))
        self.assertFalse(set(llamadas) & FUERA_DE_CABA, llamadas)
        self.assertIn("cotodigital", llamadas)
        self.assertFalse({f["tienda_id"] for f in res["fuentes"]} & FUERA_DE_CABA)

    def test_promos_sin_cadenas_fuera_de_caba(self) -> None:
        chains = {r["chain_id"] for r in promos_hoy.cargar(forzar=True)}
        self.assertFalse(chains & FUERA_DE_CABA, chains)
        cat = promos_hoy.catalogo(MARTES)
        for dia in cat["por_dia"]:
            for card in dia["items"]:
                self.assertNotIn(card["chain_id"], FUERA_DE_CABA)
        self.assertIsNone(NO_CABA_RE.search(" ".join(cat["notas"])))
        self.assertIsNone(NO_CABA_RE.search(str(promos_hoy.notas_cadenas_sin_promo())))

    def test_templates_no_nombran_cadenas_fuera_de_caba(self) -> None:
        for tpl in (ROOT / "templates").glob("*.html"):
            m = NO_CABA_RE.search(tpl.read_text(encoding="utf-8"))
            self.assertIsNone(m, f"{tpl.name}: {m.group(0) if m else ''}")


class CopyHonestoTest(unittest.TestCase):
    def test_sin_precio_real_en_templates(self) -> None:
        for tpl in (ROOT / "templates").glob("*.html"):
            self.assertNotIn("precio real", tpl.read_text(encoding="utf-8").casefold(), tpl.name)

    def test_home_dice_estimado(self) -> None:
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn("precio final estimado con promos", html)
        self.assertIn("calculados y estimados", html)


class PromosNoAcumulablesTest(unittest.TestCase):
    def test_detecta_variantes_de_no_acumulable(self) -> None:
        for legal in (
            "No acumulable con otras promociones.",
            "Pago con Mercado Pago - no acumulabe con otras ofertas",
            "Los precios de ofertas publicados no son acumulables con otras promociones vigentes.",
            "Los beneficios no se superponen ni son acumulativos entre sí.",
            "Dicha promoción no es acumulable con otras promociones vigentes.",
            "Esta promo no se acumula con otras.",
            "No acumulable ni combinable con otras promociones.",
        ):
            self.assertTrue(_no_acumula(_rec(legal=legal)), legal)

    def test_acumulable_si_suma(self) -> None:
        for legal in (
            "Este beneficio es acumulable con otras promociones que apliquen pagando con MODO.",
            "Acumulable con todas las promociones vigentes.",
            "Las compras efectuadas por cualquier modalidad acumularán para el mismo límite máximo.",
        ):
            self.assertFalse(_no_acumula(_rec(legal=legal)), legal)

    def test_no_acumulable_no_se_resta_aunque_sea_la_mejor(self) -> None:
        ok, motivo, total = puede_restar(_rec(legal="No acumulable con otras promociones."), "Yerba 1kg", 10000.0, MARTES, ya_descuento=True)
        self.assertFalse(ok)
        self.assertEqual(total, 10000.0)
        self.assertIn("no acumula", motivo)
        ok, _m, total = puede_restar(_rec(legal="no acumulabe con otras ofertas"), "Yerba 1kg", 10000.0, MARTES)
        self.assertFalse(ok)
        self.assertEqual(total, 10000.0)

    def test_aplicar_oferta_resta_una_sola_promo_nunca_suma_dos(self) -> None:
        recs = [
            _rec(banco="Banco A", percent=20.0, legal="Acumulable con otras promociones."),
            _rec(banco="Banco B", percent=15.0, legal="Acumulable con otras promociones."),
            _rec(banco="Banco C", percent=40.0, legal="No acumulable con otras promociones."),
        ]
        with patch.object(promos_hoy, "cargar", lambda forzar=False: recs):
            res = aplicar_oferta("dia", "Yerba 1kg", 10000.0, MARTES, ya_descuento=True)
        # 40% no acumulable queda afuera; de las otras se resta solo la mejor (20%), no 20%+15%.
        self.assertEqual(res["total"], 8000.0)
        self.assertEqual(len(res["promos"]), 1)
        self.assertEqual(res["promo"]["descuento"], "20%")

    def test_precio_con_descuento_de_tienda_y_promo_no_acumulable(self) -> None:
        recs = [_rec(banco="Banco C", percent=25.0, legal="No acumulable con otras promociones y/o descuentos.")]
        with patch.object(promos_hoy, "cargar", lambda forzar=False: recs):
            res = aplicar_oferta("dia", "Yerba 1kg", 3969.0, MARTES, ya_descuento=True)
        self.assertEqual(res["total"], 3969.0)
        self.assertIsNone(res["promo"])


if __name__ == "__main__":
    unittest.main()
