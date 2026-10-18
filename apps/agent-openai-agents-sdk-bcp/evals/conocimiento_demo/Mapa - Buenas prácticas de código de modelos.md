---
tipo: mapa
dominio: "[[Implementación de modelos]]"
temas: [buenas-practicas, codigo]
---

## Descripción del tema
Bóveda de demostración con buenas prácticas para el código que implementa modelos de riesgo. Sirve para probar la ingesta y la consulta del grafo sin usar notas reales del área.

## Notas por subtema
- [[Separar los parámetros del código]]: los valores del modelo viven en archivos versionados, no en el código.
- [[Declarar la versión de parámetros en configuración]]: qué versión se carga se decide fuera del código.
- [[No dejar versiones alternativas comentadas]]: el código comentado esconde decisiones.
- [[Una sola fuente de verdad para cada regla de negocio]]: no duplicar umbrales ni constantes.
- [[Dar a cada función una sola responsabilidad]]: separar carga de datos y cálculo.
