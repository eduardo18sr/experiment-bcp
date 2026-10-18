# Cómo extender la plataforma sin tocar el chasis

Los tres ejes de crecimiento del framework (§1.3) son más casuísticas, más capacidades y más dimensiones.
Ninguno modifica `mrm/chasis/`. Todas las rutas de este documento son relativas a
`apps/agent-openai-agents-sdk-bcp/`.

## Ruta A · una casuística nueva (p. ej. implementación de modelos LGD)

Es el 90 % del trabajo. Solo se toca contenido.

1. Escribe el delta en `docs/specs/deltas/DELTA-0XX.md`: qué controles cambian, en EARS, con severidad,
   tier mínimo, referencia y la regla de la skill que los evalúa.
2. Crea `mrm/catalogos/implementacion_lgd.yaml` con `dimension: entorno_tecnologico` y `tipo_modelo: lgd`.
   Cada control usa una de las `reglas` que ofrece la skill (ver su `skill.yaml`).
3. Agrega la configuración en `mrm/skills/validar_implementacion_calculo/skill.yaml`:
   ```yaml
   aplica_a:
     tipo_modelo: [pd, pricing, lgd]
   configuraciones:
     - {tipo_modelo: lgd, catalogo: implementacion_lgd, version_catalogo: 1.0.0}
   ```
4. Aporta casos etiquetados (el equipo, no el agente de codificación) y corre la suite completa:
   `uv run pytest` y `uv run mrm-evaluar`.
5. Archiva el delta en `docs/specs/archive/`.

Si el caso necesita una regla que la skill no ofrece, no es ruta A: es ruta S.

## Ruta D · una capacidad nueva (p. ej. comparador SAS ↔ Python, motor de calidad de datos)

Cuatro sesiones separadas (Anexo H.3). La separación es el control contra la hiperespecificación.

1. **Contrato.** `mrm/herramientas/<nombre>/contrato.yaml` con nombre, versión, tipo, entrada, salida, errores
   y propietario. Usa la representación canónica (`mrm/contratos/canonico.py`, `repositorio.py`); si no alcanza,
   extenderla es ruta B.
2. **Tests en rojo.** `mrm/herramientas/<nombre>/tests/` con dos casos genuinamente distintos y un test por
   cada error declarado.
3. **Implementación.** `herramienta.py` con una subclase de `Herramienta` cuyas `Entrada`, `Salida`, `errores`,
   `nombre`, `version` y `tipo` coinciden con el contrato. La herramienta devuelve hechos; no decide severidad.
4. **Registro y regresión.** Agrega la entrada en `mrm/registro/herramientas.yaml`. El chequeo de integridad del
   registro (`Registro().verificar_integridad()`, que corre en los tests y al arrancar la app) verifica que el
   contrato y la implementación coinciden.

**Una versión nueva del comparador** se agrega como otra entrada del registro (por ejemplo 1.1.0 o 2.0.0), sin
editar la anterior. Las skills que declaran `version_minima: 1.0.0` toman la 1.x más alta; una 2.0.0 exige que la
skill la pida explícitamente y que se corran sus evaluaciones.

## Ruta S · una dimensión nueva (p. ej. revisión documental en Word)

1. Spec del procedimiento: pasos, herramientas requeridas con versión mínima y reglas que ofrece.
2. `mrm/skills/<nombre>/skill.yaml` con `dimension: documentacion`, `aplica_a`, `herramientas_requeridas`,
   `reglas` y `configuraciones` por tipo de modelo.
3. `procedimiento.py` con una subclase de `Skill`. Pide herramientas con `contexto.herramienta("nombre")`;
   el chasis solo entrega las declaradas. Devuelve un `ResultadoControl` por cada control aplicable.
4. Catálogo en `mrm/catalogos/` y entrada en `mrm/registro/skills.yaml`.
5. Evaluaciones de todas sus configuraciones.

El orquestador ejecuta cada dimensión en paralelo con su propio contexto. La prueba
`tests/test_orquestador.py::test_nueva_dimension_sin_tocar_el_chasis` hace exactamente esto y verifica que el
chasis no cambió.

## Controles de juicio y el grafo de conocimiento

- Un control de juicio declara `tipo: juicio` y una regla que use el puerto del juez (`mrm/juicio/puerto.py`).
- El juez recibe contexto limpio: el enunciado EARS, la evidencia de código y las prácticas recuperadas.
- Toda cita del juez se verifica en código contra la fuente; si no existe literalmente, el control queda
  no concluyente y escala.
- Para cambiar la base de conocimiento no se toca código: se actualiza la bóveda en el Volume y se corre el job
  `mrm-ingestar-grafo-conocimiento`.

## Cuándo sí es ruta B

Cambiar el LLM del agente o del juez, agregar o mover un guardrail o un punto de HITL, cambiar un contrato de
`mrm/contratos/`, o cambiar el transporte de herramientas (por ejemplo publicarlas como funciones de UC o MCP).
Requiere spec aprobada (Gate 5) y rehacer la verificación completa.
