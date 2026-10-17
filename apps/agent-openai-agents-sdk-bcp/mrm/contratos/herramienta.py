"""Contrato de herramienta (Anexo C).

Una herramienta es una función con contrato declarado: mismo input, mismo output, sin decidir significado.
Cada herramienta vive en `mrm/herramientas/<nombre>/` con su `contrato.yaml`, su implementación y sus tests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class TipoHerramienta(str, Enum):
    DETERMINISTICO = "deterministico"
    PROBABILISTICO = "probabilistico"


class ContratoHerramienta(BaseModel):
    """Lo que declara `contrato.yaml`. El registro verifica que la implementación lo cumple."""

    model_config = ConfigDict(extra="forbid")

    nombre: str
    version: str
    tipo: TipoHerramienta
    descripcion: str
    entrada: dict[str, str] = Field(description="campo -> descripción")
    salida: dict[str, str] = Field(description="campo -> descripción")
    errores: list[str] = Field(default_factory=list)
    propietario: str
    tests: str = ""


class ErrorHerramienta(Exception):
    """Error declarado en el contrato. Un código no declarado es un defecto de la herramienta."""

    def __init__(self, codigo: str, mensaje: str):
        super().__init__(f"[{codigo}] {mensaje}")
        self.codigo = codigo
        self.mensaje = mensaje


E = TypeVar("E", bound=BaseModel)
S = TypeVar("S", bound=BaseModel)


class Herramienta(ABC, Generic[E, S]):
    """Clase base de toda herramienta. Las subclases declaran su contrato en atributos de clase."""

    nombre: ClassVar[str]
    version: ClassVar[str]
    tipo: ClassVar[TipoHerramienta]
    errores: ClassVar[tuple[str, ...]] = ()
    Entrada: ClassVar[type[BaseModel]]
    Salida: ClassVar[type[BaseModel]]

    @classmethod
    def desde_dependencias(cls, dependencias: dict[str, Any]) -> "Herramienta":
        """Fábrica usada por el chasis. Las herramientas con dependencias externas la redefinen."""
        return cls()

    def __call__(self, entrada: E) -> S:
        if not isinstance(entrada, self.Entrada):
            entrada = self.Entrada.model_validate(entrada)
        salida = self.ejecutar(entrada)  # type: ignore[arg-type]
        if not isinstance(salida, self.Salida):
            raise TypeError(f"{self.nombre} devolvió {type(salida).__name__}, se esperaba {self.Salida.__name__}")
        return salida

    @abstractmethod
    def ejecutar(self, entrada: E) -> S:
        raise NotImplementedError

    def fallar(self, codigo: str, mensaje: str) -> ErrorHerramienta:
        if codigo not in self.errores:
            raise ValueError(f"{self.nombre} intentó emitir un error no declarado en su contrato: {codigo}")
        return ErrorHerramienta(codigo, mensaje)
