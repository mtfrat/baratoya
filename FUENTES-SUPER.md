# Fuentes súper (Coto y Chango Más)

Verificado el 3 de octubre de 2026, alrededor de las 12:48 ART, desde este servidor. Query: `yerba`. Mismo patrón VTEX: `/api/catalog_system/pub/products/search?ft=yerba`. Sin scraper pago.

| Tienda | URL probada | HTTP | Muestra o bloqueo | ¿v1 gratis con este patrón? |
| --- | --- | --- | --- | --- |
| Coto | `https://www.coto.com.ar/api/catalog_system/pub/products/search?ft=yerba` | 200 | HTML de la SPA «Coto Digital: Tu super a un click» (`<app-root>`), no JSON. Sin nombre de producto ni precio. | No |
| Coto | `https://www.cotodigital3.com.ar/api/catalog_system/pub/products/search?ft=yerba` | 200 | El mismo HTML de la SPA. | No |
| Coto | `https://www.cotodigital.com.ar/api/catalog_system/pub/products/search?ft=yerba` | 200 | El mismo HTML de la SPA. | No |
| Chango Más | `https://www.changomas.com.ar/api/catalog_system/pub/products/search?ft=yerba&_from=0&_to=1` | 301 y después 206 | 301 a `https://www.masonline.com.ar/api/catalog_system/pub/products/search?...`. Ahí el JSON trae Yerba Mate Taragui 500g · Price **3609.0** · link `https://www.masonline.com.ar/yerba-mate-taragui-4flex-sin-palo-500gr-2/p` | Sí, en Mas Online (destino del redirect de changomas.com.ar) |

El certificado de `*.changomas.com.ar` es GeoTrust (Dorinka SRL, válido hasta el 7 dic 2026). El almacén de CAs de este servidor no trae el intermedio (`cacerts.geotrust.com/GeoTrustTLSRSACAG1.crt`). Se armó el bundle con ese intermedio público y se verificó la cadena; no se desactivó la verificación TLS para saltar un bloqueo.

Coto no entra en v1. Scrapers pagos: apagados.

## Mas Online cableado

Releído el 3 de octubre de 2026, alrededor de las 20:45 ART, desde este servidor, antes de cablearlo. Sin scraper pago y sin proxy.

| Tienda | URL | HTTP | Precio real |
| --- | --- | --- | --- |
| Mas Online | `https://www.masonline.com.ar/api/catalog_system/pub/products/search?ft=yerba&_from=0&_to=4` | 206 | Yerba Mate Taragui 500g · `commertialOffer.Price` **3609.0** · disponible · `https://www.masonline.com.ar/yerba-mate-taragui-4flex-sin-palo-500gr-2/p` |

`changomas.com.ar` sigue siendo el host viejo: el pase de las 12:48 ART vio un 301 hacia `www.masonline.com.ar` y el mismo JSON. El código pega directo a Mas Online, que es el catálogo que respondió. No hace falta el bundle GeoTrust de `*.changomas.com.ar` para esta URL.

Cómo se busca, sin secretos: `GET {origin}/api/catalog_system/pub/products/search` con `ft` = el texto, `_from=0` y `_to=4`. `origin` es `https://www.masonline.com.ar`. Solo entra un producto si el JSON trae `items[0].sellers[0].commertialOffer.Price` numérico y mayor a 0. El nombre sale de `productName` y el link de `link`.

Quedó en `baratoya/super_cadenas.py` y se suma en `GET /api/buscar` (modo Súper). Cada ítem lleva `tienda: Mas Online` y en la home el badge «Mas Online (ex Chango Más) · catálogo público». Precios Claros no se toca: si responde, sus productos siguen; el snapshot local sigue siendo solo Precios Claros. Electro no mezcla esta cadena. Carrefour, Día, Jumbo, Disco y Vea no se re-probaron y no se agregaron.

Nota de la madrugada (no re-probada en este pase): Carrefour, Día, Jumbo, Disco y Vea habían dado 206 con precio. Hoy solo se rehicieron Coto y Chango Más, como se pidió.
