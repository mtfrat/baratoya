"""Cuenta, cupo y Mercado Pago.

La búsqueda exige sesión. Una cuenta normal tiene 5 búsquedas.
El admin no tiene tope. Sin MERCADOPAGO_ACCESS_TOKEN no se llama a Mercado
Pago y no se simula un pago.
"""
from __future__ import annotations

import os
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx

FREE_LIMIT = 5
DEFAULT_PLAN_CENTS = 199_000
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
PAYMENT_ID_RE = re.compile(r"^\d{1,20}$")


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def supabase_url() -> str:
    return _env("SUPABASE_URL").rstrip("/")


def anon_key() -> str:
    return _env("SUPABASE_ANON_KEY")


def service_key() -> str:
    return _env("SUPABASE_SERVICE_ROLE_KEY")


def mp_token() -> str:
    return _env("MERCADOPAGO_ACCESS_TOKEN")


def cuentas_on() -> bool:
    return bool(supabase_url() and anon_key())


def cupo_on() -> bool:
    """Sin la service role el cupo no se puede contar. La búsqueda no sigue."""
    return bool(cuentas_on() and service_key())


def cobro_on() -> bool:
    return bool(mp_token())


def plan_cents() -> int:
    raw = _env("BARATOYA_PLAN_ARS_CENTS")
    if not raw:
        return DEFAULT_PLAN_CENTS
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_PLAN_CENTS
    if n <= 0 or n > 100_000_000:
        return DEFAULT_PLAN_CENTS
    return n


def plan_label() -> str:
    """$1.990 a partir de centavos. Solo se muestra si el cobro está activo."""
    cents = plan_cents()
    pesos = cents // 100
    frac = cents % 100
    entero = f"{pesos:,}".replace(",", ".")
    if frac:
        return f"${entero},{frac:02d}"
    return f"${entero}"


def public_base() -> str:
    return (_env("BARATOYA_PUBLIC_URL") or "https://baratoya.vercel.app").rstrip("/")


def pagina_publica() -> dict[str, Any]:
    """Lo que el HTML puede ver. La service role y el token de MP no entran."""
    activo = cobro_on()
    return {
        "supabase_url": supabase_url(),
        "supabase_anon_key": anon_key(),
        "cuentas_on": cuentas_on(),
        "cobro_on": activo,
        "free_limit": FREE_LIMIT,
        "plan_label": plan_label() if activo else "",
    }


def bearer(request_headers: Any) -> str:
    header = ""
    if request_headers is not None:
        header = request_headers.get("authorization") or request_headers.get("Authorization") or ""
    if not header.lower().startswith("bearer "):
        return ""
    return header.split(" ", 1)[1].strip()


def token_de(request_headers: Any, cookies: Any = None) -> str:
    """Bearer de la API, o la cookie que el navegador manda al abrir /admin."""
    tok = bearer(request_headers)
    if tok:
        return tok
    if cookies is None or not hasattr(cookies, "get"):
        return ""
    return str(cookies.get("baratoya_at") or "").strip()


def _service_headers() -> dict[str, str]:
    key = service_key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _user_headers(token: str) -> dict[str, str]:
    return {
        "apikey": anon_key(),
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


async def usuario(token: str) -> dict[str, str] | None:
    if not token or not cuentas_on():
        return None
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{supabase_url()}/auth/v1/user", headers=_user_headers(token))
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    uid = str(data.get("id") or "")
    if not UUID_RE.match(uid):
        return None
    email = str(data.get("email") or "")
    return {"id": uid, "email": email}


def _cuenta_vacia() -> dict[str, Any]:
    return {
        "plan": "free",
        "used": 0,
        "remaining": FREE_LIMIT,
        "limit": FREE_LIMIT,
        "role": "user",
        "admin": False,
    }


async def leer_cuenta(token: str, user_id: str) -> dict[str, Any]:
    if not UUID_RE.match(user_id):
        return _cuenta_vacia()
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{supabase_url()}/rest/v1/profiles",
            params={"id": f"eq.{user_id}", "select": "plan,searches_used,paid_at,role"},
            headers=_user_headers(token),
        )
    if r.status_code != 200:
        return _cuenta_vacia()
    try:
        rows = r.json()
    except Exception:
        return _cuenta_vacia()
    if not isinstance(rows, list) or not rows:
        return _cuenta_vacia()
    row = rows[0]
    plan = row.get("plan") if row.get("plan") in {"free", "paid"} else "free"
    try:
        used = int(row.get("searches_used") or 0)
    except (TypeError, ValueError):
        used = 0
    if used < 0:
        used = 0
    role = row.get("role") if row.get("role") in {"user", "admin"} else "user"
    if role == "admin" or plan == "paid":
        remaining = None
    else:
        remaining = max(0, FREE_LIMIT - used)
    return {
        "plan": plan,
        "used": used,
        "remaining": remaining,
        "limit": None if role == "admin" else FREE_LIMIT,
        "paid_at": row.get("paid_at"),
        "role": role,
        "admin": role == "admin",
    }


