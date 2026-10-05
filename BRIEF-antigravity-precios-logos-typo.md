# BaratoYa — lote crítico 1–3 (brief Antigravity)

Repo: `C:\Users\martin\Documents\baratoya` → https://github.com/mtfrat/baratoya (master; Vercel despliega desde master; deploy autorizado).

Hacé los tres ítems en un solo commit (o PR pequeño) a master. Investigá vos; las hipótesis son orientativas.

## 1) Precios siempre vivos
Problema: pueden quedar precios viejos. Ejemplo: Playadito Suave 1 kg el sáb 3 estaba $3.969; hoy (lun 5 ~17:30 ART) en Mas Online es ~$5.289 sin promo. No confundir con Playadito Sin Palo 500g (~$3.969). `/api/buscar` puede pedir login (401 sin sesión).

Objetivo: toda búsqueda/resultado trae precio de góndola actual (sin cache multi-día). Las reglas de promo bancaria ya corregidas se mantienen (`do_not_apply` nunca resta; cuotas nunca restan).

Hipótesis (verificar/descartar): TTL de cache largo, snapshot estático, o match de SKU incorrecto.

Verificación: smoke con sesión + búsqueda Playadito Suave 1 kg → precio alineado a Mas Online del día.

## 2) Logos oficiales de bancos / billeteras
Hoy ~57 SVGs en Supabase `brand-logos` vía `brand_logos.py` + `data/brand-logos.json`, pero muchos son tiles con el nombre en color, no marcas reconocibles. Visa/Mastercard/Amex/Carrefour OK; Galicia/BBVA/Santander/etc. se ven vacíos.

Objetivo: reemplazar assets por marcas oficiales (o Simple Icons / Wikimedia Commons / Clearbit-style) redistribuibles; SVG/PNG chicos; actualizar `brand-logos.json` y subir/commitear como ya hace el repo. UI de filtros con logos reales. No inventar promos. Anotar fuente en comentario o README corto.

## 3) Tipografía Atkinson Hyperlegible + Libre Baskerville
Brand sheet v3 Humanist cerrado: UI sans = Atkinson Hyperlegible; acentos italic = Libre Baskerville. La app puede seguir en Inter.

Objetivo: migrar CSS/templates a Atkinson + Libre Baskerville (Google Fonts o archivos OFL en `static/`). Roles: body/UI Atkinson; precios Atkinson bold tabular; “lista”/acentos italic Baskerville. Sin rediseño más allá de fuentes.

Colores de marca: forest `#163300`, lima `#9FE870`, fog `#E8EBE6`, char `#454745`.

## Constraints
- UI en español.
- No tocar Mercado Pago / planes pagos en este lote.
- No debilitar auth (search puede seguir con login).
- Correr tests existentes (`test_match.py` / pytest) y dejarlos en verde.
- Commit claro + push a master. Reportar SHA y cómo verificar en baratoya.vercel.app.

## Orden sugerido
Tipografía (rápido) → logos (assets) → precios (diagnóstico + fix) → tests → push.
