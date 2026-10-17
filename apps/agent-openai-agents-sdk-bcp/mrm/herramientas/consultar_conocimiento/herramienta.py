"""Herramienta `consultar_conocimiento`: recupera buenas prácticas del grafo de conocimiento.

Es probabilística (la relevancia es aproximada) y, por regla del framework (G.5), solo se usa en
controles de juicio, nunca para decidir un control determinístico. Las citas que devuelve son
literales para que el guardrail de fidelidad pueda verificarlas.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mrm.conocimiento.consulta import ConsultorGrafo, PracticaRecuperada
from mrm.contratos.herramienta import Herramienta, TipoHerramienta


class EntradaConsultar(BaseModel):
    consulta: str = Field(min_length=3)
    k: int = Field(default=5, ge=1, le=20)


class SalidaConsultar(BaseModel):
    practicas: list[PracticaRecuperada]


class ConsultarConocimiento(Herramienta[EntradaConsultar, SalidaConsultar]):
    nombre = "consultar_conocimiento"
    version = "1.0.0"
    tipo = TipoHerramienta.PROBABILISTICO
    errores = ("conocimiento_no_disponible",)
    Entrada = EntradaConsultar
    Salida = SalidaConsultar

    def __init__(self, consultor: ConsultorGrafo | None = None):
        self.consultor = consultor

    @classmethod
    def desde_dependencias(cls, dependencias: dict[str, Any]) -> "ConsultarConocimiento":
        return cls(dependencias.get("conocimiento"))

    def ejecutar(self, entrada: EntradaConsultar) -> SalidaConsultar:
        if self.consultor is None:
            raise self.fallar("conocimiento_no_disponible", "No hay grafo de conocimiento configurado")
        return SalidaConsultar(practicas=self.consultor.buscar(entrada.consulta, entrada.k))
