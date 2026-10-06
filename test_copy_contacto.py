"""Copy de home/planes: trial 7 días visible, sin promesas de ahorro, contacto unificado."""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

import app as app_mod

IG = "https://www.instagram.com/baratoya.ba/"
MAIL = "baratoyaba@gmail.com"


class CopyContactoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.c = TestClient(app_mod.app)

    def test_home_card_free_menciona_trial_7_dias(self) -> None:
        html = self.c.get("/").text
        self.assertIn("<strong>7 días Plus gratis</strong>, sin tarjeta", html)

    def test_home_sin_promesas_de_ahorro(self) -> None:
        html = self.c.get("/").text.lower()
        self.assertNotIn("nunca pagues de más", html)
        self.assertNotIn("descuento exacto", html)

    def test_contacto_unico_y_instagram(self) -> None:
        for path in ("/", "/planes", "/privacidad", "/terminos", "/no-existe-xyz"):
            html = self.c.get(path, headers={"accept": "text/html"}).text
            self.assertNotIn("punatechba@", html, path)
            self.assertIn(IG, html, path)
            self.assertIn("@baratoya.ba", html, path)
            self.assertIn(MAIL, html, path)


if __name__ == "__main__":
    unittest.main()
