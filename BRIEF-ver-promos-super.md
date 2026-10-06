# BaratoYa — botón “Ver promociones del supermercado” en cada oferta

Repo: `C:\Users\martin\Documents\baratoya` → master (deploy autorizado).
UI ES. Atkinson + Baskerville. No inventar precios/promos.

## Contexto
Ya funciona filtro de súpers del perfil + precio góndola (ej. Día $3.000 dulce de leche). Falta, en cada card de tienda, poder ver **todas** las promos bancarias de **ese súper** para **hoy** (o el día elegido) y el **precio final** de ese producto con cada una.

Referencia UX: en diaonline hay “Promociones Bancarias”; acá queremos el cálculo aplicado al producto de la card.

## Objetivo
En cada oferta de súper (ej. fila Día / El Abastecedor / …):

1. Botón/link: **“Ver promociones del súper”** (o “Promos de Día”).
2. Al click: panel/drawer/modal (sin salir de BaratoYa) con:
   - Nombre del súper + producto + precio góndola
   - Selector de día (default: hoy ART; mismos días que la sección Promos)
   - Lista de promos **de esa cadena** ese día (fuente `promos_hoy` / semana), una fila por promo aplicable:
     - Banco/billetera + logo si hay
     - % o cuotas (cuotas: mostrar beneficio, **no restar** del precio)
     - **Precio final** si `puede_restar` (respetar `do_not_apply`, canal online/both, tope/cap si afecta el display)
     - Línea corta legal opcional (tope, vigencia) — no el acordeón viejo “letra”
   - Si el usuario tiene bancos en prefs: destacar primero “Tus bancos”; igual mostrar el resto colapsable o debajo (“Otras promos del súper”).
3. Ordenar: mayor descuento efectivo primero (menor precio final); cuotas al final.
4. CTA “Ir a la tienda” = mismo URL con `target=_blank`.

## Alcance
- Solo súper (no electro en v1, salvo que reutilizar sea trivial).
- No reemplaza el precio principal de la card; es detalle on-demand.
- Respetar prefs `show_promo_price` solo para el precio destacado de la card; el panel de promos del súper siempre calcula (es explícito).
- Filtro de súpers del perfil ya debe estar filtrando cards; este botón es por card visible.

## Implementación sugerida (no dogmática)
- Reusar lógica de `puede_restar` / aplicar % sobre góndola.
- Endpoint opcional `GET /api/promos?cadena=dia&dia=lunes` o filtrar client-side desde `/api/promos` ya cargado.
- Tests: Día + lunes → N promos con precio final; cuotas no bajan precio; do_not_apply no resta.

## Entrega
Commit + push master. SHA + cómo probar (producto con Día, click botón, ver finales).