async def listar_busquedas(token: str, user_id: str) -> list[dict[str, str]]:
    if not UUID_RE.match(user_id):
        return []
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{supabase_url()}/rest/v1/searches",
            params={
                "user_id": f"eq.{user_id}",
                "select": "query,created_at",
                "order": "created_at.desc",
                "limit": "40",
            },
            headers=_user_headers(token),
        )
    if r.status_code != 200:
        return []
    try:
        rows = r.json()
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        q = " ".join(str(row.get("query") or "").split())
        if not q:
            continue
        out.append({"query": q, "created_at": str(row.get("created_at") or "")})
    return out


async def es_admin(token: str, user_id: str) -> bool:
    """La propia sesion lee su rol. No hace falta la service role para abrir /admin."""
    if not cuentas_on() or not token or not UUID_RE.match(user_id):
        return False
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{supabase_url()}/rest/v1/profiles",
            params={"id": f"eq.{user_id}", "select": "role"},
            headers=_user_headers(token),
        )
    if r.status_code != 200:
        return False
    try:
        rows = r.json()
    except Exception:
        return False
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return False
    return rows[0].get("role") == "admin"


async def resumen_admin() -> dict[str, Any]:
    """Conteos reales. ingresos_centavos queda en 0 hasta que exista Mercado Pago."""
    if not cupo_on():
        raise RuntimeError("sin service role")
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{supabase_url()}/rest/v1/rpc/admin_stats",
            headers=_service_headers(),
            json={},
        )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"admin_stats http {r.status_code}")
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError("admin_stats vacío")
    return data


async def consumir(user_id: str, query: str) -> dict[str, Any]:
    if not cupo_on():
        raise RuntimeError("sin service role")
    if not UUID_RE.match(user_id):
        return {"ok": False, "reason": "auth"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{supabase_url()}/rest/v1/rpc/consume_search",
            headers=_service_headers(),
            json={"p_user": user_id, "p_query": query},
        )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"consume_search http {r.status_code}")
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError("consume_search vacío")
    return data


async def marcar_pago(user_id: str, payment_id: str) -> dict[str, Any]:
    if not cupo_on():
        raise RuntimeError("sin service role")
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{supabase_url()}/rest/v1/rpc/mark_profile_paid",
            headers=_service_headers(),
            json={"p_user": user_id, "p_payment": payment_id},
        )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"mark_profile_paid http {r.status_code}")
    data = r.json()
    return data if isinstance(data, dict) else {"ok": False}


