# Promos bancarias semanales (lunes a domingo)

Regenera `data/promos-semana.json` desde páginas y endpoints **públicos** (sin login, sin cookies, sin tokens), valida,
corre los tests y abre un PR. **Nunca mergea ni despliega.** No escribe en Supabase.

## Cómo correrlo los lunes

```bash
pip install -r scripts/promos/requirements.txt      # una vez (beautifulsoup4 + pytest; la app ya trae el resto)
gh auth status                                      # tiene que decir: account mtfrat
python3 scripts/promos_semana.py --pr               # semana de hoy (lunes→domingo); en domingo arma la que viene
```

Ensayo sin tocar el repo ni GitHub (descarga, arma, valida y corre los tests sobre una copia):

```bash
python3 scripts/promos_semana.py --dry-run [--semana 2026-11-09]
```

El PR sale contra `master` (`--base` para cambiarlo), rama `promos/semana-AAAA-MM-DD`. Si ya hay un PR abierto para
esa semana no crea otro; si el resultado es idéntico a lo versionado dice "nada para hacer". Correrlo dos veces es seguro.

## Qué hace, en orden

1. **Fetch** (`promos/fetch.py`): páginas de Día, La Anónima, Makro, Maxiconsumo, Super Mami, Cordiez, Toledo; JSON de Cencosud (Jumbo/Disco/Vea)
   y de Coto; entidades públicas BP/FB/FC de VTEX (Mas Online, Carrefour). Si una fuente falla o viene chica, aborta con su nombre.
2. **Armado**: un módulo por fuente (`dia`, `bp`, `cenco`, `coto`, `laanonima`, `pages`). Regla: **no se inventan datos**.
   Se reutiliza lo resuelto la semana anterior (`promos/state/*.json`) sólo si la card/página es idéntica o cambió únicamente en
   fechas o redacción; si cambió un número, una condición o hay una card nueva, queda **pendiente**.
3. **Pendientes** → el script se frena (exit 2) y deja `.promos-work/<lunes>/pendientes.json` con una plantilla por cada uno.
   Alguien lee la fuente, completa y vuelve a correr con `--overrides resueltos.json`. Para Makro/Maxiconsumo/Super Mami/Cordiez/Toledo
   (páginas sin datos estructurados) que cambiaron: revisar y luego `--aprobar-paginas makro,toledo`.
   `--allow-unresolved` descarta los pendientes y sigue (quedan listados en el PR).
4. **Alarmas** (exit 3): cadena vacía, caída de más de 40% de filas-día contra la semana anterior, o Jumbo/Disco/Vea con menos de 10 promos un día.
   `--allow-alarms` sigue igual, pero hay que mirar por qué.
5. **Tests**: suite normal y `BARATOYA_TESTS_REALES=1` (data y reloj reales). Si falla algo (exit 4), no se commitea.
6. **PR** con `gh pr create` (resumen por cadena, cambios, alarmas, pendientes, tests). Esperar el OK de Martin antes de mergear.

Códigos de salida: 0 ok · 2 pendientes · 3 alarmas · 4 tests · 5 entorno (fuente caída, gh mal autenticado, etc.).

## Regla de producto

Las promos bancarias van **aparte** del precio de góndola. El pipeline sólo carga datos de la promo (valor, días, tope, condiciones, vigencia,
`do_not_apply`); nunca precios. `test_promos_no_restan.py` verifica sobre toda la data que sólo se calcula un "total con promo" en el caso
acotado de `promos_hoy.puede_restar` (porcentaje online con tope en pesos, sin `do_not_apply`, sin "no acumula"); cuotas, sucursal, sin tope
o con condición nunca restan.

## Mantenimiento

- `promos/state/` guarda lo resuelto de la semana anterior (cards de Día/Cencosud/VTEX, huellas de páginas). Se actualiza en cada corrida real;
  va en el PR para que se pueda revisar.
- Un `ref` estable por fila (`J...`, `M:...`, `C:...`, `D#`, `L#`) identifica la promo entre semanas.
- Nada de secretos: todo lo que se consulta es público. No guardar cookies ni tokens en `state/` ni en `.promos-work/` (ignorado por git).
