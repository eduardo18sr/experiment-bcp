# Golden dataset · DIRECTORIO PROTEGIDO

Aquí van los expedientes históricos reales etiquetados por el área. Hoy está vacío a propósito.

Reglas (framework F4 y Anexo H.2):

- Nadie que construya el agente escribe en esta carpeta, y ningún agente de codificación la modifica.
- Dos validadores senior etiquetan cada caso por separado y sin verse. Las discrepancias se discuten y se
  resuelven; nunca se promedian. Si discrepan en más del 20 % de los casos, el problema es el control.
- Se divide en `desarrollo/` y `ciego/`. El set ciego se corre una sola vez por versión; si falla, esos casos
  quedan quemados.
- Los datos reales no salen del almacenamiento autorizado: aquí solo van punteros (rutas a Volumes de Unity
  Catalog) y las etiquetas, nunca los archivos de los modelos.

Formato de etiquetas: el mismo de `evals/desarrollo/etiquetas.yaml`.
