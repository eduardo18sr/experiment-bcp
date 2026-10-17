# DELTA-001 · Revisión documental como segunda dimensión

> Rutas: **S** (skill `revisar-documentacion` 1.0.0) y **D** (herramienta `extraer_documento` 1.0.0).
> Cambios en `mrm/chasis/` y `mrm/contratos/`: **ninguno**.
> Estado: implementado con datos sintéticos; pendiente de Gate 3 (controles) y de casos reales.

## 1. Qué se agrega

| Artefacto | Ruta | Contenido |
|---|---|---|
| Herramienta | `mrm/herramientas/extraer_documento/` | Word (.docx) y Markdown a secciones canónicas con título, nivel, camino, párrafos y tablas. Reconoce estilos de título traducidos ("Título 1" guarda el nombre interno `heading 1`), niveles de esquema y basedOn |
| Skill | `mrm/skills/revisar_documentacion/` | Reglas `presencia_seccion`, `presencia_tabla` (determinísticas) y `suficiencia_contenido` (juicio) |
| Catálogos | `mrm/catalogos/documentacion_pd.yaml`, `documentacion_pricing.yaml` | Cuatro controles cada uno: tres determinísticos y uno de juicio |
| Conocimiento demo | `evals/conocimiento_demo/` | Mapa y dos notas de buenas prácticas de documentación |
| Datos sintéticos | `evals/sintetico/` | Un documento por caso: A en Word en español e incompleto, B en Markdown completo, C en Word en inglés completo |

Cambio aditivo en `mrm/juicio/`: `SolicitudJuicio.documento` y `VeredictoJuicio.citas_documento` (opcionales), y una
sección "Documentación evaluada" en el mensaje del juez solo cuando hay documento. El prompt de los controles de
código no cambia de contenido, pero sí su texto de instrucciones: antes de usar el juez real en producción hay que
re-correr las evaluaciones de IMP-*-007.

## 2. Corte C recursivo

El control del framework "el documento declara el perímetro de aplicación (segmento, producto, canal y vigencia)"
se partió en dos:

| Paso | Naturaleza | Control |
|---|---|---|
| ¿Existe una sección de perímetro con contenido? | Determinístico | DOC-*-001 |
| ¿Declara de forma explícita los cuatro elementos? | Juicio | DOC-*-002 |

Si la sección no existe, DOC-*-002 se resuelve como `no_cumple` sin llamar al LLM: no puede declarar lo que no tiene.

## 3. Tabla de variación

| Eje | Caso A | Caso B | Caso C | ¿Código o configuración? |
|---|---|---|---|---|
| Formato | Word | Markdown | Word | Código genérico (extractor) |
| Estilos de título | Español (`Ttulo1`) | `#` | Inglés (`Heading1`) | Código genérico |
| Nombre de la sección | "Perímetro de aplicación" | "Perímetro de aplicación" | "Ámbito de aplicación" | Configuración (`criterio.titulos`) |
| Tabla requerida | Variables | Segmentos | Diccionario de variables | Configuración (`criterio.columnas`) |

## 4. Pendientes que requieren ruta B

Se dejaron fuera a propósito para no tocar el chasis ni los contratos sin aprobación:

1. **Verificar citas de documentos en el guardrail del chasis.** Hoy la skill verifica cada cita del juez contra la
   sección extraída y anula el veredicto si no aparece literal. El chasis solo verifica que el archivo exista, porque
   `TipoEvidencia` no tiene un tipo `documento`. Propuesta: agregar `TipoEvidencia.DOCUMENTO` (fuente = archivo,
   ubicación = sección) y su verificación en `VerificadorEvidencia` reutilizando `extraer_documento`.
2. **Campo explícito en el expediente.** La skill busca los documentos en la carpeta `documentacion/` del expediente
   (parámetro `carpeta_documentos` de su configuración). Propuesta: campo `documentacion: [rutas]` en
   `SolicitudValidacion`, para que el expediente declare qué documentos son la referencia.
3. **Promover `DocumentoCanonico` a `mrm/contratos/`** cuando exista un segundo extractor (por ejemplo PDF con capa
   de texto), para que ambos produzcan la misma representación.

## 5. Fuera de alcance

PDF escaneado y OCR (herramienta aparte con confianza declarada), control de cambios y comentarios de Word, y la
numeración automática de títulos (`numbering.xml`): los títulos se leen sin el número automático.

## 6. Terminado cuando

- [x] `Registro().verificar_integridad()` sin defectos.
- [x] La suite completa pasa (95 tests) y el arnés cumple los umbrales.
- [x] Los casos sintéticos ya no reportan `documentacion` como hueco de cobertura.
- [x] Cero cambios en `mrm/chasis/` y `mrm/contratos/`.
- [ ] Controles aprobados en Gate 3 y casos reales etiquetados por dos validadores.
