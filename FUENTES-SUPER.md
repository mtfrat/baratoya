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

Cómo se busca, sin secretos: `GET {origin}/api/catalog_system/pub/products/search` con `ft` = el texto (espacios como `%20`, nunca `+`), `_from=0` y `_to=4`. `origin` es el de cada cadena cableada. Solo entra un producto si el JSON trae `items[0].sellers[0].commertialOffer.Price` numérico y mayor a 0. El nombre sale de `productName` y el link de `link`.

Quedó en `baratoya/super_cadenas.py` y se suma en `GET /api/buscar` (modo Súper). Cada ítem lleva `tienda` con el nombre de la cadena. En la home, Mas Online usa el badge «Mas Online (ex Chango Más) · catálogo público»; Día y Carrefour usan «Día · catálogo público» y «Carrefour · catálogo público». Precios Claros no se toca: si responde, sus productos siguen; el snapshot local sigue siendo solo Precios Claros. Electro no mezcla estas cadenas. Coto y Mercado Libre no se agregaron. Jumbo, Disco y Vea no se re-probaron en este pase y no se agregaron.

Nota de la madrugada (el pase de las 12:48 ART no las re-probó): Jumbo, Disco y Vea habían dado 206 con precio. Coto sigue sin JSON.

## Día y Carrefour cableados

Releído el 3 de octubre de 2026, alrededor de las 21:46 ART, desde este servidor, antes de cablearlos. Sin scraper pago y sin proxy. El espacio en `ft` va como `%20`.

| Tienda | URL | HTTP | Precio real |
| --- | --- | --- | --- |
| Día | `https://diaonline.supermercadosdia.com.ar/api/catalog_system/pub/products/search?ft=yerba%20chamigo&_from=0&_to=4` | 200 | Yerba Mate Chamigo 500 Gr. · `commertialOffer.Price` **1950.0** · `https://diaonline.supermercadosdia.com.ar/yerba-mate-chamigo-500-gr-53413/p` |
| Día | `https://diaonline.supermercadosdia.com.ar/api/catalog_system/pub/products/search?ft=Yerba%20Mate%20Chamigo%20500%20Gr&_from=0&_to=4` | 206 | El mismo producto, Price **1950.0** |
| Carrefour | `https://www.carrefour.com.ar/api/catalog_system/pub/products/search?ft=yerba%20natura&_from=0&_to=4` | 206 | Yerba mate Natura 500 g. · `commertialOffer.Price` **1829.0** · `https://www.carrefour.com.ar/yerba-mate-natura-500-g-697155-697155/p` |
| Carrefour | `https://www.carrefour.com.ar/api/catalog_system/pub/products/search?ft=Yerba%20mate%20Natura%20500%20g&_from=0&_to=4` | 206 | El mismo producto, Price **1829.0** |

La etiqueta es `tienda: Día` y `tienda: Carrefour`. No se inventó ningún precio: si `Price` no es un número mayor a 0, el producto no entra.
