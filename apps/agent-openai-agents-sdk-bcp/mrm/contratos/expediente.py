"""Contrato de entrada: la solicitud de validación (expediente) y el modelo del inventario.

Todo lo que varía de un caso a otro (celdas, funciones, tablas, archivos) vive aquí, como dato.
El tier y el tipo de modelo NO vienen en la solicitud: se leen del inventario (Anexo D.2).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_REF_CELDA = re.compile(r"^\$?[A-Za-z]{1,3}\$?\d+(:\$?[A-Za-z]{1,3}\$?\d+)?$")


class ModeloInventario(BaseModel):
    """Registro del modelo en el inventario MRM. Es la única fuente del tier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    nombre: str
    tipo_modelo: str
    tier: int = Field(ge=1, le=4)
    atributos: dict[str, Any] = Field(default_factory=dict)
    responsable: str = ""


class ReferenciaExcel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hoja: str
    rango: str = Field(description="Celda (H13) o rango (I27:BZ27)")
    etiquetas: str | None = Field(default=None, description="Rango paralelo con etiquetas, p. ej. los periodos")

    @field_validator("rango", "etiquetas")
    @classmethod
    def _rango_valido(cls, valor: str | None) -> str | None:
        if valor is not None and not _REF_CELDA.match(valor):
            raise ValueError(f"Rango inválido: {valor!r}")
        return valor.replace("$", "").upper() if valor else valor

    def completa(self) -> str:
        return f"{self.hoja}!{self.rango}"


class EntradaCalculo(BaseModel):
    """Una entrada del cálculo: dónde está en la referencia y cómo se llama en la implementación."""

    model_config = ConfigDict(extra="forbid")

    nombre: str
    hoja: str
    celda: str
    argumento: str | None = Field(default=None, description="Nombre del argumento de la función; por defecto `nombre`")
    tipo: Literal["numero", "entero", "texto"] = "numero"
    paso: float | None = Field(default=None, description="Paso para probar fronteras de entradas continuas")

    @property
    def ref(self) -> str:
        return f"{self.hoja}!{self.celda.replace('$', '').upper()}"

    @property
    def nombre_argumento(self) -> str:
        return self.argumento or self.nombre


class FuncionImplementacion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    funcion: str = Field(description="paquete.modulo:funcion, relativo a la raíz del proyecto evaluado")
    salida: str | None = Field(default=None, description="Clave del dict devuelto; None si devuelve el valor directo")

    @field_validator("funcion")
    @classmethod
    def _formato(cls, valor: str) -> str:
        if ":" not in valor:
            raise ValueError("La función debe tener la forma modulo:funcion")
        return valor


class ToleranciaDeclarada(BaseModel):
    """Sobrescritura de tolerancia para un componente. Exige justificación y queda en el expediente (R11)."""

    model_config = ConfigDict(extra="forbid")

    absoluta: float = Field(ge=0)
    relativa: float = Field(default=0.0, ge=0)
    justificacion: str = Field(min_length=10)


class Componente(BaseModel):
    """Una pieza del cálculo que se compara: una celda o un rango de la referencia contra una salida del código."""

    model_config = ConfigDict(extra="forbid")

    id: str
    tipo: Literal["salida", "derivado"] = Field(
        description="salida: resultado principal del modelo; derivado: regla de negocio aplicada sobre una salida"
    )
    descripcion: str = ""
    referencia: ReferenciaExcel
    implementacion: FuncionImplementacion
    tolerancia: ToleranciaDeclarada | None = None


class TablaParametros(BaseModel):
    """Tabla de parámetros de la referencia y patrón de archivos candidatos en el proyecto (R4–R7)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    referencia: ReferenciaExcel
    orientacion: Literal["filas", "columnas"] = Field(
        description="filas: cada fila es una variable (nombre en la 1.ª columna, claves en la 1.ª fila); "
        "columnas: cada columna es una variable (nombres en la 1.ª fila)"
    )
    clave: str = Field(description="Nombre de la clave que indexa los registros (p. ej. periodo)")
    archivos: str = Field(description="Patrón glob relativo a la raíz del proyecto evaluado")
    clave_archivo: str | None = Field(default=None, description="Columna clave en los archivos, si difiere")


class ArtefactoReferencia(BaseModel):
    model_config = ConfigDict(extra="forbid")

    excel: str = Field(description="Ruta relativa al expediente")


class ArtefactoImplementacion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raiz: str = Field(description="Ruta relativa al expediente de la raíz del proyecto evaluado")
    lenguaje: Literal["python"] = "python"
    permitir_ejecucion: bool = Field(
        default=False, description="Autorización explícita para ejecutar el código evaluado en una copia aislada"
    )


class SolicitudValidacion(BaseModel):
    """El expediente que llega a validar. Es un archivo `expediente.yaml` dentro de su carpeta."""

    model_config = ConfigDict(extra="forbid")

    id: str
    modelo_id: str
    descripcion: str = ""
    dimensiones: list[str] = Field(
        default_factory=list,
        description="Dimensiones adicionales a las obligatorias por tier (ampliar cobertura queda registrado)",
    )
    referencia: ArtefactoReferencia
    implementacion: ArtefactoImplementacion
    entradas: list[EntradaCalculo]
    componentes: list[Componente]
    tablas_parametros: list[TablaParametros] = Field(default_factory=list)
