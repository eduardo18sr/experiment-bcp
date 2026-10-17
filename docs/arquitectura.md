# Arquitectura del agente validador de implementación (piloto)

> Documento de diseño. Aplica el *Framework de construcción de agentes MRM* (v3) a un primer agente sobre Databricks, con el comparador de implementación como primera herramienta.
> Estado: **piloto vertical** (modo arranque, Anexo G.3). Nada de lo que hay aquí está aprobado por Gate 0 ni Gate 5.

---

## 1. Qué se construye y qué no

**Se construye:**

- El **chasis** del framework: registro de herramientas, skills y catálogos; resolutor determinístico de skills; selector de tier; orquestador por dimensión; motor de hallazgos; guardrails de salida; human-in-the-loop (HITL); expediente auditable e informe.
- La **capa de herramientas** del comparador, cada una con contrato, versión y tests: `extraer_excel`, `evaluar_formulas` (oráculo), `indexar_repositorio`, `analizar_parametros`, `ejecutar_funcion`, `comparar_series`, `generar_casos_frontera` y `consultar_conocimiento`, más `extraer_documento` (Word y Markdown) para la revisión documental.
- Dos **skills**, cada una con dos **catálogos de controles** (PD y pricing): `validar-implementacion-calculo` (dimensión *entorno tecnológico*) y `revisar-documentacion` (dimensión *documentación*, agregada por la ruta S sin tocar el chasis; ver `docs/specs/deltas/DELTA-001-revision-documental.md`).
- Un **grafo de conocimiento** de buenas prácticas (bóveda Obsidian → Delta + `grafo.json` + Vector Search opcional) consultado con recuperación híbrida tipo GraphRAG.
- La integración con la **Databricks App** (OpenAI Agents SDK + MLflow AgentServer): herramientas del agente conversacional, API REST y una página `/validador` con el botón *Validar*.
- Un **arnés de evaluación** con tres casos sintéticos etiquetados.

**No se construye (fuera de alcance del piloto):**

- Canonicalización estructural de Python (pasar una función Python al mismo árbol que una fórmula Excel). La equivalencia la decide la **ejecución**, no la comparación de árboles (requisito R8).
- Extractores de SAS, Word, PDF y OCR.
- Skills de calidad de datos y certificación. Hoy el resolutor las reporta como **hueco de cobertura** en lugar de omitirlas en silencio.
- Aprobación de modelos. El sistema nunca emite una aprobación final: entrega insumo para el validador humano.

---

## 2. Drivers arquitectónicos

| Driver | Contenido | Fuente |
|---|---|---|
| Requisito funcional significativo | Verificar que la implementación productiva (Python) reproduce la referencia metodológica (Excel): lógica, parámetros y versiones | `CONTEXTO_AGENTIZACION.md` §3 |
| Atributo de calidad: extensibilidad | Agregar una casuística, una herramienta o una dimensión **sin tocar el chasis** | Framework §1.3 (tres ejes de crecimiento) |
| Atributo de calidad: auditabilidad | Cada hallazgo rastreable a su evidencia (celda, línea, archivo) y a la versión de skill, catálogo, control y herramienta que lo generó | Framework F5, Anexo D.2 |
| Atributo de calidad: reproducibilidad | Hashes SHA-256 de entradas, configuración efectiva y parches registrados por corrida | `CONTEXTO_AGENTIZACION.md` §5.2 |
| Atributo de calidad: seguridad de datos | No enviar valores numéricos al LLM; secretos solo por variables de entorno; nunca modificar el proyecto evaluado | `CONTEXTO_AGENTIZACION.md` §7 |
| Restricción | Todo nativo en Databricks: Apps, Unity Catalog (Volumes, Delta), Model Serving, Vector Search, MLflow, Jobs | Decisión del área |
| Restricción | Plantilla `agent-openai-agents-sdk` ya desplegada como app Git-backed | Estado del repositorio |
| Concern | "Un comparador ajustado para un caso deja de funcionar con el siguiente" | Lecciones R1–R12 |

**Escenario de extensibilidad (medible).** *Fuente:* el equipo. *Estímulo:* llega una casuística nueva (p. ej. LGD). *Artefacto:* catálogos y configuración. *Respuesta:* se agrega un catálogo y una entrada en la configuración de la skill. *Medida:* **cero archivos modificados bajo `mrm/chasis/`**, y la suite completa verde.

---

## 3. Vista de capas

