# Deploy gratis de BaratoYa

Host elegido: **Vercel Hobby**, en el team que Martin ya tiene (`mfrat's projects`, slug `mfrats-projects`). Mismo patrón que `mtfrat/punav2` → proyecto Vercel `punav2` → `https://punav2.vercel.app`.

No hace falta Dockerfile, Procfile ni `vercel.json`. Vercel detecta FastAPI si hay `requirements.txt` y un `app = FastAPI(...)` en `app.py` (raíz del repo).

No se creó el proyecto Vercel ni el repo de GitHub. No hay dominio. No hay Mercado Pago. Las páginas legales siguen marcadas **BORRADOR** y este deploy no las vuelve finales.

## Por qué este host y no otro

La búsqueda (`/api/buscar`) es HTTP saliente a Precios Claros y catálogos públicos. No necesita base de datos. FastAPI en Vercel Hobby corre como una Function (Python 3.13, duración incluida hasta 300 s). El plan Hobby ya está en la cuenta: no hay que crear un plan pago, ni Blob, ni Postgres, ni KV.

Lo que no entra en $0 con datos que sobrevivan:

| Host | Por qué no |
| --- | --- |
| Railway | No hay plan free durable. El Hobby es de pago. No crear esa cuenta ni ese plan. |
| Render free | Aunque exista un web service free, el disco es efímero y el servicio se duerme. Habría que abrir otra cuenta. SQLite se pierde igual. |
| Fly.io | El free allowance no alcanza para un volumen. Sin volumen, SQLite también se pierde, y el volumen es un addon pago. |

Si más adelante la lista de compras tiene que persistir, eso es un disco o una base pagos. No está en este camino.

## Qué archivos suben

Repo nuevo, raíz = esta carpeta (`baratoya/`):

- `app.py` — entrypoint (`app`)
- `electro.py`, `super_cadenas.py`
- `templates/`
- `snapshots/last_ok.json` — solo fallback si Precios Claros falla; en Vercel no se reescribe (disco de solo lectura)
- `requirements.txt`
- `.python-version` — `3.13`
- `DEPLOY.md`, `README.md`, docs de producto

No subir `data/*.sqlite` (está en `.gitignore`). No subir `.env` ni tokens.

En Vercel el import es `app.py` directo (`from electro import ...`). En la box sigue `uvicorn baratoya.app:app` desde `/workspace/micro-saas`.

## Variables de entorno

Ninguna es obligatoria. Ninguna debe ser secreta para este deploy.

Dejar vacío el formulario de env de Vercel, o fijar solo esto (todo público / apagado):

```
ENABLE_PAID_SCRAPERS=false
ENABLE_MLA=false
```

No configurar:

- `MERCADOPAGO_ACCESS_TOKEN`, `STRIPE_SECRET_KEY`
- `BRIGHTDATA_API_KEY`, `SCRAPERAPI_KEY`, `MLA_ACCESS_TOKEN`, `GOOGLE_VISION_KEY`
- `PRECIOS_CLAROS_API_KEY` (vacío: se llama sin header; el default de base ya está en el código)

`BARATOYA_DATA_DIR` solo tendría sentido con un disco escribible. En Hobby no hay. No setearla.

## SQLite en este host

La lista de espera y la lista de compras usan `data/lista_espera.sqlite` cuando el disco se puede escribir (la box).

En Vercel el código del proyecto es de solo lectura. La única ruta escribible es `/tmp`. El arranque prueba `data/` y, si falla, usa `/tmp/baratoya/lista_espera.sqlite`.

Eso implica, sin adornos:

- Cada instancia tiene su propio archivo.
- Se pierde al reciclar la instancia, al redeploy y al escalar a otra.
- Dos visitas seguidas pueden no ver la misma lista.
- La búsqueda no lee ni escribe esa base. Sigue funcionando.

No hay volumen gratis que lo arregle en este plan. No activar Vercel Blob ni Postgres para “solucionarlo”.

## Qué sigue gratis y apagado

- Buscar precios no cobra y no usa APIs pagas. `ENABLE_PAID_SCRAPERS` y `ENABLE_MLA` quedan en false.
- Mercado Pago no está cableado. No hay checkout.
- `/terminos`, `/privacidad` y `/aviso-precios` muestran el banner **BORRADOR — no publicar sin abogado**. Subir el sitio a `*.vercel.app` no es publicarlas como legales finales. No sacar el banner. No comprar dominio para “cerrarlas”.

## Pasos (Martin, desde su PC)

Hoy no existe `https://github.com/mtfrat/baratoya`. La cuenta de GitHub conectada es **mtfrat** (no `mfrat`). El git de esta carpeta en la box no tiene remote.

1. Copiar esta carpeta a la PC, sin `data/*.sqlite` y sin `__pycache__`.
2. Crear un repo vacío **público** `mtfrat/baratoya` (sin README de GitHub, para no pisar el primer push). No hace falta plan pago de GitHub.
3. En la carpeta:

```bash
git init
git add .
git status   # no debe aparecer lista_espera.sqlite ni .env
git commit -m "Prepare BaratoYa for Vercel Hobby"
git branch -M master
git remote add origin git@github.com:mtfrat/baratoya.git
git push -u origin master
```

Si esta copia ya trae el `.git` de la box, no hace falta `git init`: solo el remote y el push. Revisar `git status` antes.

4. En Vercel, team **mfrat's projects** (el de `punav2`, no un team nuevo):
   - Add New → Project → Import `mtfrat/baratoya`.
   - Framework: FastAPI (preset de Python). Root directory: `.`
   - No custom domain.
   - No Storage (ni Blob, ni Postgres, ni KV).
   - Env: vacío, o solo los dos flags en `false`.
   - Deploy. El plan tiene que seguir siendo el que ya está. No pasar a Pro ni comprar créditos por este proyecto.
5. Probar, reemplazando el host que asigne Vercel (suele ser `https://baratoya.vercel.app` o `https://baratoya-<team>.vercel.app`):

```bash
curl -sS -o /tmp/by.json -w "%{http_code}\n" "https://HOST/api/buscar?q=yerba"
```

Tiene que ser `200` y, en `data.productos`, algún `precioMin` o `precioMax` mayor a 0. La UI `/` es la misma app.

## Smoke local (box)

```bash
curl -sS -o /tmp/by.json -w "%{http_code}\n" "http://127.0.0.1:8011/api/buscar?q=yerba"
```

El proceso de la box es `uvicorn baratoya.app:app` en el puerto 8011, cwd `/workspace/micro-saas`. No se reinició para este prepare.
