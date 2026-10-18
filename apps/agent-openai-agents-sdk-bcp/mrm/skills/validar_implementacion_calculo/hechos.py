"""Hechos que recoge el procedimiento antes de aplicar las reglas del catálogo.

Separar la recolección de hechos (herramientas) de la evaluación (reglas) es lo que permite que un mismo
procedimiento sirva a varios catálogos, y que un cambio de criterio no obligue a re-ejecutar código.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mrm.contratos.canonico import LibroCanonico
from mrm.contratos.expediente import Componente, SolicitudValidacion
from mrm.contratos.resultado import EstadoEjecucion

VARIANTE_ACTIVA = "activa"
VARIANTE_ALINEADA = "alineada"


@dataclass
class Serie:
    """Valores de un componente en la referencia y en la implementación, para una variante."""

    componente: Componente
    variante: str
    referencia: list[Any]
    etiquetas: list[Any] | None
    estado: EstadoEjecucion
    implementacion: list[Any] | None = None
    error: str | None = None


@dataclass
class CasoFronteraEjecutado:
    entrada: str
    operador: str
    umbral: float
    valor: float
    posicion: str
    referencia: dict[str, list[Any]] = field(default_factory=dict)
    implementacion: dict[str, list[Any]] = field(default_factory=dict)
    error: str | None = None


@dataclass
class Hechos:
    solicitud: SolicitudValidacion
    libro: LibroCanonico
    oraculo: Any
    indice: Any
    parametros: Any | None = None
    series: dict[tuple[str, str], Serie] = field(default_factory=dict)
    ejecuciones: dict[str, list[Any]] = field(default_factory=dict)
    variantes: list[str] = field(default_factory=list)
    fronteras: Any | None = None
    variante_fronteras: str | None = None
    casos_frontera: list[CasoFronteraEjecutado] = field(default_factory=list)
    limitaciones: list[str] = field(default_factory=list)
    llamadas_juez: int = 0

    @property
    def tiene_alineada(self) -> bool:
        return VARIANTE_ALINEADA in self.variantes

    def series_de(self, tipo: str, variante: str) -> list[Serie]:
        return [s for (_, v), s in self.series.items() if v == variante and s.componente.tipo == tipo]