Las cuatro capas del framework (§1.3) se materializan como directorios con ritmos de cambio distintos:

```
apps/agent-openai-agents-sdk-bcp/
├── mrm/
│   ├── contratos/        Esquemas: control, skill, herramienta, expediente, resultado, representación canónica
│   ├── chasis/           PROTEGIDO · infraestructura de ejecución común a todos los agentes
│   ├── herramientas/     Capacidades con contrato (contrato.yaml + implementación + tests)
│   ├── skills/           Procedimientos de validación (skill.yaml + procedimiento + configs por tipo de modelo)
│   ├── catalogos/        Contenido: controles en EARS con severidad, tier mínimo y referencia
│   ├── registro/         Declaración legible por máquina: herramientas, skills, agentes
│   ├── constitucion/     Política de tiering (dimensiones obligatorias por tier)
│   ├── conocimiento/     Grafo de buenas prácticas: ingesta, modelo y consulta GraphRAG
│   ├── juicio/           Puerto del juez (subagente LLM) y sus adaptadores
│   └── api/              API REST y página /validador
├── agent_server/         Plantilla Databricks: agente conversacional (OpenAI Agents SDK)
├── evals/                Arnés, umbrales, casos de desarrollo sintéticos y golden (PROTEGIDO)
└── jobs/                 Jobs de Databricks: ingesta del grafo y corrida de evaluaciones
```

Regla de corte (framework F0, plano 2):

| Si es… | Va en… |
|---|---|
| Infraestructura de ejecución que no cambia entre agentes | `chasis/` |
| Capacidad con entrada y salida definidas que varias skills podrían usar | `herramientas/` |
| Procedimiento de validación | `skills/` |
| Criterio de negocio, umbral, severidad o referencia regulatoria | `catalogos/` |
| Datos del caso (qué celda corresponde a qué función, qué archivos) | El **expediente** (entrada), nunca el código |

### 3.1 Por qué todo vive dentro de la carpeta de la app

Una Databricks App despliega solo su `source_code_path`. Para que el piloto sea desplegable sin infraestructura adicional, la plataforma `mrm` vive dentro de la carpeta de la app. Cuando exista un segundo agente, `mrm` se extrae a un *wheel* publicado en un Volume de Unity Catalog, y las herramientas se exponen como funciones de UC o como servidor MCP. Ese cambio es una **ruta B** (cambia el transporte de herramientas), y el contrato de herramientas no se toca: MCP es transporte, no contrato (framework G.5).

---

## 4. Flujo de una validación

