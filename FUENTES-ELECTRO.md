# Fuentes electro y Mercado Libre

Verificado el 3 de octubre de 2026, alrededor de las 12:45–12:50 ART, desde este servidor. Query de electro: `heladera`. Sin scraper pago, sin cuenta nueva, sin proxy y sin rotar IP. Un precio solo entra en la tabla si el JSON lo trajo (`commertialOffer.Price`). No hay precios inventados.

Mercado Libre no se usa en `/api/electro`. La home, en modo Electro, dice «no disponible desde este servidor».

## Tabla

| Tienda | URL probada | HTTP | Muestra o bloqueo | ¿v1 gratis? |
| --- | --- | --- | --- | --- |
| Mercado Libre API search | `https://api.mercadolibre.com/sites/MLA/search?q=heladera` | 403 | `{"message":"forbidden","error":"forbidden","status":403}` | No |
| Mercado Libre listado | `https://listado.mercadolibre.com.ar/heladera` | 302 | Redirige a `https://www.mercadolibre.com.ar/gz/account-verification?go=...`. El cuerpo del 302 no trae precio. Header `x-is-search-bot: true`. | No |
| Mercado Libre listado (siguiendo el redirect, 2 saltos) | el mismo listado | 200 final | HTML de `suspicious-traffic-frontend` / verificación de cuenta (~41 KB). No hay precio, ni `andes-money`, ni ficha de producto. | No |
| Mercado Libre sitio | `https://api.mercadolibre.com/sites/MLA` | 403 | PolicyAgent, sin precio | No |
| Mercado Libre highlights | `https://api.mercadolibre.com/highlights/MLA/category/MLA1574` | 401 | `unauthorized` / `unspecified_token`. Sin precio. | No |
| Mercado Libre categoría | `https://api.mercadolibre.com/categories/MLA1574` | 200 | Metadato: nombre «Hogar, Muebles y Jardín». Ninguna clave de precio. | No (no es un precio) |
| Mercado Libre ítems | `https://api.mercadolibre.com/items/` | 404 | Recurso inexistente. Sin id público obtenido por una vía libre, no se consultó un ítem suelto. | No |
| Fravega | `https://www.fravega.com/api/catalog_system/pub/products/search?ft=heladera&_from=0&_to=2` | 206 | Heladera Lacar 60mg · seller Hogar Store · Price **399999.0** · ListPrice 444444.0 · disponible | Sí |
| Tienda de Audio | `tiendadeaudio.com.ar`, `www.tiendadeaudio.com.ar`, `tiendadeaudio.com`, `tiendaaudio.com.ar` | DNS | Esos hosts no resuelven. No apareció un dominio oficial con ese nombre. No se usó Casa del Audio (`casadelaudio.com`): es otra cadena. | No |
| Cetrogar | `https://www.cetrogar.com.ar/api/catalog_system/pub/products/search?ft=heladera&_from=0&_to=2` | 206 | Heladera termoeléctrica Daewoo DAW33L 12/220V 33 lt con ruedas · seller Cetrogar · Price **252079.0** | Sí |
| Cetrogar (apex) | `https://www.cetrogar.com/...` misma ruta | TLS | `unable to get local issuer certificate`. El `.com.ar` sí respondió. | No hace falta: vale el `.com.ar` |
| Naldo | `https://www.naldo.com.ar/api/catalog_system/pub/products/search?ft=heladera` | 206 | Heladera Cava Vondom T8 8 Botellas Estantes De Madera · seller Naldo Lombardi SA Arg · Price **256999.0** | Sí |
| On City | `https://www.oncity.com/api/catalog_system/pub/products/search?ft=heladera` | 206 | Huevera Heladera Todos Los Modelos Samsung · seller Vstore · Price **16019.0** (el `ft` matchea accesorios, no solo heladeras) | Sí |
| Musimundo | `https://www.musimundo.com/` y la misma ruta VTEX | 200 | HTML «Sitio en mantenimiento». La ruta de catálogo devuelve esa misma página, no JSON. | No |
| Megatone | `https://www.megatone.net/` y la ruta VTEX | 403 | HTML «403 Forbidden». `www.megatone.com` es otro sitio (software), no la cadena. `megatone.com.ar` no resuelve. | No |

Home de Fravega, Naldo y On City: HTTP 200 (HTML de la tienda). Eso no es el catálogo.

## Mercado Libre, en el orden pedido

1. Página pública `listado.mercadolibre.com.ar/heladera`: no trae precio. Sin seguir redirects es 302 a verificación de cuenta. Siguiéndola, el HTML es la pantalla de tráfico sospechoso, sin monto.
2. Endpoints públicos que no son el search bloqueado: highlights 401; `sites/MLA` 403; `categories/MLA1574` 200 pero solo ficha de categoría, sin precio; `items/` 404. Ninguno respondió 200 con un precio real.
3. No se usó proxy pago, ni rotación de IP, ni cookie de sesión.

No hay adapter de Mercado Libre, ni detrás de un flag: la única vía HTML tampoco trae precio. `ENABLE_MLA` sigue en falso. `ENABLE_PAID_SCRAPERS` sigue en falso.

## Qué quedó en el código

`GET /api/electro?q=heladera` junta Fravega, Cetrogar, Naldo y On City (`baratoya/electro.py`). Cada tienda es `.../api/catalog_system/pub/products/search?ft=` con `_from=0` y `_to=4`. Solo entra un producto si el JSON trae `Price` numérico mayor a 0. Mercado Libre figura en `fuentes` con HTTP 403 y el aviso «no disponible desde este servidor», sin fila de producto. El modo Súper (`GET /api/buscar`) no cambia: sigue siendo Precios Claros.