def _centavos(amount: Any) -> int | None:
    try:
        d = Decimal(str(amount))
    except Exception:
        return None
    if not d.is_finite():
        return None
    return int((d * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


async def crear_preferencia(user_id: str, email: str) -> dict[str, Any]:
    """Arma Checkout Pro. Si no hay token, no llama a Mercado Pago."""
    if not cobro_on():
        return {
            "ok": False,
            "status": 503,
            "error": "El cobro todavía no está activo.",
        }
    if not cupo_on():
        return {
            "ok": False,
            "status": 503,
            "error": "El servidor no puede marcar un pago: falta la clave de servicio.",
        }
    base = public_base()
    if not base.startswith("https://"):
        return {
            "ok": False,
            "status": 503,
            "error": "El aviso de pago necesita BARATOYA_PUBLIC_URL en https. No se abrió el cobro.",
        }
    cents = plan_cents()
    unit = float(Decimal(cents) / Decimal(100))
    vuelta = f"{base}/?mp=vuelta"
    body = {
        "items": [
            {
                "id": "busquedas-ilimitadas",
                "title": "BaratoYa — búsquedas ilimitadas",
                "description": "Plan de búsqueda ilimitada. No es una compra en el supermercado.",
                "quantity": 1,
                "currency_id": "ARS",
                "unit_price": unit,
            }
        ],
        "external_reference": user_id,
        "metadata": {"user_id": user_id},
        "notification_url": f"{base}/api/mercadopago/webhook",
        "back_urls": {"success": vuelta, "pending": vuelta, "failure": vuelta},
        "auto_return": "approved",
    }
    if email:
        body["payer"] = {"email": email}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            "https://api.mercadopago.com/checkout/preferences",
            headers={
                "Authorization": f"Bearer {mp_token()}",
                "Content-Type": "application/json",
            },
            json=body,
        )
    try:
        data = r.json()
    except Exception:
        data = {}
    if r.status_code not in (200, 201) or not isinstance(data, dict):
        return {
            "ok": False,
            "status": 502,
            "error": "Mercado Pago no armó la preferencia. No se marcó ningún pago.",
        }
    token = mp_token()
    init = data.get("sandbox_init_point") if token.startswith("TEST-") else data.get("init_point")
    if not init:
        init = data.get("init_point") or data.get("sandbox_init_point")
    if not init:
        return {
            "ok": False,
            "status": 502,
            "error": "Mercado Pago no devolvió un link de pago. No se marcó ningún pago.",
        }
    return {"ok": True, "status": 200, "init_point": str(init)}


def _payment_id(query: dict[str, Any], body: dict[str, Any]) -> str:
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict) and data.get("id") is not None:
            tipo = str(body.get("type") or body.get("topic") or "payment")
            if tipo == "payment":
                return str(data.get("id"))
        if str(body.get("type") or body.get("topic") or "") == "payment" and body.get("id") is not None:
            return str(body.get("id"))
    topic = str(query.get("topic") or query.get("type") or "")
    if topic == "payment" and query.get("id") is not None:
        return str(query.get("id"))
    data_id = query.get("data.id")
    if str(query.get("type") or "") == "payment" and data_id is not None:
        return str(data_id)
    return ""


async def procesar_aviso(query: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """Confirma el pago contra la API de Mercado Pago. La vuelta del browser no paga."""
    if not cobro_on():
        return {"status": 503, "body": {"ok": False, "error": "El cobro todavía no está activo."}}
    if not cupo_on():
        return {"status": 503, "body": {"ok": False, "error": "Falta la clave de servicio para marcar el pago."}}
    pid = _payment_id(query or {}, body or {})
    if not pid:
        return {"status": 200, "body": {"ok": True, "ignored": True}}
    if not PAYMENT_ID_RE.match(pid):
        return {"status": 200, "body": {"ok": True, "ignored": True}}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(
            f"https://api.mercadopago.com/v1/payments/{pid}",
            headers={"Authorization": f"Bearer {mp_token()}"},
        )
    if r.status_code == 404:
        return {"status": 200, "body": {"ok": True, "ignored": True}}
    if r.status_code != 200:
        return {"status": 502, "body": {"ok": False, "error": "No se pudo leer el pago en Mercado Pago."}}
    try:
        pago = r.json()
    except Exception:
        return {"status": 502, "body": {"ok": False, "error": "Mercado Pago no devolvió el pago."}}
    if not isinstance(pago, dict):
        return {"status": 502, "body": {"ok": False, "error": "Mercado Pago no devolvió el pago."}}
    if str(pago.get("status") or "") != "approved":
        return {"status": 200, "body": {"ok": True, "ignored": True, "status_pago": pago.get("status")}}
    if str(pago.get("currency_id") or "") != "ARS":
        return {"status": 200, "body": {"ok": True, "ignored": True, "reason": "moneda"}}
    uid = str(pago.get("external_reference") or "")
    if not UUID_RE.match(uid):
        return {"status": 200, "body": {"ok": True, "ignored": True, "reason": "sin cuenta"}}
    cents = _centavos(pago.get("transaction_amount"))
    if cents != plan_cents():
        return {"status": 200, "body": {"ok": True, "ignored": True, "reason": "monto"}}
    marked = await marcar_pago(uid, pid)
    if not marked.get("ok"):
        return {"status": 502, "body": {"ok": False, "error": "El pago está aprobado y no se pudo anotar en la cuenta."}}
    return {"status": 200, "body": {"ok": True, "plan": "paid"}}
