# BaratoYa — precio final con promo + preferencias de perfil

Repo: `C:\Users\martin\Documents\baratoya` → https://github.com/mtfrat/baratoya  
Rama: `master` (Vercel despliega desde master; deploy autorizado).  
UI en español. Tipografía Atkinson Hyperlegible + Libre Baskerville.  
No inventar precios ni promos: usar `promos_hoy` / `data/promos-semana.json` y reglas actuales (`do_not_apply` nunca resta; cuotas nunca restan; solo canal online/both cuando aplica; vigencia por día ART).

---

## 1) Quitar la “letra” / ruido de promo en la card

Problema: en resultados se muestra texto/letra de promo poco claro o que ensucia la card.

Objetivo:
- Dejar de mostrar la letra/código/aviso confuso de promo en la card principal (investigar el copy actual: “letra de la promo”, badges legales densos, etc.).
- Si hay descuento bancario aplicable, mostrar de forma limpia el **precio final** (ver §2), no un bloque de letra cruda.
- El detalle legal puede vivir en tooltip, “¿cómo se calcula?” o solo en el drawer de promos — no en el primer vistazo de la card.

---

## 2) Precio final con promociones bancarias del súper ese día

Objetivo: al buscar, para cada oferta de una cadena, calcular el **precio con promo** usando las promos bancarias vigentes **ese día** (America/Argentina/Buenos_Aires) **para ese súper**, respetando:
- `valid_from` / `valid_to` y `days`
- `puede_restar` (sin restar si `do_not_apply`, cuotas, canal store-only, etc.)
- Preferencias de bancos del usuario (§3): si el usuario tiene bancos configurados, calcular con **sus** bancos; si no, con el mejor descuento aplicable entre todos (o el del filtro activo de la UI, si hay filtro de bancos en la sesión).

UI en card (cuando el toggle esté ON):
- Precio góndola (tachado o secundario si hay descuento)
- **Precio con tu promo** (o “Con promo”) destacado
- Una línea corta: banco + % (ej. “Galicia 25%”) — sin pegar el legal largo
- Si ninguna promo resta: solo góndola (comportamiento actual limpio)

Toggle de usuario (§3): si “Ver precio con promo” está **desactivado**, no calcular ni mostrar precio con promo (solo góndola + link tienda).

---

## 3) Perfil / Cuenta: preferencias editables

Nueva sección en cuenta/perfil (modal o `/cuenta` — reutilizar lo que ya exista de sesión Supabase):

### A) Ver precio con promo
- Switch: **activado / desactivado** (default: **activado** para cuentas nuevas, o el default que ya use el producto si hay uno).
- Persistido en perfil (Supabase): ej. `profiles.prefs` JSONB o columnas `show_promo_price boolean`.
- Debe aplicarse en todas las búsquedas del usuario logueado sin re-filtrar a mano.

### B) Mis bancos
- Multi-select con los mismos bancos/billeteras del catálogo de logos (`brand-logos` / pins).
- Persistido: lista de `brand_id` o nombres normalizados.
- Efecto: el cálculo de precio con promo y el filtro default de la home usan estos bancos (el usuario no tiene que marcar el dropdown cada vez).
- Vacío = sin restricción (todas las promos elegibles).

### C) Mis supermercados
- Multi-select de cadenas activas (dia, masonline, carrefour, jumbo, disco, vea, cotodigital, cordiez, toledo, laanonima, makro, maxiconsumo, supermami, josimar, comodin, etc. — las que el producto ya lista).
- Persistido igual.
- Efecto: la búsqueda prioriza / filtra por esas cadenas por defecto (sigue pudiendo ampliar en la UI si hay control; si no hay UI de cadenas, aplicar filtro server-side o client-side al renderizar resultados).
- Vacío = todas las cadenas.

Guardar con botón claro “Guardar preferencias” + feedback corto. Cargar prefs al login / al abrir la app.

---

## 4) “Ver precio” (tienda) no saca de BaratoYa

Todos los links a la tienda (“Ver precio” / ir al súper):
- `target="_blank"` + `rel="noopener noreferrer"`
- Nunca `window.location` same-tab

(Incluye súper y electro.)

---

## 5) Admin (si entra en el mismo lote; si no, commit aparte después)

Si el tiempo alcanza en este mismo brief: métricas del `/admin` clickeables con detalle (usuarios, búsquedas, pagos). Si no, priorizar §§1–4 y dejar admin para el brief `BRIEF-admin-detalle.md`.

---

## Constraints
- No tocar Mercado Pago / cobro en este lote.
- No debilitar auth (búsqueda con login si ya lo está).
- No restar promos que `puede_restar` diga que no.
- Tests: precio con promo ON/OFF; banco preferido limita descuento; link target=_blank; prefs se leen/escriben (mock o integration liviana).
- Commit claro + push a `master`. Reportar SHA, campos nuevos en Supabase/migración, y cómo probar.

## Orden sugerido
1. Links `_blank`  
2. Prefs perfil (toggle + bancos + súpers) + migración/cols  
3. Cálculo precio final en API/UI según prefs y día  
4. Limpiar “letra” de promo en cards  
5. Tests + push  
