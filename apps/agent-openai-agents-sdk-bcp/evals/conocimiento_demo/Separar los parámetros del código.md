---
tipo: consejo
dominio: "[[Implementación de modelos]]"
temas: [buenas-practicas, parametros]
---

## Idea
Los coeficientes, umbrales y tablas de un modelo no se escriben como literales en el código: se cargan desde archivos de parámetros versionados. El código implementa la lógica; los parámetros son datos.

## Por qué funciona
Un parámetro escrito en el código solo se puede cambiar con un despliegue, y su historia queda mezclada con la del código. Separarlos permite recalibrar sin tocar la lógica y comparar la versión cargada contra la referencia metodológica.

## Cuándo usarlo
- Cuando una constante de negocio (factor, umbral, tasa) aparece como número dentro de una función.
- Cuando el mismo valor existe en el Excel de referencia y en el código.

## Relacionado
- Mapa: [[Mapa - Buenas prácticas de código de modelos]]
- [[Declarar la versión de parámetros en configuración]]
- [[Una sola fuente de verdad para cada regla de negocio]]