```
 Primera línea pulsa "Validar"  ─┐        (o el agente conversacional llama validar_expediente)
                                 ▼
 ┌────────────────────────── CHASIS (determinístico) ──────────────────────────┐
 │ 1. Carga el expediente y lee el TIER del inventario (nunca lo infiere)      │
 │ 2. Política de tiering → dimensiones obligatorias                           │
 │ 3. Resolutor: (dimensión, tipo_modelo, tier, atributos) → skill + catálogo  │
 │    · ninguna skill  → hallazgo de cobertura no disponible                   │
 │    · empate         → se detiene y escala                                   │
 │ 4. Selector de tier: controles aplicables / excluidos (con motivo)          │
 │ 5. Orquestador: una skill por dimensión, en paralelo, contexto limpio       │
 └──────────────────────────────────┬──────────────────────────────────────────┘
                                    ▼
 ┌──────────── SKILL validar-implementacion-calculo (procedimiento) ───────────┐
 │ extraer_excel → evaluar_formulas (oráculo validado contra caché)            │
 │ indexar_repositorio → analizar_parametros (uso × coincidencia)              │
 │ ejecutar_funcion (variante activa) → comparar_series                        │
 │ ejecutar_funcion (variante diagnóstica: parámetros alineados) → comparar    │
 │ generar_casos_frontera → oráculo vs implementación en cada frontera         │
 │ juez (subagente LLM) + consultar_conocimiento, solo en controles de juicio  │
 │ → hechos por componente → reglas del catálogo → veredicto por control       │
 └──────────────────────────────────┬──────────────────────────────────────────┘
                                    ▼
 ┌────────────────────────── CHASIS (gobierno) ────────────────────────────────┐
 │ Guardrails: esquema · evidencia verificable · no_concluyente escala         │
 │ HITL: severidad Alta, tier 1 y no_concluyente → revisión humana             │
 │ Veredicto integral (nunca mejor que el peor control aplicable)              │
 │ Expediente auditable (JSON) + informe (Markdown) → Volume de UC             │
 └─────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Tres niveles de resultado

1. **Hecho de herramienta** (`comparar_series`): comparados, coincidencias, diferencia máxima, rangos que coinciden. No sabe de controles ni de severidad.
2. **Resultado de componente** (skill): `aplicabilidad` × `estado_ejecucion` × `veredicto` (`MATCH`, `DIVERGE`, `PARTIAL`, `INCONCLUSIVE`). Son tres campos separados (R9).
3. **Resultado de control** (skill + catálogo): `cumple`, `no_cumple` o `no_concluyente`, con la severidad del catálogo, evidencia y trazabilidad.

Reglas del motor de hallazgos, verificadas en código y con tests:

- Un `ERROR` técnico nunca produce `MATCH` ni `DIVERGE`.
- La ausencia de evidencia nunca produce `cumple`.
- El veredicto integral no puede ser mejor que el peor control aplicable.

---

## 5. Decisiones de diseño

| # | Decisión | Por qué | Alternativa descartada |
|---|---|---|---|
| D1 | La selección de skill y catálogo es **determinística** (tabla de ruteo por especificidad) | Si fuera probabilística, un control podría no ejecutarse sin rastro (Anexo D.2) | Que el LLM elija qué verificar |
| D2 | **La herramienta devuelve hechos; la skill decide significado** | Cambiar un criterio de negocio no obliga a tocar herramientas probadas (§1.3) | Comparador que emite hallazgos con severidad |
| D3 | La skill **declara** herramientas con versión mínima; el chasis las **resuelve e inyecta** desde el registro, y rechaza las no declaradas | Inversión de dependencias: la skill depende del contrato, no de la clase concreta. Permite promover capacidades sin reescribirlas (Anexo C.2) | Imports directos entre skills y herramientas |
| D4 | Las fórmulas Excel se traducen a un **árbol canónico**; el oráculo evalúa ese árbol y **se valida contra los valores en caché** antes de usarse | R3: el AS-IS no soportaba `IF` y nunca validaba su evaluador | Evaluar el texto de la fórmula o confiar en `data_only` |
| D5 | **La evidencia ejecutable decide**. Las correspondencias celda ↔ función son datos del expediente; el LLM solo puede proponerlas para confirmación humana | R8: el LLM daba falsos negativos (`merge` frente a `VLOOKUP`, formas algebraicas de la logística) | Que el LLM dictamine la equivalencia |
| D6 | La ejecución productiva corre en una **copia verificada por SHA-256**, en subproceso aislado con timeout y solo con autorización explícita del expediente. La **variante diagnóstica** sustituye rutas de parámetros en la copia y deja un registro del parche | R2 y R4; reproduce automáticamente el caso controlado (0/70 frente a 70/70) | Ejecutar el repositorio original o parchearlo a mano |
| D7 | Varias **estrategias por caso**, combinadas por componente | R1: el AS-IS asumía una sola estrategia y quedaba `AMBIGUOUS` | Descubrimiento de "la" estrategia por puntaje |
| D8 | El **grafo de conocimiento** se usa solo en controles de **juicio**, y toda cita se verifica contra el texto de la nota | Un componente probabilístico en la ruta de evidencia necesita su propia métrica y cero alucinación (G.5) | RAG en la ruta de los controles determinísticos |
| D9 | Los guardrails son **código**, no prompt | "Un guardrail en el prompt es una sugerencia" (F5) | Instrucciones en el prompt del agente |
| D10 | El agente conversacional **nunca recibe valores numéricos** de parámetros; recibe conteos, estados y ubicaciones | Datos de alta criticidad (`CONTEXTO_AGENTIZACION.md` §7) | Enviar el detalle completo al LLM |
| D11 | Las variaciones del caso son **parámetros de configuración del expediente** (celdas, funciones, tablas, tolerancias con justificación), no código | "Lo que no varía es código; lo que varía es parámetro" (F2) | Adaptadores por modelo (`EADCurveAdapter`) |

---

## 6. Mapeo a Databricks

| Pieza | Servicio Databricks | Estado en el piloto |
|---|---|---|
| Agente conversacional y página `/validador` | Databricks Apps (FastAPI + MLflow AgentServer + OpenAI Agents SDK) | Implementado |
| LLM del agente y del juez | Model Serving (endpoint `databricks-claude-sonnet-5-5`) | Implementado; el juez se activa por variable de entorno |
| Expedientes de entrada y resultados | Unity Catalog Volumes (Files API) | Adaptador implementado, sin probar contra un workspace real |
| Inventario de modelos (tier) | Tabla Delta (hoy: `inventario.yaml` en el Volume) | Adaptador YAML implementado |
| Grafo de conocimiento | Tablas Delta `kg_nodos`, `kg_aristas`, `kg_fragmentos` + `grafo.json` en el Volume | Job implementado, sin probar en un workspace real |
| Recuperación semántica | Mosaic AI Vector Search (índice delta-sync sobre `kg_fragmentos`) | Opcional; sin índice se usa recuperación léxica BM25 |
| Trazas | MLflow Tracing (autolog del agente + spans por herramienta) | Implementado con degradación a no-op |
| Evaluaciones | Job de evaluación + MLflow (métricas por corrida) | Implementado |
| Gobierno del código | GitHub Actions: tests + rutas protegidas | Implementado |

---

## 7. Cómo crece

| Eje | Ruta | Qué se toca | Qué **no** se toca |
|---|---|---|---|
| Más casuísticas (LGD, EAD, scoring) | A | `mrm/catalogos/` y `configuraciones` de la skill | Chasis, herramientas |
| Más capacidades (comparador SAS, extractor Word, motor de calidad) | D | `mrm/herramientas/<nueva>/` + `mrm/registro/herramientas.yaml` | Chasis, skills existentes |
| Más dimensiones (documentación, calidad de datos) | S | `mrm/skills/<nueva>/` + `mrm/registro/skills.yaml` + catálogo | Chasis |
| Nueva versión del comparador | D | Nueva versión en el registro (semver). Las skills que piden `>=1.0` siguen funcionando; un cambio mayor obliga a migrarlas explícitamente | Chasis |

El paso a paso está en [`docs/como-extender.md`](como-extender.md). Una prueba de integración demuestra el criterio: registra una skill nueva en un registro temporal y el orquestador la ejecuta sin modificar el chasis.

---

## 8. Trazabilidad de requisitos R1–R12

| Req. | Cómo se cubre | Dónde |
|---|---|---|
| R1 | Varias estrategias por caso, combinadas por componente | `skills/validar_implementacion_calculo/procedimiento.py` |
| R2 | Ejecución real de la función productiva en una copia aislada | `herramientas/ejecutar_funcion` |
| R3 | Oráculo con `IF`, `VLOOKUP` y otras funciones; validado contra la caché antes de usarse | `herramientas/evaluar_formulas` |
| R4, R5 | Uso de cada archivo de parámetros (activo, comentado, dinámico, no referenciado) cruzado con su coincidencia | `herramientas/indexar_repositorio`, `herramientas/analizar_parametros` |
| R6, R7 | Comparación de tablas sin fórmulas y de tablas anchas (filas o columnas) | `herramientas/analizar_parametros` |
| R8 | La ejecución decide; el LLM no dictamina equivalencia | Decisión D5 |
| R9 | Aplicabilidad, ejecución y veredicto separados | `contratos/resultado.py` |
| R10 | Configuración y registros validados al arrancar (integridad del registro) | `chasis/registro.py` |
| R11 | Tolerancias del catálogo; sobrescritura por componente solo con justificación registrada | `contratos/expediente.py`, expediente auditable |
| R12 | Matriz de casos en las fronteras de las condiciones de rango | `herramientas/generar_casos_frontera` |
| Regresión | Versión activa 0/70, versión Excel 70/70, curva final 10/70 | `evals/` y `tests/test_regresion_caso_controlado.py` |

---

## 9. Limitaciones conocidas

- El juez LLM y la recuperación con Vector Search no tienen todavía un set de evaluación propio con casos reales; con datos sintéticos solo se verifica la mecánica (esquema, fidelidad de citas, escalamiento).
- La ejecución productiva corre dentro del contenedor de la app. Para producción conviene un adaptador que la ejecute como Job serverless aislado; el puerto `Ejecutor` ya lo permite.
- Las fronteras se generan solo para comparaciones entre una celda de entrada y una constante numérica.
- Las citas del juez dentro de documentos las verifica la skill documental; el guardrail del chasis solo comprueba que el archivo exista. Llevar esa verificación al chasis es una ruta B pendiente (DELTA-001).
- Los adaptadores de Unity Catalog (Volumes, Vector Search) y los jobs no se han probado contra un workspace real.
- Los umbrales de `evals/umbrales.yaml` son provisionales y esperan aprobación (Gate 4).
