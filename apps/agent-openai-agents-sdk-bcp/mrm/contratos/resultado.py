"""Contrato de salida (framework F3 y `CONTEXTO_AGENTIZACION.md` §5.1).

Separa tres cosas que el AS-IS mezclaba (R9): si el componente aplica, si se ejecutó y qué se concluyó.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mrm.contratos.control import Severidad, TipoControl


class Aplicabilidad(str, Enum):
    APLICA = "APPLIES"
    NO_APLICA = "DOES_NOT_APPLY"


class EstadoEjecucion(str, Enum):
    COMPLETADA = "COMPLETED"
    ERROR = "ERROR"
    NO_EJECUTADA = "NOT_EXECUTED"


class VeredictoComponente(str, Enum):
    COINCIDE = "MATCH"
    DIVERGE = "DIVERGE"
    PARCIAL = "PARTIAL"
    NO_CONCLUYENTE = "INCONCLUSIVE"


class VeredictoControl(str, Enum):
    CUMPLE = "cumple"
    NO_CUMPLE = "no_cumple"
    NO_CONCLUYENTE = "no_concluyente"


class TipoEvidencia(str, Enum):
    CELDA = "celda"
    LINEA_CODIGO = "linea_codigo"
    ARCHIVO = "archivo"
    NOTA_CONOCIMIENTO = "nota_conocimiento"
    HECHO = "hecho"


class Evidencia(BaseModel):
    """Una pieza verificable. Los guardrails comprueban que `cita` existe literalmente en `fuente`."""

    model_config = ConfigDict(extra="forbid")

    tipo: TipoEvidencia
    fuente: str = Field(description="Ruta relativa al expediente, nombre de nota o componente")
    ubicacion: str = Field(description="Celda, número de línea, sección o variante")
    cita: str | None = Field(default=None, description="Texto literal que debe existir en la fuente")
    descripcion: str = ""
    valor: Any = Field(default=None, description="Dato numérico de detalle. Nunca se envía al LLM")


class ResultadoComponente(BaseModel):
    model_config = ConfigDict(extra="forbid")

    componente_id: str
    control_id: str
    estrategia: str
    variante: str | None = None
    aplicabilidad: Aplicabilidad = Aplicabilidad.APLICA
    estado_ejecucion: EstadoEjecucion
    veredicto: VeredictoComponente | None = None
    comparados: int = 0
    coincidencias: int = 0
    max_dif_abs: float | None = None
    tolerancia: dict[str, float] = Field(default_factory=dict)
    evidencia: list[Evidencia] = Field(default_factory=list)
    limitaciones: list[str] = Field(default_factory=list)
    detalle: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reglas_de_veredicto(self) -> "ResultadoComponente":
        if self.aplicabilidad is Aplicabilidad.NO_APLICA:
            if self.veredicto is not None:
                raise ValueError("Un componente que no aplica no tiene veredicto")
            return self
        if self.estado_ejecucion is not EstadoEjecucion.COMPLETADA and self.veredicto not in (
            None,
            VeredictoComponente.NO_CONCLUYENTE,
        ):
            raise ValueError("Un error técnico o una ejecución omitida nunca produce MATCH ni DIVERGE")
        if self.veredicto is VeredictoComponente.COINCIDE and self.comparados == 0:
            raise ValueError("La ausencia de evidencia nunca produce MATCH")
        return self


class Trazabilidad(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill: str
    version_skill: str
    catalogo: str
    version_catalogo: str
    version_control: str
    herramientas: dict[str, str] = Field(default_factory=dict)


class ResultadoControl(BaseModel):
    """Lo que el agente afirma sobre un control. El veredicto tiene tres valores, no dos."""

    model_config = ConfigDict(extra="forbid")

    control_id: str
    nombre: str
    tipo: TipoControl
    aplicabilidad: Aplicabilidad = Aplicabilidad.APLICA
    veredicto: VeredictoControl | None = None
    severidad: Severidad
    justificacion: str
    evidencia: list[Evidencia] = Field(default_factory=list)
    componentes: list[str] = Field(default_factory=list)
    limitaciones: list[str] = Field(default_factory=list)
    requiere_revision_humana: bool = False
    motivos_escalamiento: list[str] = Field(default_factory=list)
    trazabilidad: Trazabilidad | None = None

    @model_validator(mode="after")
    def _reglas(self) -> "ResultadoControl":
        if self.aplicabilidad is Aplicabilidad.APLICA and self.veredicto is None:
            raise ValueError(f"{self.control_id}: un control que aplica necesita veredicto")
        if self.aplicabilidad is Aplicabilidad.NO_APLICA and self.veredicto is not None:
            raise ValueError(f"{self.control_id}: un control que no aplica no tiene veredicto")
        if self.veredicto is VeredictoControl.CUMPLE and not self.evidencia:
            raise ValueError(f"{self.control_id}: la ausencia de evidencia nunca produce 'cumple'")
        return self

    @property
    def es_hallazgo(self) -> bool:
        return self.veredicto is VeredictoControl.NO_CUMPLE


ORDEN_GRAVEDAD = {
    VeredictoControl.CUMPLE: 0,
    VeredictoControl.NO_CONCLUYENTE: 1,
    VeredictoControl.NO_CUMPLE: 2,
}


def veredicto_integral(resultados: list[ResultadoControl]) -> VeredictoControl | None:
    """El veredicto integral nunca es mejor que el peor control aplicable."""
    aplicables = [r.veredicto for r in resultados if r.aplicabilidad is Aplicabilidad.APLICA and r.veredicto]
    if not aplicables:
        return None
    return max(aplicables, key=lambda v: ORDEN_GRAVEDAD[v])
