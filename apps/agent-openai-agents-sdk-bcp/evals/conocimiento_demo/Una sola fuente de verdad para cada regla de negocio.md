---
tipo: consejo
dominio: "[[Implementación de modelos]]"
temas: [buenas-practicas, dry]
---

## Idea
Cada umbral, rango o constante de negocio se define en un solo lugar. Si el rango de plazos aparece escrito en dos funciones, tarde o temprano las dos copias divergen.

## Por qué funciona
La duplicación de conocimiento es el origen típico de diferencias en los límites de rango entre la referencia y la implementación, como un umbral menor o igual a 19 en un lado y un tramo de 19 a 24 en el otro.

## Relacionado
- Mapa: [[Mapa - Buenas prácticas de código de modelos]]
- [[Separar los parámetros del código]]
- [[Dar a cada función una sola responsabilidad]]
