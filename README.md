# experiment-bcp · agente validador de implementación de modelos (MRM)

Piloto del framework de construcción de agentes del área de Model Risk Management, desplegado como
Databricks App. La primera herramienta es el **comparador de implementación**: verifica que el código
productivo (Python) reproduce la referencia metodológica (Excel) en lógica, parámetros y versiones.

- Arquitectura y decisiones: [`docs/arquitectura.md`](docs/arquitectura.md)
- Cómo agregar casuísticas, herramientas y dimensiones: [`docs/como-extender.md`](docs/como-extender.md)
- Spec del piloto: [`docs/specs/piloto-comparador.md`](docs/specs/piloto-comparador.md)
- Reglas para personas y agentes de codificación: [`AGENTS.md`](AGENTS.md)

## Qué hace

1. Recibe un **expediente**: el Excel de referencia, el proyecto Python y la correspondencia entre celdas y
   funciones. El tier y el tipo de modelo se leen del inventario.
2. El **chasis** decide de forma determinística qué skill y qué catálogo de controles aplican, filtra por tier
   y ejecuta cada dimensión en paralelo.
3. La skill de implementación usa herramientas con contrato: extrae el Excel, valida un oráculo de fórmulas
   contra la caché, indexa el repositorio, cruza el uso y la coincidencia de cada archivo de parámetros, ejecuta
   la función productiva en una copia aislada (activa y con parámetros alineados), compara series y prueba
   fronteras de rango. Un subagente juez evalúa buenas prácticas con el grafo de conocimiento.
   La skill de documentación lee el documento metodológico (Word o Markdown) del expediente y verifica secciones,
   tablas y, con el juez, que el contenido declare lo que exige el catálogo.
4. Los guardrails verifican cada cita contra su fuente; el HITL marca qué escala a revisión humana; se guarda un
   expediente auditable y un informe.

Interfaces: el chat del agente (`/`), la página **`/validador`** con el botón *Validar*, y la API `/mrm/api/*`.

## Probarlo en local

```bash
cd apps/agent-openai-agents-sdk-bcp
uv sync
uv run pytest
uv run mrm-evaluar
uv run python -m evals.sintetico.generador ./casos_demo
```

## Desplegarlo en Databricks

La app Git-backed `agent-openai-agents-sdk-bcp` toma el código de `apps/agent-openai-agents-sdk-bcp/`. Sin más
configuración arranca en **modo demo** con tres expedientes sintéticos. Para trabajar con Unity Catalog:

1. Crea el esquema y el Volume (por defecto `workspace.mrm.mrm`).
2. Sube la bóveda Obsidian de buenas prácticas a `/Volumes/workspace/mrm/mrm/conocimiento/boveda/` y corre el job
   `mrm-ingestar-grafo-conocimiento` (tablas Delta `kg_*` y `grafo.json`).
3. Sube los expedientes y el `inventario.yaml` a `/Volumes/workspace/mrm/mrm/expedientes/` (o corre el job
   `mrm-publicar-casos-sinteticos`).
4. Agrega el Volume como recurso de la app y descomenta las variables `MRM_*` en `app.yaml`.

Los jobs se despliegan con el bundle (`databricks bundle deploy`), ver `databricks.yml`.
