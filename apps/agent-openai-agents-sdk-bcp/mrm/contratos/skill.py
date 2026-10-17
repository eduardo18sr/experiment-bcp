"""Contrato de skill (Anexo D): el procedimiento, separado del contenido (el catálogo).

Una skill declara qué herramientas necesita; nunca las importa. El chasis resuelve la dependencia
contra el registro y se la inyecta a través del contexto.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field

from mrm.contratos.control import CatalogoControles, Control
from mrm.contratos.expediente import ModeloInventario, SolicitudValidacion
from mrm.contratos.resultado import ResultadoComponente, ResultadoControl


class DependenciaHerramienta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: str
    version_minima: str


class PredicadoAplicabilidad(BaseModel):
    """Predicados de la tabla de ruteo. `*` es comodín y pierde frente a una coincidencia exacta."""

    model_config = ConfigDict(extra="forbid")

    tipo_modelo: list[str]
    atributos: dict[str, Any] = Field(default_factory=dict)


class ConfiguracionSkill(BaseModel):
    """Configuración de la skill para un tipo de modelo: qué catálogo aplica y con qué parámetros."""

    model_config = ConfigDict(extra="forbid")

    tipo_modelo: str
    catalogo: str
    version_catalogo: str
    parametros: dict[str, Any] = Field(default_factory=dict)


class SkillSpec(BaseModel):
    """Lo que declara `skill.yaml`."""

    model_config = ConfigDict(extra="forbid")

    nombre: str
    version: str
    dimension: str
    descripcion: str
    aplica_a: PredicadoAplicabilidad
    procedimiento: list[str]
    herramientas_requeridas: list[DependenciaHerramienta]
    reglas: list[str] = Field(description="Reglas de evaluación que los controles del catálogo pueden usar")
    usa_juez: bool = False
    configuraciones: list[ConfiguracionSkill]

    def configuracion_para(self, tipo_modelo: str) -> ConfiguracionSkill | None:
        exactas = [c for c in self.configuraciones if c.tipo_modelo == tipo_modelo]
        if exactas:
            return exactas[0]
        comodines = [c for c in self.configuraciones if c.tipo_modelo == "*"]
        return comodines[0] if comodines else None


class ContextoSkill(Protocol):
    """Lo que el chasis ofrece a una skill. La skill no conoce el chasis: solo esta interfaz."""

    solicitud: SolicitudValidacion
    modelo: ModeloInventario
    catalogo: CatalogoControles
    controles: list[Control]
    configuracion: ConfiguracionSkill
    juez: Any

    def herramienta(self, nombre: str) -> Callable[[Any], Any]: ...

    def ruta(self, relativa: str) -> Path: ...

    def version_herramienta(self, nombre: str) -> str: ...


class ResultadoSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resultados_control: list[ResultadoControl]
    resultados_componentes: list[ResultadoComponente] = Field(default_factory=list)
    limitaciones: list[str] = Field(default_factory=list)
    hechos: dict[str, Any] = Field(default_factory=dict, description="Resumen de hechos de la corrida")


class Skill(ABC):
    """Implementación de un procedimiento. Su `skill.yaml` es la fuente de verdad de lo que declara."""

    nombre: ClassVar[str]

    @abstractmethod
    def ejecutar(self, contexto: ContextoSkill) -> ResultadoSkill:
        raise NotImplementedError
