"""Representación canónica de referencias a archivos dentro de un repositorio evaluado.

La producen los indexadores (hoy, Python) y la consumen las herramientas que cruzan uso y contenido.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EstadoReferencia(str, Enum):
    ACTIVO = "ACTIVO"
    COMENTADO = "COMENTADO"
    DINAMICO = "DINAMICO"


class ReferenciaArchivo(BaseModel):
    ruta: str = Field(description="Archivo fuente donde aparece la referencia")
    linea: int
    texto: str = Field(description="Línea literal del código fuente")
    objetivo: str = Field(description="Nombre del archivo referenciado, o patrón glob si es dinámico")
    estado: EstadoReferencia
