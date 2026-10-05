# BaratoYa — actualizar promos bancarias semana 05–11/10/2026 (brief para agente de código)

Repo: https://github.com/mtfrat/baratoya (master; Vercel despliega desde master; deploy autorizado).
Archivo adjunto: promos-semana-2026-10-05.json (366 filas, 13 cadenas) = fuente de verdad, ya validada (relevada 04/10/2026 ~23:55 ART). No re-scrapear ni editar valores.

Esquema por fila: chain (dia, masonline, carrefour, jumbo, disco, vea, cotodigital, cordiez, toledo, laanonima, makro, maxiconsumo, supermami), bank, kind ('percent'|'installments'; en cuotas value = cantidad), value, days (ISO 1=lunes…7=domingo; promos_hoy usa 0=lunes → convertir), channel ('online'|'store'=sucursal|'both'), cap (ARS o null; período en legal), minimum, valid_from, valid_to, legal, source_url, do_not_apply (null o motivo), ref.

Tareas:
1. Copiar el JSON a data/promos-semana.json y hacer que promos_hoy lo use como fuente para todas las cadenas incluidas (reemplaza dia-promos.json, mas-online-promos.json, cordiez/toledo/la-anonima/makro-promos.json y las secciones Carrefour/Coto de promos-js.md para esas cadenas; no borrar archivos viejos). Mapear al formato interno (banco, percent/cuotas, days, canal, cap, minimo, inicio, fin, exclusion/legal) para que la UI y /api/promos sigan igual. Sumar Jumbo, Disco, Vea, Maxiconsumo y Super Mami; actualizar/quitar las notas de notas_cadenas_sin_promo() que dicen que Jumbo/Disco/Vea no tienen promos. Josimar y Comodín: sin cambios.
2. do_not_apply no nulo => se muestra como info pero NUNCA se resta del precio (puede_restar False). Mantener las reglas actuales de puede_restar. Cuotas nunca se restan.
3. Mostrar solo si valid_from <= hoy (America/Argentina/Buenos_Aires) <= valid_to y el día está en days.
4. No pasar a leer Supabase en este cambio (la RLS pública oculta las filas con do_not_apply); no tocar Supabase, env vars ni RLS.
5. Sin rediseño. Correr tests existentes (test_match.py / pytest) + smoke de app.py y /api/promos; todo debe pasar. Agregar test: fila con do_not_apply no se resta; día ISO 7 = domingo.
6. Commit claro y push a master. Reportar SHA y conteos por cadena de /api/promos para el lunes 05/10/2026.
