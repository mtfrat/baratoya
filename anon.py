"""Búsqueda sin cuenta: tope por IP (+ cookie firmada) y registro para métricas.

- La IP sale de x-real-ip / x-forwarded-for (Vercel las pisa con la IP real del
  cliente) y nunca se guarda en claro: se guarda HMAC-SHA256 truncado.
- El conteo vive en Supabase (public.anon_search_events, RPC anon_search_hit,
  solo service_role) porque en Vercel cada instancia tiene su memoria.
- Si la tabla/RPC todavía no existe (migración sin aplicar) o Supabase falla,
  cae a un tope en memoria por instancia: más blando, pero la búsqueda anda.
- Nada de esto toca el cupo de cuentas (consume_search / trial / Plus).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import threading
import time
import uuid
from collections import deque
from typing import Any

import httpx

try:
    from baratoya import cuentas
except ImportError:  # pragma: no cover - layout plano (tests / Vercel root)
    import cuentas

COOKIE = "by_anon"
COOKIE_MAX_AGE = 365 * 24 * 3600
_ANON_RE = re.compile(r"^[0-9a-f]{32}$")


def _int_env(name: str, default: int) -> int:
    try:
        v = int((os.getenv(name) or "").strip())
        return v if v > 0 else default
    except ValueError:
        return default


def hour_limit() -> int:
    return _int_env("ANON_SEARCH_HOUR_LIMIT", 10)


def day_limit() -> int:
    return _int_env("ANON_SEARCH_DAY_LIMIT", 30)


def _secret() -> bytes:
    s = (os.getenv("ANON_SEARCH_SECRET") or "").strip() or cuentas.service_key() or "baratoya-anon-dev"
    return hashlib.sha256(("anon-search:" + s).encode()).digest()


def client_ip(headers: Any, client_host: str | None = None) -> str:
    real = (headers.get("x-real-ip") or "").strip()
    if real:
        return real
    fwd = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if fwd:
        return fwd
    return (client_host or "").strip() or "unknown"


def ip_hash(ip: str) -> str:
    return hmac.new(_secret(), ("ip:" + ip).encode(), hashlib.sha256).hexdigest()[:32]


def _firma(anon_id: str) -> str:
    return hmac.new(_secret(), ("cookie:" + anon_id).encode(), hashlib.sha256).hexdigest()[:24]


def nueva_cookie() -> tuple[str, str]:
    anon_id = uuid.uuid4().hex
    return anon_id, f"{anon_id}.{_firma(anon_id)}"


def leer_cookie(raw: str | None) -> str | None:
    """Devuelve el anon_id si la firma coincide; si no, None (se emite una nueva)."""
    if not raw or "." not in raw:
        return None
    anon_id, _, sig = raw.partition(".")
    if not _ANON_RE.match(anon_id):
        return None
    if not hmac.compare_digest(sig, _firma(anon_id)):
        return None
    return anon_id


# ---- Fallback en memoria (por instancia) ----
_mem_lock = threading.Lock()
_mem: dict[str, deque[float]] = {}


def _mem_hit(keys: list[str], q: str, ahora: float | None = None) -> dict[str, Any]:
    now = ahora if ahora is not None else time.time()
    h_lim, d_lim = hour_limit(), day_limit()
    with _mem_lock:
        used_h = used_d = 0
        for k in keys:
            dq = _mem.setdefault(k, deque())
            while dq and dq[0] <= now - 86400:
                dq.popleft()
            used_d = max(used_d, len(dq))
            used_h = max(used_h, sum(1 for t in dq if t > now - 3600))
        base = {"hour": used_h, "day": used_d, "hour_limit": h_lim, "day_limit": d_lim, "storage": "memory"}
        if used_d >= d_lim:
            return {"ok": False, "reason": "rate_day", **base}
        if used_h >= h_lim:
            return {"ok": False, "reason": "rate_hour", **base}
        for k in keys:
            _mem[k].append(now)
        if len(_mem) > 20000:  # tope de memoria: se descarta lo más viejo
            for k in list(_mem)[:5000]:
                _mem.pop(k, None)
        base.update(hour=used_h + 1, day=used_d + 1)
        return {"ok": True, **base}


def _mem_reset() -> None:
    with _mem_lock:
        _mem.clear()


async def _rpc_hit(iph: str, anon_id: str | None, q: str) -> dict[str, Any] | None:
    """RPC atómica en Supabase. None = no disponible (migración sin aplicar o error)."""
    if not cuentas.cupo_on():
        return None
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(
                f"{cuentas.supabase_url()}/rest/v1/rpc/anon_search_hit",
                headers=cuentas._service_headers(),
                json={
                    "p_ip_hash": iph,
                    "p_anon_id": anon_id,
                    "p_query": q[:80],
                    "p_hour_limit": hour_limit(),
                    "p_day_limit": day_limit(),
                },
            )
    except Exception as exc:
        print(f"anon_search_hit error: {type(exc).__name__}")
        return None
    status = int(getattr(r, "status_code", 0) or 0)
    if status not in (200, 201):
        body = (getattr(r, "text", None) or "")[:200]
        print(f"anon_search_hit HTTP {status} body={body!r}")
        return None
    try:
        data = r.json()
    except Exception:
        return None
    if not isinstance(data, dict) or "ok" not in data:
        return None
    data["storage"] = "supabase"
    return data


async def registrar(headers: Any, cookies: Any, client_host: str | None, q: str) -> dict[str, Any]:
    """Cuenta y registra una búsqueda anónima. Devuelve ok/reason + cookie a emitir."""
    iph = ip_hash(client_ip(headers, client_host))
    anon_id = leer_cookie((cookies or {}).get(COOKIE))
    set_cookie = None
    if not anon_id:
        anon_id, set_cookie = nueva_cookie()
    res = await _rpc_hit(iph, anon_id, q)
    if res is None:
        res = _mem_hit(["ip:" + iph, "an:" + anon_id], q)
    res["anon_id"] = anon_id
    res["set_cookie"] = set_cookie
    return res
