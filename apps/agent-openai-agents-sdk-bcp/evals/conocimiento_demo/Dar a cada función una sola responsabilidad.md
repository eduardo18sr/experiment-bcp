---
tipo: consejo
dominio: "[[Implementación de modelos]]"
temas: [buenas-practicas, diseno]
---

## Idea
La función que calcula no lee archivos, y la que lee archivos no calcula. Separar la carga de parámetros del cálculo permite probar el cálculo con parámetros conocidos.

## Por qué funciona
Si el cálculo abre sus propios archivos, no se puede ejecutar con los parámetros de la referencia sin modificar el código. Con la carga separada, el validador inyecta la versión que quiere comparar.

## Relacionado
- Mapa: [[Mapa - Buenas prácticas de código de modelos]]
- [[Una sola fuente de verdad para cada regla de negocio]]
