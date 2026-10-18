"""Contrato de control y de catálogo de controles (framework F0 y Anexo B)."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mrm.contratos.version import parsear


class Severidad(str, Enum):
    ALTA = "Alta"
    MEDIA = "Media"
    BAJA = "Baja"


class TipoControl(str, Enum):
    DETERMINISTICO = "deterministico"
    JUICIO = "juicio"


class Control(BaseModel):
    """La unidad atómica de verificación. El tier es metadato del control, no un eje del catálogo."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    version: str
    nombre: str
    enunciado_ears: str
    evidencia_requerida: str
    tipo: TipoControl
    tier_minimo: int = Field(ge=1, le=4, description="Aplica a los tiers 1..tier_minimo")
    profundidad: dict[str, str] = Field(default_factory=dict)
    severidad: Severidad
    referencia: str
    regla: str = Field(description="Regla de evaluación ofrecida por la skill que usa este catálogo")
    criterio: dict[str, Any] = Field(default_factory=dict, description="Umbrales y parámetros de negocio")

    @field_validator("version")
    @classmethod
    def _version_valida(cls, valor: str) -> str:
        parsear(valor)
        return valor

    @field_validator("enunciado_ears")
    @classmethod
    def _formato_ears(cls, valor: str) -> str:
        texto = " ".join(valor.split())
        if not texto.lower().startswith("cuando ") or "el sistema deberá" not in texto.lower():
            raise ValueError(
                "El enunciado debe seguir EARS: 'Cuando <condición observable>, el sistema deberá <comportamiento>'"
            )
        return texto

    def aplica_a_tier(self, tier: int) -> bool:
        """Filtro de tier en código, no en prompt (Anexo B.4): tier 1 es el más crítico."""
        return tier <= self.tier_minimo


class CatalogoControles(BaseModel):
    """Una casuística (dimensión × tipo de modelo) materializada como catálogo versionado."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    nombre: str
    version: str
    dimension: str
    tipo_modelo: str
    descripcion: str = ""
    criterios_comunes: dict[str, Any] = Field(default_factory=dict)
    controles: list[Control]

    @field_validator("version")
    @classmethod
    def _version_valida(cls, valor: str) -> str:
        parsear(valor)
        return valor

    @model_validator(mode="after")
    def _ids_unicos(self) -> "CatalogoControles":
        ids = [control.id for control in self.controles]
        repetidos = {i for i in ids if ids.count(i) > 1}
        if repetidos:
            raise ValueError(f"Controles repetidos en el catálogo {self.nombre}: {sorted(repetidos)}")
        return self

    def criterio(self, control: Control, clave: str, defecto: Any = None) -> Any:
        """Criterio del control, o el común del catálogo si el control no lo redefine."""
        if clave in control.criterio:
            return control.criterio[clave]
        return self.criterios_comunes.get(clave, defecto)
