from promos_hoy import descripcion_cadena_hoy


def test_meta_con_pct_condicionado():
    d = descripcion_cadena_hoy("Disco", "miércoles", 3, None, None, 2, "15%")
    assert d.startswith("Promociones bancarias Disco hoy (miércoles) en CABA: hasta 15% con condiciones")
    assert len(d) <= 155


def test_sin_condicion_no_cambia():
    a = descripcion_cadena_hoy("Vea", "miércoles", 1, {"pct": "15%", "bancos": "Galicia"}, None, 2)
    b = descripcion_cadena_hoy("Vea", "miércoles", 1, {"pct": "15%", "bancos": "Galicia"}, None, 2, "20%")
    assert a == b and "con condiciones" not in a
