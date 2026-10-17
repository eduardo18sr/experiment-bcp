---
tipo: consejo
dominio: "[[Implementación de modelos]]"
temas: [buenas-practicas, versionamiento, parametros]
---

## Idea
El nombre o la versión del archivo de parámetros que se carga se declara en configuración versionada, no escrito dentro del código que hace el cálculo.

## Por qué funciona
Cuando la versión de parámetros está escrita en el código, cambiar de versión exige editar la lógica, y es fácil que producción cargue una versión distinta de la validada sin que nadie lo note. Con la versión en configuración, la decisión queda registrada y es auditable.

## Cuándo usarlo
- Cuando el código abre un archivo cuyo nombre incluye una fecha o una versión.
- Cuando existen varias versiones del mismo archivo de parámetros en el repositorio.

## Ejemplo
En lugar de abrir `theta_2024_v2.csv` dentro de la función de cálculo, la función recibe la ruta desde un archivo de configuración que también se versiona.

## Relacionado
- Mapa: [[Mapa - Buenas prácticas de código de modelos]]
- [[No dejar versiones alternativas comentadas]]
- [[Separar los parámetros del código]]
