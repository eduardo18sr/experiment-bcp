"""Expediente auditable: todo lo necesario para responder "¿por qué se concluyó esto?" y "¿por qué no se evaluó aquello?"."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mrm.chasis.contexto import InvocacionHerramienta
from mrm.chasis.politica import ControlExcluido
from mrm.contratos.expediente import ModeloInventario
from mrm.contratos.resultado import ResultadoComponente, ResultadoControl, VeredictoControl


class HuecoCobertura(BaseModel):
    dimension: str
    motivo: str


class ResultadoDimension(BaseModel):
    dimension: str
    resolucion: dict[str, Any]
    resultados_control: list[ResultadoControl] = Field(default_factory=list)
    resultados_componentes: list[ResultadoComponente] = Field(default_factory=list)
    controles_excluidos: list[ControlExcluido] = Field(default_factory=list)
    hechos: dict[str, Any] = Field(default_factory=dict)
    limitaciones: list[str] = Field(default_factory=list)
    error: str | None = None


class ExpedienteAuditable(BaseModel):
    id_validacion: str
    expediente_id: str
    fecha_utc: str
    solicitante: str
    agente: dict[str, Any]
    modelo: ModeloInventario
    politica_tiering: str
    etapa_autonomia: str
    dimensiones_obligatorias: list[str]
    ampliaciones_cobertura: list[str] = Field(default_factory=list)
    huecos_cobertura: list[HuecoCobertura] = Field(default_factory=list)
    dimensiones: list[ResultadoDimension] = Field(default_factory=list)
    invocaciones: list[InvocacionHerramienta] = Field(default_factory=list)
    huellas_entradas: dict[str, str] = Field(default_factory=dict)
    solicitud: dict[str, Any] = Field(default_factory=dict, description="Configuración efectiva del expediente")
    veredicto_integral: VeredictoControl | None = None
    requiere_revision_humana: bool = True
    motivos_revision: list[str] = Field(default_factory=list)
    duracion_s: float = 0.0
    llamadas_llm: int = 0
    aviso: str = (
        "Resultado preliminar generado por un agente. Es insumo para el validador humano de segunda línea, "
        "que es quien decide. No constituye aprobación ni rechazo del modelo."
    )

    def resultados(self) -> list[ResultadoControl]:
        return [r for d in self.dimensiones for r in d.resultados_control]

    def conteos(self) -> dict[str, int]:
        conteo = {"cumple": 0, "no_cumple": 0, "no_concluyente": 0, "no_aplica": 0, "excluidos_por_tier": 0}
        for resultado in self.resultados():
            conteo[resultado.veredicto.value if resultado.veredicto else "no_aplica"] += 1
        conteo["excluidos_por_tier"] = sum(len(d.controles_excluidos) for d in self.dimensiones)
        return conteo

    def resumen_para_llm(self) -> dict[str, Any]:
        """Lo que puede ver el agente conversacional: estados, conteos y ubicaciones. Nunca valores numéricos."""
        return {
            "id_validacion": self.id_validacion,
            "expediente": self.expediente_id,
            "modelo": {"id": self.modelo.id, "tipo_modelo": self.modelo.tipo_modelo, "tier": self.modelo.tier},
            "veredicto_integral": self.veredicto_integral.value if self.veredicto_integral else None,
            "requiere_revision_humana": self.requiere_revision_humana,
            "conteos": self.conteos(),
            "huecos_cobertura": [h.model_dump() for h in self.huecos_cobertura],
            "controles": [
                {
                    "control_id": r.control_id,
                    "nombre": r.nombre,
                    "tipo": r.tipo.value,
                    "aplicabilidad": r.aplicabilidad.value,
                    "veredicto": r.veredicto.value if r.veredicto else None,
                    "severidad": r.severidad.value,
                    "justificacion": r.justificacion,
                    "evidencia": [
                        {"tipo": e.tipo.value, "fuente": e.fuente, "ubicacion": e.ubicacion, "descripcion": e.descripcion}
                        for e in r.evidencia
                    ],
                    "requiere_revision_humana": r.requiere_revision_humana,
                    "motivos_escalamiento": r.motivos_escalamiento,
                }
                for r in self.resultados()
            ],
            "controles_excluidos_por_tier": [c.model_dump() for d in self.dimensiones for c in d.controles_excluidos],
            "aviso": self.aviso,
        }
