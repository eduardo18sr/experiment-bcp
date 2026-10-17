---
tipo: consejo
dominio: "[[Implementación de modelos]]"
temas: [buenas-practicas, versionamiento]
---

## Idea
No se dejan en el código líneas comentadas que cargan otra versión de parámetros o una lógica alternativa. El control de versiones ya guarda la historia.

## Por qué funciona
Una línea comentada que apunta a otra versión de parámetros indica que hubo una decisión sobre qué versión usar, pero no dice cuál es la vigente ni por qué. Para quien valida, es una señal de riesgo de versión.

## Cuándo usarlo
- Cuando aparece un comentario con el nombre de otro archivo de parámetros junto a la línea activa.

## Relacionado
- Mapa: [[Mapa - Buenas prácticas de código de modelos]]
- [[Declarar la versión de parámetros en configuración]]
