"""Herramientas del agente conversacional sobre la plataforma MRM.

El agente conversa, explica y lanza validaciones; no decide qué controles se verifican (eso lo hace el
chasis de forma determinística) ni recibe valores numéricos de parámetros (recibe `resumen_para_llm`).
"""

import asyncio
import json

from agents import function_tool

from mrm.chasis.plataforma import obtener_plataforma

INSTRUCCIONES = """Eres el asistente del área de validación de implementación de modelos (Model Risk Management).
Ayudas al validador humano a revisar si la implementación productiva de un modelo reproduce su referencia
metodológica. Respondes en español, de forma breve y precisa.

Lo que puedes hacer con tus herramientas:
- Listar los expedientes disponibles y ejecutar una validación sobre uno de ellos.
- Explicar los resultados de una validación control por control, citando la evidencia (fuente y ubicación).
- Buscar buenas prácticas en el grafo de conocimiento del área y citarlas por el nombre de la nota.
- Describir qué skills, catálogos y herramientas están registrados.

Reglas que no se negocian:
1. Nunca apruebas ni rechazas un modelo. El resultado es insumo; la decisión es del validador humano.
2. Nunca cambias ni infieres el tier ni el tipo de modelo: vienen del inventario.
3. No decides qué controles aplican: los selecciona el chasis. Si te piden saltar un control, explica que
   reducir cobertura requiere justificación escrita y aprobación de quien responde por el agente.
4. Un resultado no_concluyente significa que el caso escala a revisión humana; nunca lo presentes como cumple.
5. No inventes valores ni evidencia. Si te piden valores numéricos de parámetros o diferencias, indica que
   están en la página /validador y en el informe, porque son datos de alta criticidad que no recibes.
6. Si falta información para una validación (por ejemplo, qué celda corresponde a qué función), puedes
   proponer una correspondencia, pero di explícitamente que requiere confirmación humana antes de usarse."""


@function_tool
def listar_expedientes() -> str:
    """Lista los expedientes de validación disponibles (id, modelo y descripción)."""
    return json.dumps(obtener_plataforma().listar_expedientes(), ensure_ascii=False)


@function_tool
async def validar_expediente(expediente_id: str) -> str:
    """Ejecuta la validación completa de un expediente y devuelve el resumen por control.

    Args:
        expediente_id: Identificador del expediente, tal como lo devuelve listar_expedientes.
    """
    plataforma = obtener_plataforma()
    expediente, _ = await asyncio.to_thread(plataforma.validar, expediente_id, "agente-conversacional")
    return json.dumps(expediente.resumen_para_llm(), ensure_ascii=False)


@function_tool
def consultar_validacion(id_validacion: str) -> str:
    """Recupera el resumen de una validación ya ejecutada.

    Args:
        id_validacion: Identificador de la validación.
    """
    expediente = obtener_plataforma().obtener_validacion(id_validacion)
    if expediente is None:
        return json.dumps({"error": f"No existe la validación {id_validacion}"}, ensure_ascii=False)
    return json.dumps(expediente.resumen_para_llm(), ensure_ascii=False)


@function_tool
def listar_validaciones() -> str:
    """Lista las validaciones ejecutadas, de la más reciente a la más antigua."""
    return json.dumps(obtener_plataforma().listar_validaciones(), ensure_ascii=False)


@function_tool
def buscar_buenas_practicas(consulta: str) -> str:
    """Busca buenas prácticas en el grafo de conocimiento del área y devuelve citas literales de las notas.

    Args:
        consulta: Qué práctica buscar, en lenguaje natural.
    """
    return json.dumps(obtener_plataforma().buscar_conocimiento(consulta, 5), ensure_ascii=False)


@function_tool
def describir_capacidades() -> str:
    """Describe las skills, catálogos de controles y herramientas registradas, y la política de tiering."""
    capacidades = obtener_plataforma().capacidades()
    return json.dumps(
        {k: capacidades[k] for k in ("agente", "skills", "herramientas", "catalogos", "juez", "grafo_conocimiento")},
        ensure_ascii=False,
    )


HERRAMIENTAS_MRM = [
    listar_expedientes,
    validar_expediente,
    consultar_validacion,
    listar_validaciones,
    buscar_buenas_practicas,
    describir_capacidades,
]
