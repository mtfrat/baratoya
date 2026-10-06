# BaratoYa — landing + planes + pulido móvil (producto vendible)

Repo: `C:\Users\martin\Documents\baratoya` → master (deploy autorizado).
Marca: Atkinson Hyperlegible + Libre Baskerville; forest `#163300`, lima `#9FE870`, fog `#E8EBE6`, char `#454745`.
UI español. No inventar métricas ni precios fuera del código.

## Cobro Mercado Pago (ya parcialmente cableado)
- `cuentas.py`: Checkout Pro crea preference; webhook `/api/mercadopago/webhook` confirma pago → `plan=paid`.
- Plan pago actual en código: `DEFAULT_PLAN_CENTS = 199_000` → **$1.990 ARS/mes** (override con env `BARATOYA_PLAN_ARS_CENTS`).
- Falta en prod: `MERCADOPAGO_ACCESS_TOKEN` en Vercel. Sin token, UI debe decir claro que el pago no está activo (no inventar éxito).
- Flujo: usuario elige plan pago → backend preference → redirect MP → vuelve a baratoya → webhook marca paid.

## Planes a mostrar en `/planes` (y bloque en landing)
Usar montos del código:
1. **Gratis** — $0 — cupo de búsquedas (el del producto), listas básicas, prefs.
2. **BaratoYa Plus** — **$1.990/mes** — búsquedas sin el tope free (como `plan=paid` hoy), alertas, listas; CTA “Pagar con Mercado Pago”.
3. (Opcional UI) no inventar un tercer plan si el backend solo tiene free|paid; mejor 2 cards honestas. Si querés “Pro” visual, debe mapear al mismo `paid` o no incluirlo.

FAQ corto: cancelación vía MP; precios con promo son estimados; no es compra en el súper.

## Pantallas a mapear y pulir (mobile-first ~390px)
1. Landing logged-out (hero + cómo funciona + planes + CTA entrar)
2. Buscar logueado (cards, touch targets)
3. Promos
4. Preferencias modal
5. `/planes` nueva
6. Panel “Ver promos del súper” si aún falta (disclaimer estimado)
7. Legal + 404 tipografía
No romper Admin.

## Assets
- 1 hero / mock de comparación on-brand en `static/` (PNG o SVG).
- meta OG básico.

## Responsive
Nav usable en celular; sin overflow; chips de prefs scrolleables; precios legibles.

## Entrega
Commit + push master. SHA. Checklist: “poner MERCADOPAGO_ACCESS_TOKEN en Vercel → redeploy → probar pago sandbox/test”.
