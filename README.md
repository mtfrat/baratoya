# BaratoYa

Comparador independiente de precios de supermercado y electrodomésticos en CABA (Precios Claros, Día, Carrefour, Mas Online, Fravega, Cetrogar, Naldo, On City).

Dominio de producción: [https://baratoya.app](https://baratoya.app) (y deploy en Vercel: `https://baratoya.vercel.app`).

## Ejecución local

```bash
uvicorn app:app --reload --port 8000
```

## Configuración de Supabase (Auth & Redirects)

Para el correcto funcionamiento del login, registro y recuperación de contraseñas:

1. **Site URL:**
   En el panel de Supabase (**Authentication -> URL Configuration**):
   - **Site URL:** `https://baratoya.app`

2. **Redirect URLs (Allow list):**
   Agregar las siguientes URLs a la lista permitida:
   - `https://baratoya.app/**`
   - `https://baratoya.app/?mp=vuelta`
   - `https://baratoya.vercel.app/**`
   - `http://localhost:8000/**`
   - `http://127.0.0.1:8000/**`

3. **Plantillas de Email en Español (Supabase Email Templates):**
   *(Configurar en el panel de Supabase: Authentication -> Email Templates)*:
   - **Confirm signup:**
     - Asunto: `Confirmá tu cuenta en BaratoYa`
     - Mensaje: `Hacé click acá para confirmar tu cuenta y activar tus 7 días de BaratoYa Plus gratis: {{ .ConfirmationURL }}`
   - **Reset Password:**
     - Asunto: `Recuperá tu contraseña en BaratoYa`
     - Mensaje: `Hacé click acá para elegir una contraseña nueva en BaratoYa: {{ .ConfirmationURL }}`

## Modelo de Cuentas y Planes

- **Público (Anónimo):** Landing marketing, cómo funciona, planes, FAQ, legales. Sin acceso a promos del día ni resultados de búsqueda (devuelve 401).
- **Nuevo usuario:** **7 días de BaratoYa Plus gratis (Trial)** con búsquedas sin tope y precios con promos bancarias.
- **Plan Free (post-trial):** 5 búsquedas al mes por cuenta.
- **BaratoYa Plus:** Búsquedas ilimitadas y alertas mediante Checkout Pro de Mercado Pago (`$1.990 ARS / mes`).
- **Contacto de soporte:** `baratoyaba@gmail.com`.
