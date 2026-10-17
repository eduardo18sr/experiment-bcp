# AGENTS.md · reglas operativas del repositorio

Traducción a reglas verificables de la constitución del área (framework de agentes MRM, Anexo H.2).
Aplican a cualquier persona o agente de codificación que trabaje en este repositorio. Cada restricción
lleva su alternativa declarada.

## Qué hay aquí

- `apps/agent-openai-agents-sdk-bcp/` es la Databricks App (unidad de despliegue). Dentro:
  - `mrm/` es la plataforma: `contratos/`, `chasis/`, `herramientas/`, `skills/`, `catalogos/`, `registro/`,
    `constitucion/`, `conocimiento/`, `juicio/` y `api/`.
  - `agent_server/` es el agente conversacional (plantilla de Databricks + herramientas MRM).
  - `evals/` contiene el arnés, los umbrales, los casos sintéticos de desarrollo y el golden dataset.
  - `jobs/` contiene los jobs de Databricks (ingesta del grafo, evaluaciones, casos sintéticos).
- `docs/` contiene la arquitectura, la guía de extensión y las specs (`specs/deltas/`, `specs/archive/`).

## Rutas de cambio

Nombra la ruta antes de tocar nada. Si un cambio toca más de una capa, detente y consulta.

| Ruta | Qué se toca | Qué no se toca |
|---|---|---|
| A · catálogo | `mrm/catalogos/`, `docs/specs/` | chasis, herramientas, skills |
| D · herramienta | `mrm/herramientas/<nombre>/`, `mrm/registro/herramientas.yaml` | chasis, skills existentes |
| S · skill | `mrm/skills/<nombre>/`, `mrm/registro/skills.yaml`, su catálogo | chasis |
| B · chasis o modelo base | `mrm/chasis/`, `mrm/contratos/`, modelo del agente | solo con spec aprobada (Gate 5) |

## Reglas

1. No modifiques nada bajo `mrm/chasis/` ni `mrm/contratos/` sin una spec de ruta B aprobada.
   Si parece necesario, detente y repórtalo: probablemente la descomposición está mal hecha.
2. No modifiques nada bajo `apps/agent-openai-agents-sdk-bcp/evals/golden/`. El etiquetado es humano.
   Si falta un caso, pídelo al equipo.
3. No añadas parámetros a una herramienta sin actualizar antes su `contrato.yaml` y su versión.
   Si un parámetro solo lo usa una casuística, pertenece a la skill o al catálogo, no a la herramienta.
4. Toda herramienta nueva tiene `contrato.yaml` y tests con al menos dos casos genuinamente distintos
   antes de cualquier implementación. Una versión mayor no reemplaza a la anterior: se agrega al registro.
5. No pongas en el código nada específico de un modelo (celdas, nombres de funciones, archivos, EAD, CLV).
   Lo que varía entre casos es configuración del expediente.
6. Toda salida cumple el contrato de `mrm/contratos/resultado.py`, incluido el valor `no_concluyente`.
   La ausencia de evidencia nunca produce `cumple`; un error técnico nunca produce `MATCH` ni `DIVERGE`.
7. El modelo de lenguaje no decide qué controles aplican, no cambia el tier y no dictamina equivalencias:
   propone, y la evidencia ejecutable decide.
8. Nunca escribas en código, tests, logs ni prompts datos reales de modelos, credenciales, correos,
   rutas personales ni identificadores de workspace. Los tests usan datos sintéticos.
9. Cada cambio corre la suite completa (`uv run pytest` dentro de la app), no solo los tests nuevos.
   Si algo previamente verde se pone rojo, detente y repórtalo antes de arreglarlo.
10. No conviertas a la ligera un control de juicio en determinístico ni cambies severidades o umbrales:
    son criterio del área (Anexo H.4).

## Al cerrar una sesión

- [ ] ¿Se tocó algún directorio protegido? Si sí, la ruta elegida era la equivocada.
- [ ] ¿Cambió algún contrato sin declararlo ni versionarlo?
- [ ] ¿Corrió la suite completa y el arnés (`uv run mrm-evaluar`)?
- [ ] ¿Aparecieron parámetros de configuración que no estaban en la spec?
- [ ] ¿Se puede explicar el cambio en términos de una sola ruta?
