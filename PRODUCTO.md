# BaratoYa — brief de producto

Honesto a octubre 2026. No hay usuarios, conversión ni tamaño de mercado medidos. Lo que dice “ya funciona” se puede verificar en este servidor: `GET /health`, `GET /api/buscar` (sin mail, sin tope) y la lista local (`GET /api/lista`).

## Nicho y para quién

Quien hace las compras del hogar en CABA y quiere el rango de precio de un producto de góndola antes de salir. No es una herramienta para cadenas, ni un comparador de Mercado Libre.

Fuente: `baratoya/app.py` consulta solo Precios Claros y fija la zona en CABA (−34.6037, −58.3816). `ENABLE_PAID_SCRAPERS` y `ENABLE_MLA` siguen en falso.

## Qué problema

No sabés cuánto sale un producto en los comercios de CABA hasta que estás en la góndola.

## Copy de la home

Textos que están en `templates/index.html`:

- Headline (único H1): «El precio del súper, antes de salir.»
- Sub: antes de salir, el mismo producto (marca, variante y tamaño) en Día, Carrefour, Mas Online y las otras cadenas con precio público, con el precio por kilo o por litro, y te quedás con el más barato.
- CTA principal: «Buscar un precio» (envía la búsqueda a `/api/buscar`, no pide mail).
- CTA secundario: «Ver la lista local» (no es un checkout).

## SEO

Implementado en la home, un solo H1:

- Title: `BaratoYa — el precio del súper en CABA, antes de salir`
- Meta description: la búsqueda es gratis y sin tope. La lista local no cobra ni manda mail.
- H1: `El precio del súper, antes de salir.`

No hay sitemap, nota de blog, ni dominio público. Otro proceso puede tunelar este servidor; esta app no publica a internet por sí sola.

## Precios de suscripción

**HIPÓTESIS.** No salen de entrevistas ni de ventas. Están en la home para discutirlos. $0 no es hipótesis: la búsqueda ya corre.

- Buscar: $0. Mínimo, máximo y sucursales en CABA. Sin cuenta y sin tope. No está detrás de la lista.
- Lista: $1.990 por mes. Hipótesis, no se puede contratar. En local ya se puede guardar una lista y marcar una baja; eso no cobra.
- Historial: $4.900 por mes. Varias listas, historial del mínimo y más avisos. No está construido y no se puede contratar.

No hay Mercado Pago ni Stripe, ni SDK ni claves. El botón del plan Lista abre la prueba local. La lista de espera sigue en la misma SQLite (`baratoya/data/lista_espera.sqlite`) vía `POST /api/lista-espera`. No hay cobro.

## Cómo se cobra después

Decisión de Martin, no implementada. No hay SDK ni claves.

- Mercado Pago encaja si el pagador está en Argentina (tarjeta o dinero en cuenta).
- Stripe encaja si más adelante el cobro es en dólares o fuera del país.

Hasta que eso se elija, no hay cobro. La lista de espera sigue siendo la puerta para «avisame cuando se pueda pagar». La lista de productos de abajo no reemplaza un checkout.

## Mercado

Precios Claros se consulta sin API paga (`PRECIOS_CLAROS_API_KEY` vacío por defecto; el código pega a `PRECIOS_CLAROS_BASE`, cloudfront `/prod`). El precio no es un dato exclusivo de BaratoYa: cualquiera puede ver el mismo mínimo y el mismo máximo.

Por eso el hueco pago no es «acceso a precios». Es la cuenta de verdad, el mail cuando baja y el historial. La lista y la marca de baja existen solo en local, sin cobro.

## Qué existe en local

Misma base que la lista de espera: `baratoya/data/lista_espera.sqlite`, tabla `lista_compra`.

Una fila es a la vez el ítem de la lista y la alerta: `email`, `product_key`, `precio` (el precio al guardar), `nombre`, `tienda`, `url`. `bajo` pasa a 1 solo si una relectura ve un precio menor. No hay contraseña: el mail es la clave. La UI lo dice. Quien escribe el mismo mail ve la misma lista.

- `POST /api/lista` — guarda un producto que ya salió en la búsqueda (`nombre`, `tienda`, `precio`, `url`, `product_key`, `fuente`). No gatea `GET /api/buscar`.
- `GET /api/lista?email=` — devuelve la lista. No relee precios.
- `GET /api/alertas?email=` — las mismas filas, sin releer y sin mandar mail.
- `POST /api/alertas/revisar` — body `{"email": "...", "product_key": "opcional"}`. Llama a `revisar_alertas` / `precio_vigente`, que vuelve a leer Precios Claros (mínimo) o el catálogo público VTEX ya cableado (Mas Online, Día, Carrefour, Fravega, Cetrogar, Naldo, On City) y marca la fila si el precio nuevo es menor.

Esa relectura es a pedido. No hay cron, no hay worker y no se envía mail.

## Qué sigue faltando

- Mercado Pago y Stripe. No hay checkout. $1.990 y $4.900 siguen siendo hipótesis, no un precio nuevo.
- Envío real de mail cuando `bajo` es 1. Hoy solo se marca la fila.
- Programar la relectura. Hay que pegarle al endpoint.
- Cuentas: contraseña, sesión, mail de confirmación. Esto no es un login.
- Historial (la serie de precios del plan de $4.900). No se guarda.
- Deploy. Esta app no se publica sola. Las páginas legales siguen en borrador (`legal-drafts-v1.md` y las rutas con cartel de borrador). No se inventó un CUIT.
- Scrapers pagos y Mercado Libre (siguen apagados).
- Selector de barrio o de ciudad: la zona de Precios Claros es CABA.
- Marca propia: la UI usa el sistema Wise de Refero Styles, no un design system de BaratoYa. URL: https://styles.refero.design/style/367c0c6e-73a7-441c-a8ff-91d139ac60dc
- SEO más allá de title, meta description y un H1.
- Prueba de que alguien pagaría $1.990 o $4.900.
