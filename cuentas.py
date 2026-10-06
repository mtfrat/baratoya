"""Cuenta, cupo y Mercado Pago.

La búsqueda exige sesión. Una cuenta normal tiene 5 búsquedas.
El admin no tiene tope. Sin MERCADOPAGO_ACCESS_TOKEN no se llama a Mercado
Pago y no se simula un pago.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx

_ART = timezone(timedelta(hours=-3))
_MESES = "ene feb mar abr may jun jul ago sep oct nov dic".split()


def ahora_art_texto() -> str:
    dt = datetime.now(_ART)
    return f"{dt.day} {_MESES[dt.month - 1]} {dt.year}, {dt:%H:%M} ART"


def formatear_art(iso_str: str | None) -> str:
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        dt_art = dt.astimezone(_ART)
        return f"{dt_art.day} {_MESES[dt_art.month - 1]} {dt_art.year}, {dt_art:%H:%M} ART"
    except Exception:
        return str(iso_str)[:19]


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
        "trial_days": 7,
        "plan_label": plan_label(),
        "plan_price": plan_cents() // 100,
        "plan_cents": plan_cents(),
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


DEFAULT_PREFS: dict[str, Any] = {
    "show_promo_price": True,
    "banks": [],
    "supermarkets": [],
}


def normalizar_prefs(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return dict(DEFAULT_PREFS)
    show_promo = raw.get("show_promo_price")
    if not isinstance(show_promo, bool):
        show_promo = True
    banks = raw.get("banks")
    if not isinstance(banks, list):
        banks = []
    else:
        banks = [str(b).strip().lower() for b in banks if str(b).strip() and len(str(b)) <= 40]
    supermarkets = raw.get("supermarkets")
    if not isinstance(supermarkets, list):
        supermarkets = []
    else:
        supermarkets = [str(s).strip().lower() for s in supermarkets if str(s).strip() and len(str(s)) <= 40]
    return {
        "show_promo_price": show_promo,
        "banks": banks,
        "supermarkets": supermarkets,
    }


def es_trial_activo(trial_ends_at: str | None) -> bool:
    if not trial_ends_at:
        return False
    try:
        dt = datetime.fromisoformat(str(trial_ends_at).replace("Z", "+00:00"))
        return datetime.now(timezone.utc) < dt
    except Exception:
        return False


def calcular_plan_efectivo(
    plan: str,
    paid_at: str | None,
    trial_ends_at: str | None,
    role: str = "user",
) -> dict[str, Any]:
    if role == "admin":
        return {
            "plan_efectivo": "paid",
            "es_paid": True,
            "es_trial": False,
            "trial_activo": False,
            "trial_vencido": False,
        }
    if plan == "paid" and paid_at:
        return {
            "plan_efectivo": "paid",
            "es_paid": True,
            "es_trial": False,
            "trial_activo": False,
            "trial_vencido": False,
        }
    if es_trial_activo(trial_ends_at):
        return {
            "plan_efectivo": "paid",
            "es_paid": True,
            "es_trial": True,
            "trial_activo": True,
            "trial_vencido": False,
        }
    trial_vencido = bool(trial_ends_at and not es_trial_activo(trial_ends_at))
    return {
        "plan_efectivo": "free",
        "es_paid": False,
        "es_trial": False,
        "trial_activo": False,
        "trial_vencido": trial_vencido,
    }


async def activar_trial(user_id: str, days: int = 7) -> str:
    """Calcula y persiste 7 días de trial Plus para una cuenta nueva."""
    if not UUID_RE.match(user_id) or not cupo_on():
        return ""
    fin = datetime.now(timezone.utc) + timedelta(days=days)
    fin_iso = fin.isoformat()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.patch(
                f"{supabase_url()}/rest/v1/profiles?id=eq.{user_id}",
                headers=_service_headers(),
                json={"trial_ends_at": fin_iso},
            )
    except Exception:
        pass
    return fin_iso


def _cuenta_vacia() -> dict[str, Any]:
    return {
        "plan": "free",
        "plan_base": "free",
        "trial": False,
        "trial_activo": False,
        "trial_ends_at": None,
        "trial_ends_at_texto": "",
        "used": 0,
        "remaining": FREE_LIMIT,
        "limit": FREE_LIMIT,
        "role": "user",
        "admin": False,
        "prefs": dict(DEFAULT_PREFS),
    }


async def leer_cuenta(token: str, user_id: str) -> dict[str, Any]:
    if not UUID_RE.match(user_id):
        return _cuenta_vacia()
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            f"{supabase_url()}/rest/v1/profiles",
            params={"id": f"eq.{user_id}", "select": "plan,searches_used,paid_at,role,prefs,trial_ends_at"},
            headers=_user_headers(token),
        )
        if r.status_code != 200:
            r = await client.get(
                f"{supabase_url()}/rest/v1/profiles",
                params={"id": f"eq.{user_id}", "select": "plan,searches_used,paid_at,role,prefs"},
                headers=_user_headers(token),
            )
        if r.status_code != 200:
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

    trial_ends_at = row.get("trial_ends_at")
    prefs = normalizar_prefs(row.get("prefs"))
    if not trial_ends_at and isinstance(row.get("prefs"), dict):
        trial_ends_at = row["prefs"].get("trial_ends_at")

    # Si es cuenta nueva (sin paid_at y sin trial_ends_at) y no es admin, inicializamos 7 días de trial Plus
    if not trial_ends_at and not row.get("paid_at") and role != "admin":
        trial_ends_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        if cupo_on():
            try:
                import asyncio
                asyncio.create_task(activar_trial(user_id, 7))
            except Exception:
                pass

    calc = calcular_plan_efectivo(plan, row.get("paid_at"), trial_ends_at, role)
    if role == "admin" or calc["plan_efectivo"] == "paid":
        remaining = None
        limit = None
    else:
        remaining = max(0, FREE_LIMIT - used)
        limit = FREE_LIMIT

    return {
        "plan": calc["plan_efectivo"],
        "plan_base": plan,
        "trial": calc["es_trial"],
        "trial_activo": calc["trial_activo"],
        "trial_ends_at": trial_ends_at,
        "trial_ends_at_texto": formatear_art(trial_ends_at) if trial_ends_at else "",
        "used": used,
        "remaining": remaining,
        "limit": limit,
        "paid_at": row.get("paid_at"),
        "role": role,
        "admin": role == "admin",
        "prefs": prefs,
    }


async def guardar_preferencias(token: str, user_id: str, raw_prefs: Any) -> dict[str, Any]:
    prefs = normalizar_prefs(raw_prefs)
    if not cuentas_on() or not token or not UUID_RE.match(user_id):
        return {"ok": False, "reason": "auth", "prefs": prefs}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.patch(
            f"{supabase_url()}/rest/v1/profiles",
            params={"id": f"eq.{user_id}"},
            json={"prefs": prefs},
            headers={**_user_headers(token), "Content-Type": "application/json", "Prefer": "return=minimal"},
        )
        if r.status_code in (200, 204):
            return {"ok": True, "prefs": prefs, "synced": True}
        if cupo_on():
            r_serv = await client.patch(
                f"{supabase_url()}/rest/v1/profiles",
                params={"id": f"eq.{user_id}"},
                json={"prefs": prefs},
                headers=_service_headers(),
            )
            if r_serv.status_code in (200, 204):
                return {"ok": True, "prefs": prefs, "synced": True}
    return {
        "ok": True,
        "prefs": prefs,
        "synced": False,
        "note": "Guardado localmente. La columna prefs en Supabase aún no fue migrada.",
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


async def admin_listar_usuarios() -> list[dict[str, Any]]:
    """Devuelve la lista de usuarios combinando auth.users y public.profiles."""
    if not cupo_on():
        return []
    users_dict: dict[str, dict[str, Any]] = {}

    # 1. Traer auth.users
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{supabase_url()}/auth/v1/admin/users?per_page=50",
                headers=_service_headers(),
            )
            if r.status_code == 200:
                raw_users = r.json()
                items = (
                    raw_users.get("users")
                    if isinstance(raw_users, dict)
                    else (raw_users if isinstance(raw_users, list) else [])
                )
                for u in items:
                    uid = str(u.get("id") or "")
                    if uid:
                        users_dict[uid] = {
                            "id": uid,
                            "id_corto": uid[:8],
                            "email": str(u.get("email") or ""),
                            "created_at": formatear_art(u.get("created_at")),
                            "created_at_raw": str(u.get("created_at") or ""),
                            "last_sign_in": formatear_art(u.get("last_sign_in_at")),
                            "plan": "free",
                            "searches_used": 0,
                            "role": "user",
                            "paid_at": None,
                        }
    except Exception:
        pass

    # 2. Traer profiles
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r_prof = await client.get(
                f"{supabase_url()}/rest/v1/profiles?select=*",
                headers=_service_headers(),
            )
            if r_prof.status_code == 200:
                profiles = r_prof.json()
                if isinstance(profiles, list):
                    for p in profiles:
                        uid = str(p.get("id") or "")
                        if not uid:
                            continue
                        trial_ends = p.get("trial_ends_at") or (p.get("prefs", {}).get("trial_ends_at") if isinstance(p.get("prefs"), dict) else None)
                        calc = calcular_plan_efectivo(str(p.get("plan") or "free"), p.get("paid_at"), trial_ends, str(p.get("role") or "user"))
                        if calc["es_paid"] and p.get("paid_at"):
                            plan_display = "Paid (Plus)"
                        elif calc["es_trial"]:
                            plan_display = "Trial Plus"
                        elif calc["trial_vencido"]:
                            plan_display = "Free (vencido)"
                        else:
                            plan_display = "Free"

                        if uid not in users_dict:
                            users_dict[uid] = {
                                "id": uid,
                                "id_corto": uid[:8],
                                "email": str(p.get("display_name") or uid[:8]),
                                "created_at": "—",
                                "created_at_raw": "",
                                "last_sign_in": "—",
                                "plan": str(p.get("plan") or "free"),
                                "plan_display": plan_display,
                                "trial_ends_at": formatear_art(trial_ends),
                                "searches_used": int(p.get("searches_used") or 0),
                                "role": str(p.get("role") or "user"),
                                "paid_at": formatear_art(p.get("paid_at")),
                            }
                        else:
                            users_dict[uid]["plan"] = str(p.get("plan") or "free")
                            users_dict[uid]["plan_display"] = plan_display
                            users_dict[uid]["trial_ends_at"] = formatear_art(trial_ends)
                            users_dict[uid]["searches_used"] = int(p.get("searches_used") or 0)
                            users_dict[uid]["role"] = str(p.get("role") or "user")
                            users_dict[uid]["paid_at"] = formatear_art(p.get("paid_at"))
    except Exception:
        pass

    out = list(users_dict.values())
    for u in out:
        if "plan_display" not in u:
            u["plan_display"] = "Free"
        if "trial_ends_at" not in u:
            u["trial_ends_at"] = "—"
    out.sort(key=lambda x: x.get("created_at_raw") or "", reverse=True)
    return out


async def admin_detalle_usuario(user_id: str) -> dict[str, Any] | None:
    if not UUID_RE.match(user_id):
        return None
    usuarios = await admin_listar_usuarios()
    target = next((u for u in usuarios if u["id"] == user_id), None)
    if not target:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    f"{supabase_url()}/rest/v1/profiles?id=eq.{user_id}",
                    headers=_service_headers(),
                )
                if r.status_code == 200:
                    rows = r.json()
                    if isinstance(rows, list) and rows:
                        p = rows[0]
                        trial_ends = p.get("trial_ends_at") or (p.get("prefs", {}).get("trial_ends_at") if isinstance(p.get("prefs"), dict) else None)
                        target = {
                            "id": user_id,
                            "id_corto": user_id[:8],
                            "email": str(p.get("display_name") or user_id[:8]),
                            "created_at": "—",
                            "last_sign_in": "—",
                            "plan": str(p.get("plan") or "free"),
                            "plan_display": "Paid (Plus)" if p.get("paid_at") else ("Trial Plus" if es_trial_activo(trial_ends) else "Free"),
                            "trial_ends_at": formatear_art(trial_ends),
                            "searches_used": int(p.get("searches_used") or 0),
                            "role": str(p.get("role") or "user"),
                            "paid_at": formatear_art(p.get("paid_at")),
                        }
        except Exception:
            pass
    if not target:
        return None

    busquedas = []
    if cupo_on():
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r_srch = await client.get(
                    f"{supabase_url()}/rest/v1/searches?user_id=eq.{user_id}&order=created_at.desc&limit=50",
                    headers=_service_headers(),
                )
                if r_srch.status_code == 200:
                    items = r_srch.json()
                    if isinstance(items, list):
                        for s in items:
                            busquedas.append({
                                "query": str(s.get("query") or ""),
                                "created_at": formatear_art(s.get("created_at")),
                            })
        except Exception:
            pass

    return {
        "usuario": target,
        "busquedas": busquedas,
    }


async def admin_listar_busquedas(limit: int = 50) -> list[dict[str, Any]]:
    if not cupo_on():
        return []
    usuarios = await admin_listar_usuarios()
    email_map = {u["id"]: u["email"] for u in usuarios}

    busquedas = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{supabase_url()}/rest/v1/searches?select=*&order=created_at.desc&limit={limit}",
                headers=_service_headers(),
            )
            if r.status_code == 200:
                rows = r.json()
                if isinstance(rows, list):
                    for row in rows:
                        uid = str(row.get("user_id") or "")
                        busquedas.append({
                            "id": str(row.get("id") or ""),
                            "user_id": uid,
                            "email": email_map.get(uid, uid[:8] if uid else "Anónimo"),
                            "query": str(row.get("query") or ""),
                            "created_at": formatear_art(row.get("created_at")),
                        })
    except Exception:
        pass
    return busquedas


async def admin_listar_pagos() -> dict[str, Any]:
    if not cupo_on():
        return {"pagos": [], "total_mes": "$0", "total_lifetime": "$0", "vacio": True}
    usuarios = await admin_listar_usuarios()
    email_map = {u["id"]: u["email"] for u in usuarios}

    pagos = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{supabase_url()}/rest/v1/profiles?plan=eq.paid&select=*",
                headers=_service_headers(),
            )
            if r.status_code == 200:
                rows = r.json()
                if isinstance(rows, list):
                    for row in rows:
                        uid = str(row.get("id") or "")
                        pagos.append({
                            "user_id": uid,
                            "email": email_map.get(uid, uid[:8]),
                            "payment_id": str(row.get("mp_payment_id") or "Manual/Admin"),
                            "monto": plan_label(),
                            "status": "Aprobado",
                            "fecha": formatear_art(row.get("paid_at")),
                        })
    except Exception:
        pass

    return {
        "pagos": pagos,
        "total_mes": f"${len(pagos) * (plan_cents() // 100):,.0f}".replace(",", ".") if pagos else "$0",
        "total_lifetime": f"${len(pagos) * (plan_cents() // 100):,.0f}".replace(",", ".") if pagos else "$0",
        "vacio": len(pagos) == 0,
    }


async def consumir(user_id: str, query: str) -> dict[str, Any]:
    if not cupo_on():
        raise RuntimeError("sin service role")
    if not UUID_RE.match(user_id):
        return {"ok": False, "reason": "auth"}

    # Chequear si tiene trial activo o plan paid antes de aplicar límite
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r_prof = await client.get(
                f"{supabase_url()}/rest/v1/profiles?id=eq.{user_id}",
                headers=_service_headers(),
            )
            if r_prof.status_code == 200:
                rows = r_prof.json()
                if isinstance(rows, list) and rows:
                    p = rows[0]
                    plan = str(p.get("plan") or "free")
                    paid_at = p.get("paid_at")
                    trial_ends_at = p.get("trial_ends_at")
                    if not trial_ends_at and isinstance(p.get("prefs"), dict):
                        trial_ends_at = p["prefs"].get("trial_ends_at")
                    role = str(p.get("role") or "user")
                    calc = calcular_plan_efectivo(plan, paid_at, trial_ends_at, role)
                    if calc["es_trial"]:
                        # Trial activo: búsquedas sin tope
                        q_clean = query[:80].strip()
                        await client.post(
                            f"{supabase_url()}/rest/v1/searches",
                            headers=_service_headers(),
                            json={"user_id": user_id, "query": q_clean},
                        )
                        used = int(p.get("searches_used") or 0)
                        return {
                            "ok": True,
                            "plan": "paid",
                            "trial": True,
                            "used": used,
                            "remaining": None,
                            "limit": None,
                        }
    except Exception:
        pass

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
        "statement_descriptor": "BARATOYA",
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
