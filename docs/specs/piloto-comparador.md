# Spec · piloto vertical del comparador de implementación

> Modo arranque (framework G.3). Celda: **entorno tecnológico × {PD, pricing}**.
> Estado: implementado con datos sintéticos; pendiente de casos reales, Gate 3 (controles) y Gate 4 (umbrales).

## 1. Alcance

Verificar, para un expediente, que la implementación productiva en Python reproduce la referencia en Excel:
salidas principales, lógica con parámetros alineados, parámetros cargados, versión de parámetros, reglas
derivadas, fronteras de rango y buenas prácticas del código (juicio).

Fuera de alcance: SAS, Word, PDF, OCR, aprobación del modelo, registro en el inventario MRM.

## 2. Tabla de variación (diseñar desde dos casos, validar con un tercero)

| Eje | Caso A · curva PD | Caso B · pricing | ¿Código o configuración? |
|---|---|---|---|
| Forma de la salida | Escalar + series de 70 periodos | Escalares | Configuración (`componentes`) |
| Lógica de la referencia | `IF` anidados, logística, extensión lineal | `VLOOKUP`, potencias, `ROUND` | Código genérico (oráculo) |
| Tablas de parámetros | Ancha por filas (periodos en columnas) y por columnas | Por columnas con clave de texto | Configuración (`orientacion`, `clave`) |
| Archivos de parámetros | Dos versiones; la que coincide está comentada | Dos versiones; ninguna coincide del todo | Hecho medido (`analizar_parametros`) |
| Entradas | Numérica y entera | Texto, numérica y entera | Configuración (`entradas`) |
| Condiciones de rango | `plazo <= 19`, `plazo <= 25` | `plazo > 12` | Hecho medido (`generar_casos_frontera`) |
| Función productiva | `motor.curva:calcular_pd_temporal` | `pricing.cuota:calcular_cuota` | Configuración (`implementacion.funcion`) |

Tercer caso (C · scoring): forma algebraica distinta de la logística y tabla de coeficientes sin fórmulas. Se
resolvió sin tocar código, solo con su expediente.

## 3. Controles

La fuente de verdad son los catálogos `mrm/catalogos/implementacion_pd.yaml` e `implementacion_pricing.yaml`
(enunciados EARS, severidad, tier mínimo, referencia y regla). Resumen:

| Regla | Control PD | Tipo | Severidad | Tier mínimo |
|---|---|---|---|---|
| reproduccion_salida_principal | IMP-PD-001 | determinístico | Alta | 4 |
| equivalencia_logica | IMP-PD-002 | determinístico | Alta | 4 |
| precision_parametros | IMP-PD-003 | determinístico | Alta | 4 |
| version_parametros | IMP-PD-004 | determinístico | Media | 4 |
| reglas_derivadas | IMP-PD-005 | determinístico | Media | 3 |
| fronteras_rango | IMP-PD-006 | determinístico | Media | 2 |
| buenas_practicas_codigo | IMP-PD-007 | juicio | Baja | 1 |

Seis de siete controles son determinísticos (86 %), por encima de la meta del 70 % al 80 % del framework.

## 4. Contrato de salida

`mrm/contratos/resultado.py`: veredicto con tres valores (`cumple`, `no_cumple`, `no_concluyente`), aplicabilidad
separada, evidencia verificable (celda, línea de código, archivo, nota) y trazabilidad hasta la versión de skill,
catálogo, control y herramientas.

## 5. Terminado cuando

- [x] Los tres casos se procesan con el mismo código, cambiando solo el expediente.
- [x] El caso de regresión se reproduce automáticamente: 0/70, 70/70 y 10/70 (`tests/test_regresion_caso_controlado.py`).
- [x] El arnés corre sin intervención manual y reporta recall, precisión y fidelidad (`uv run mrm-evaluar`).
- [x] Una dimensión nueva se agrega sin modificar el chasis (`tests/test_orquestador.py`).
- [ ] Umbrales aprobados por quien responde por el agente (Gate 4).
- [ ] Veinte casos históricos etiquetados por dos validadores (golden dataset).
- [ ] Juez LLM evaluado con casos reales y set ciego.
