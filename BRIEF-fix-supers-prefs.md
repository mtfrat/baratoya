# BaratoYa — fix: “Mis supermercados” no filtra

Repo: `C:\Users\martin\Documents\baratoya` → master (deploy autorizado).

## Bug (repro)
1. Preferencias → marcar solo **Día** → Guardar.
2. Ir a **Promos**: siguen apareciendo Carrefour y el resto (141 de hoy).
3. En **Buscar**: las otras cadenas siguen en las cards; hoy el código solo **prioriza** (sort) las favoritas, no las filtra.

Causa confirmada en `super_cadenas.py` ~1496: si hay `supermercados_permitidos`, hace `ofertas.sort(... fav first ...)` pero **no elimina** las no favoritas. La grilla de Promos ignora por completo `userPrefs.supermarkets`.

## Fix obligatorio

### A) Búsqueda / cards de producto
Cuando `prefs.supermarkets` (o query `supermercados=`) tiene ≥1 id:
- En `agrupar_mismo_producto` (o `_presentar_super`): **filtrar** `ofertas` a solo `tienda_id` ∈ favoritos (casefold).
- Si un grupo queda sin ofertas → no incluirlo en resultados.
- Vacío / sin prefs → comportamiento actual (todas las cadenas).
- Mantener cálculo de promo bancaria como está.

### B) Sección Promos (“Promos de banco, juntas”)
Cuando el usuario tiene supermercados guardados:
- Filtrar las cards de promo a esas cadenas (`chain` / `tienda_id` alineado con ids: `dia`, `carrefour`, `masonline`, …).
- Mostrar copy claro: “Mostrando promos de tus súpers (Día). Cambiá en Preferencias.”
- Si vacío → todas (como ahora).
- Ideal: al cargar prefs, aplicar el mismo filtro sin forzar al usuario a tocar el dropdown otra vez.

### C) IDs
Asegurar que chips de prefs usan los mismos ids que promos/cadenas (`dia` no `día`, `masonline`, `cotodigital`, `laanonima`, etc.). Si hay mismatch Día↔promos, mapear.

### D) Tests
- Con `supermarkets=["dia"]`, ofertas de carrefour no aparecen en el grupo.
- Grupo solo Carrefour + filtro Día → grupo omitido.
- Promos filtradas por cadena preferida.
- Lista vacía de supers → sin filtro.

## Entrega
Commit + push master. Reportar SHA. No tocar Mercado Pago.
