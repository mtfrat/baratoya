"""Coto Digital: endpoint REST público getPromocionesMulticanal (online y sucursales físicas)."""
from __future__ import annotations

import json
import re

from .common import NOVIG, Ctx, clean

ICON0 = {"comunidad": "Comunidad Coto", "tci": "Tarjeta Coto TCI", "naranjax": "Naranja X", "icbc": "ICBC", "ciudad": "Banco Ciudad", "supervielle": "Supervielle",
         "credicoop": "Credicoop", "comafi_unico": "Comafi Único", "comafi": "Comafi", "patagonia": "Banco Patagonia", "columbia": "Banco Columbia",
         "amex": "American Express", "galicia": "Galicia", "nacion": "Banco Nación", "bbva": "BBVA", "macro": "Macro", "mercadopago": "Mercado Pago",
         "modo": "MODO", "jubiladosypensionados": "Jubilados y pensionados", "beneficios_anses": "ANSES", "ciudadania_portena": "Ciudadanía Porteña"}
ICON = dict(ICON0, **{"visa": "Visa débito (NFC)", "tarjetascredito": "Tarjetas de crédito"})


def _bank(ic: str) -> str:
    for k, v in ICON.items():
        if k in ic:
            return v
    return ic


def build(ctx: Ctx) -> None:
    cd = json.loads((ctx.raw / "coto_promos.json").read_text(encoding="utf-8"))["result"]
    n = 0
    for key, ch, tag in (("promocionesDigitales", "online", "D"), ("promocionesSucursalesFisicas", "store", "S")):
        for i, x in enumerate(cd[key]):
            txt = x["textoDescuento"]
            obs = clean(x["observacion"])
            desc = clean(x["descripcion"])
            days = [7 if d["id"] == 1 else d["id"] - 1 for d in x["dias"]]
            if not days:
                ctx.log(f"coto: se omite «{txt}» {x['icono']} (sin días publicados)")
                continue
            m = re.match(r"(\d+) ?(%|OFF)", txt)
            mc = re.match(r"(\d+) CUOTAS", txt)
            if not (m or mc):
                ctx.pendiente("cotodigital", f"coto:{key}:{i}", "textoDescuento con formato nuevo", txt)
                continue
            kind, val = ("percent", int(m.group(1))) if m else ("installments", int(mc.group(1)))
            mv = re.search(r"Del (\d\d)/(\d\d) al (\d\d)/(\d\d)/(\d{4})", obs)
            if mv:
                vf = f"{mv.group(5)}-{mv.group(2)}-{mv.group(1)}"
                vt = f"{mv.group(5)}-{mv.group(4)}-{mv.group(3)}"
                vn = ""
            else:
                vf, vt, vn = ctx.W0, ctx.W1, NOVIG
            cap = None
            mt = re.search(r"(?i)tope[^$]{0,40}\$ ?([\d\.]+)", obs)
            if mt:
                cap = int(mt.group(1).replace(".", ""))
            mn = None
            mm = re.search(r"a partir de \$([\d\.]+)", obs)
            if mm:
                mn = int(mm.group(1).replace(".", ""))
            dna = []
            if kind == "percent":
                if re.search(r"(?i)exclu|sin oferta", obs):
                    dna.append("Aplican exclusiones (ver legales)")
                if cap is None:
                    dna.append("Sin tope o tope no informado")
                if re.search(r"(?i)jubilados|comunidad|ciudadan|anses|plan sueldo|sgto|segmento|plan [ée]pico|plan turbo|plan inicial", obs + " " + desc + " " + x["icono"]):
                    dna.append("Solo para un segmento de clientes")
            elif re.search(r"(?i)seleccionad|electro", obs):
                dna.append("Solo productos seleccionados")
            if ctx.add("cotodigital", _bank(x["icono"]), kind, val, days, ch, cap, mn, vf, vt, " | ".join(filter(None, [txt, desc, obs, vn])),
                       "https://www.coto.com.ar/descuentos", "; ".join(dna) or None, f"{tag}{i}"):
                n += 1
    ctx.log(f"cotodigital: {n} filas")
