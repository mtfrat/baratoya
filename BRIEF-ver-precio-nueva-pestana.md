# BaratoYa — “Ver precio” abre en pestaña nueva

Repo: `C:\Users\martin\Documents\baratoya` (master, deploy autorizado).

Problema: al hacer click en “Ver precio” (link a la tienda) el usuario sale de BaratoYa.

Fix: todos esos enlaces con `target="_blank"` y `rel="noopener noreferrer"`. Sin `window.location` same-tab. Súper + electro.

Commit + push master. Reportar SHA y archivos tocados.
