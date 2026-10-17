"""Juez sobre un endpoint de Model Serving de Databricks, con el OpenAI Agents SDK y salida estructurada."""

from __future__ import annotations

import json

from mrm.juicio.puerto import SolicitudJuicio, VeredictoJuicio

INSTRUCCIONES = """Eres un validador senior de implementación de modelos en un área de Model Risk Management.
Evalúas UN control a la vez con la evidencia que se te entrega y nada más.

Reglas que no se negocian:
1. Responde solo con el esquema pedido. El veredicto es cumple, no_cumple o no_concluyente.
2. Cada cita de código debe copiar literalmente texto de la línea indicada; cada cita de documento, texto de la
   sección indicada; cada cita de práctica, texto de la nota entregada. Una cita inventada invalida el veredicto.
3. Si la evidencia no basta para decidir, el veredicto es no_concluyente. Nunca adivines.
4. No apruebes ni rechaces el modelo: solo dictaminas este control.
5. La justificación es breve, en español, y no repite valores numéricos de parámetros."""


def _numerar(texto: str, inicio: int) -> str:
    """Prefija cada línea con su número para que el juez cite la línea exacta (sin copiar el prefijo)."""
    return "\n".join(f"{numero:>4} | {linea}" for numero, linea in enumerate(texto.splitlines(), start=inicio))


def _mensaje(solicitud: SolicitudJuicio) -> str:
    codigo = "\n\n".join(
        f"### {f.ruta}\nCada línea va precedida de su número y ' | '; en la cita copia solo el código.\n"
        f"```\n{_numerar(f.texto, f.linea_inicio)}\n```"
        for f in solicitud.codigo
    )
    documento = "\n\n".join(f"### {f.documento} — sección «{f.seccion}»\n{f.texto}" for f in solicitud.documento)
    practicas = "\n\n".join(f"### [[{p.nota}]] — {p.seccion}\n{p.cita}" for p in solicitud.practicas)
    partes = [
        f"## Control {solicitud.control_id}\n{solicitud.enunciado_ears}",
        f"Evidencia requerida: {solicitud.evidencia_requerida}",
        f"Rúbrica: {solicitud.rubrica or 'sin rúbrica adicional'}",
    ]
    if codigo:
        partes.append(f"## Código evaluado\n{codigo}")
    if documento:
        partes.append(f"## Documentación evaluada\n{documento}")
    partes.append(f"## Buenas prácticas del área\n{practicas}")
    return "\n\n".join(partes)


class JuezAgentesDatabricks:
    """Subagente juez con contexto limpio: solo recibe el control, la evidencia (código o documento) y las prácticas."""

    nombre = "juez-agentes-databricks"

    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.llamadas = 0

    def juzgar(self, solicitud: SolicitudJuicio) -> VeredictoJuicio:
        from agents import Agent, OpenAIChatCompletionsModel, Runner
        from databricks_openai import AsyncDatabricksOpenAI

        # Cliente propio por llamada: el juez corre en un hilo con su propio event loop, distinto del de la app.
        modelo = OpenAIChatCompletionsModel(model=self.endpoint, openai_client=AsyncDatabricksOpenAI())
        agente = Agent(
            name=f"juez-{solicitud.control_id}",
            instructions=INSTRUCCIONES,
            model=modelo,
            output_type=VeredictoJuicio,
        )
        self.llamadas += 1
        resultado = Runner.run_sync(agente, _mensaje(solicitud))
        salida = resultado.final_output
        if isinstance(salida, VeredictoJuicio):
            return salida
        return VeredictoJuicio.model_validate(json.loads(salida) if isinstance(salida, str) else salida)
