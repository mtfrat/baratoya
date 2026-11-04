"""Alarmas: una cadena vacía o con caída fuerte respecto de la semana anterior hace FALLAR el script."""
from __future__ import annotations

from datetime import date, timedelta

from .common import CADENAS

CAIDA_MAX = 0.40  # más de 40% menos "filas-día" que la semana anterior => alarma
MIN_CENCO_POR_DIA = 10


def filas_dia(rows: list[dict], chain: str, w0: date) -> int:
    """Cantidad de pares (fila, día) activos en la semana lunes..domingo que empieza en w0."""
    n = 0
    for i in range(7):
        d = w0 + timedelta(days=i)
        iso = d.isoformat()
        n += sum(1 for r in rows if r["chain"] == chain and r["valid_from"] <= iso <= r["valid_to"] and d.isoweekday() in r["days"])
    return n


def semana_de(rows: list[dict], tope: date | None = None) -> date | None:
    """Lunes de la semana (<= tope) con más filas-día en el archivo: la semana que describe esa carga."""
    cand = set()
    for r in rows:
        for k in ("valid_from", "valid_to"):
            d = date.fromisoformat(r[k])
            cand.add(d - timedelta(days=d.weekday()))
    cand = {c for c in cand if tope is None or c <= tope}
    if not cand:
        return None
    return max((sum(filas_dia(rows, ch, c) for ch in CADENAS), c) for c in cand)[1]


def alarmas(rows: list[dict], previas: list[dict], w0: date, w_prev: date | None = None) -> tuple[list[str], list[str]]:
    """Devuelve (alarmas, tabla de resumen)."""
    al: list[str] = []
    tabla: list[str] = []
    w_prev = w_prev or semana_de(previas, w0 - timedelta(days=1)) or (w0 - timedelta(days=7))
    for ch in CADENAS:
        n = filas_dia(rows, ch, w0)
        p = filas_dia(previas, ch, w_prev) if previas else 0
        tabla.append(f"{ch:12s} filas={sum(1 for r in rows if r['chain'] == ch):3d}  filas-día={n:4d}  semana anterior ({w_prev})={p:4d}")
        if n == 0:
            al.append(f"{ch}: VACÍA (0 filas activas en la semana {w0})")
        elif p and n < p * (1 - CAIDA_MAX):
            al.append(f"{ch}: cae {round(100 * (1 - n / p))}% ({p} -> {n} filas-día) respecto de la semana anterior")
    for ch in ("jumbo", "disco", "vea"):
        for i in range(6):  # lunes a sábado
            d = w0 + timedelta(days=i)
            n = sum(1 for r in rows if r["chain"] == ch and r["valid_from"] <= d.isoformat() <= r["valid_to"] and d.isoweekday() in r["days"])
            if n < MIN_CENCO_POR_DIA:
                al.append(f"{ch}: sólo {n} promos el {d} (mínimo esperado {MIN_CENCO_POR_DIA})")
    return al, tabla
