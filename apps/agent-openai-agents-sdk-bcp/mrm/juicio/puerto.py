"""Puerto del juez. La skill depende de esta interfaz, no del LLM concreto (inversión de dependencias).

El juez recibe solo lo que necesita para un control (contexto limpio): el enunciado EARS, la evidencia
de código y las prácticas recuperadas. Devuelve un veredicto con citas literales que el chasis verifica.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field


class FragmentoCodigo(BaseModel):
    ruta: str
    linea_inicio: int
    texto: str


class FragmentoDocumento(BaseModel):
    documento: str
    seccion: str
    texto: str


class PracticaContexto(BaseModel):
    nota: str
    seccion: str
    cita: str


class SolicitudJuicio(BaseModel):
    control_id: str
    enunciado_ears: str
    evidencia_requerida: str
    rubrica: str = ""
    codigo: list[FragmentoCodigo] = Field(default_factory=list)
    documento: list[FragmentoDocumento] = Field(default_factory=list)
    practicas: list[PracticaContexto]


class CitaCodigo(BaseModel):
    ruta: str
    linea: int
    cita: str = Field(description="Texto literal de esa línea")


class CitaDocumento(BaseModel):
    documento: str
    seccion: str
    cita: str = Field(description="Texto literal de esa sección del documento")


class CitaPractica(BaseModel):
    nota: str
    cita: str = Field(description="Texto literal de la nota")


class VeredictoJuicio(BaseModel):
    veredicto: Literal["cumple", "no_cumple", "no_concluyente"]
    justificacion: str
    citas_codigo: list[CitaCodigo] = Field(default_factory=list)
    citas_documento: list[CitaDocumento] = Field(default_factory=list)
    citas_practicas: list[CitaPractica] = Field(default_factory=list)


class Juez(Protocol):
    nombre: str

    def juzgar(self, solicitud: SolicitudJuicio) -> VeredictoJuicio: ...


class JuezProgramado:
    """Juez de prueba con respuestas fijas por control. Sirve para tests y para el arnés sin LLM."""

    nombre = "juez-programado"

    def __init__(self, respuestas: dict[str, VeredictoJuicio]):
        self.respuestas = respuestas
        self.solicitudes: list[SolicitudJuicio] = []

    def juzgar(self, solicitud: SolicitudJuicio) -> VeredictoJuicio:
        self.solicitudes.append(solicitud)
        return self.respuestas.get(
            solicitud.control_id,
            VeredictoJuicio(veredicto="no_concluyente", justificacion="Sin respuesta programada para este control"),
        )
