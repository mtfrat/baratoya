# BRIEF Antigravity — BaratoYa pendientes (lote único)

Repo: `C:\Users\martin\Documents\baratoya` → https://github.com/mtfrat/baratoya · rama `master` · Vercel auto-deploy.
Marca: Atkinson Hyperlegible + Libre Baskerville · forest `#163300` · lima `#9FE870`.
Admin mail: `baratoyaba@gmail.com`. Dominio: `https://baratoya.app`.
Antes de codear: plan corto (problema → plan → alcance). Prohibido parches sueltos.

## Ya hecho (NO rehacer)
- Live prices, logos bancos, tipografía, prefs bancos/súpers, filtro supers, Ver promos del súper + disclaimer.
- Landing `/planes`, Checkout Pro código, MP token prod + webhook en Vercel.
- Chips wrap sin scroll (`2c4afc1`).
- Resend SMTP Auth (`noreply@baratoya.app`).
- "Ver precio" debería ser `_blank` (verificar, no romper).

---

## P0 — Landing pública + muro de login (prioridad)

### Problema
Sin cuenta se puede mirar Promos (y contenido útil). Martin: **no se ve nada útil sin ingresar**; landing “como la gente”.

### Objetivo
- **Público:** `/`, `/planes`, legales, assets marketing. Hero, cómo funciona, planes, FAQ, CTAs registro/login. Sin promos del día, sin resultados, sin listados útiles.
- **Privado (sesión):** Buscar, Promos, listas, alertas, prefs, admin, checkout API.
- Anónimo → API promos/search → **401/403**. UI Promos/buscar → modal login: “Creá una cuenta gratis para ver promos y precios.”
- Muro = **auth**, no pago (free sigue con límite búsquedas).
- No romper webhook MP ni exponer secrets.

### Tests
Anónimo sin promos; logueado OK; suite verde.

---

## P1 — Admin detalle

### Problema
`/admin` solo totales; no se puede navegar al detalle.

### Objetivo
Cards clickeables → `/admin/usuarios` (+ detalle por id), `/admin/busquedas`, `/admin/pagos` + ingresos.
Campos desde DB real (profiles, searches/usage, lists, alerts, payments). Paginación ~50.
Vacíos honestos. Solo rol admin. Breadcrumb. MP set sí/no (boolean env, no token).
Timestamp ART en resumen.

### Tests
Admin 200; no-admin 403. Extender tests.

---

## P2 — Pulido post-gate (si queda tiempo en el mismo lote)

- Home anónima: nav limpia (Planes, Cómo funciona, Ingresar / Crear cuenta); sin link “Promos” que muestre data.
- Site URL / redirects: documentar en README que Supabase debe tener `https://baratoya.app` (+ vercel.app).
- Copy landing sharp, mobile ~390px, touch ≥44px.
- Si plantillas Auth en español: **NO** en código — nota en README para panel Supabase Email Templates (opcional).

---

## Fuera de alcance (Martin / otro canal)
- Reel CapCut / screen-record.
- Posts redes.
- X BaratoYa (bloqueado hasta bio+link).
- Cambiar precio plan (default $1.990 = 199_000 cents).

---

## Entrega
1. Implementar **P0 completo** primero; luego P1.
2. Tests OK.
3. Commit(s) claros + **push master**.
4. Reportar: SHA(s), rutas/APIs gateadas, rutas admin nuevas, campos↔tablas.

Reemplaza / prioriza sobre `BRIEF-landing-login-wall.md` y `BRIEF-admin-detalle.md` (podés archivarlos o dejarlos como detalle; **este archivo manda**).
---

## P0b — QA Auth (bloqueante, Martin 2026-10-05)

### Bug
En el popup de entrar: mail que **no existe** + Entrar → el popup **se cierra y no pasa nada** (sin error visible).

### Obligatorio
- Mostrar error claro en el modal (ej. “No encontramos esa cuenta” / mensaje real de Supabase), **sin cerrar** el diálogo.
- Misma regla para: password incorrecta, mail inválido, rate limit, network error.
- Nunca cerrar el modal en fallo de login/registro/recovery.
- Tras éxito sí cerrar y refrescar sesión.
- Revisar registro (mail ya usado) y “olvidé contraseña” (feedback visible).

### Tests
- Login fail → modal abierto + texto error en DOM.
- Login ok → sesión.
- No más “fail silently”.

**Doctrina:** todo flujo auth/UI crítico pasa por QA de errores antes de push. No nos puede pasar más.

---

### Bug extra (Martin 2026-10-05, /planes)
Botón **Crear cuenta** en el modal Entrar: click → no pasa nada (sin feedback, sin cambio de modo registro, sin error).
Arreglar: modo registro funcional + errores visibles + tests (crear cuenta / mail ya usado).

---

## P1.5 — Trial 7 días Plus (freemium)

### Objetivo
Cuenta nueva → **Plus trial 7 días** (búsquedas sin tope + alertas como paid) → al vencer: plan **free** (5 búsquedas/mes) salvo que pague Checkout Pro.

### Backend
- Campos: 	rial_ends_at (o equivalente) + plan efectivo paid mientras trial activo.
- Signup setea trial 7 días ART.
- cupo/gates usan plan efectivo (admin sin tope).
- Webhook MP: paid permanente cancela/supersede trial.
- Copy UI: “7 días Plus gratis” en landing/planes/modal; fecha fin en prefs.

### Tests
Signup → trial activo; día 8 simulado → free; pago → paid sin tope.

---

## P2b — Contacto visible
Footer + legal + página planes/landing: mail de soporte **baratoyaba@gmail.com** (mailto + texto). Copy corto: “¿Problema o bug? Escribinos.”

---

## P3 — BeautifulUI (aplicar patrones; no copiar React)

Fuente: https://www.beautifului.dev/ (MIT). Reimplementar en HTML/CSS/JS on-brand. No tocar auth ni MP.
Orden: **1 → 2 → 5 → 3 → 4** (después de P0/P0b/P1/P1.5, o en paralelo si no pisa esos archivos).

1. **Progreso por súper** mientras busca: fila por cadena (respetar Mis supermercados) con buscando / listo (N) / sin respuesta + segundos. Nada mudo >1s.
2. **Tarjeta "Mejor compra"** arriba de resultados: súper más barato, ahorro $/%, precio con promo del día si hay, CTA Ir a súper. Solo datos reales.
3. **Insight de ahorro** en /planes y muro login: ejemplo REAL de búsqueda (“Hoy la yerba X está $Y más barata en Z”). Sin cifras inventadas.
4. **Admin tabla densa** (con P1): orden, chips estado, actividad relativa.
5. **Skeleton/shimmer** en cards de resultados y modal Promos; prefers-reduced-motion.

Criterio done: 1+2+5 en prod; 3 si hay dato real; 4 con admin detalle.
