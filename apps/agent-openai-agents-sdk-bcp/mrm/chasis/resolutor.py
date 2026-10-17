"""Resolutor de skills: una tabla de ruteo determinística, no una búsqueda semántica (Anexo D.2).

El modelo de lenguaje nunca decide qué se verifica. La clave sale del inventario y de la solicitud,
nunca del contenido de los documentos.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from mrm.chasis.registro import EntradaSkill, ErrorRegistro, Registro
from mrm.contratos.control import CatalogoControles
from mrm.contratos.skill import ConfiguracionSkill


class EstadoResolucion(str, Enum):
    RESUELTA = "RESUELTA"
    SIN_COBERTURA = "SIN_COBERTURA"
    EMPATE = "EMPATE"
    ERROR = "ERROR"


class ClaveResolucion(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: str
    tipo_modelo: str
    tier: int
    atributos: dict[str, Any] = {}


class Resolucion(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    clave: ClaveResolucion
    estado: EstadoResolucion
    motivo: str = ""
    skill: str | None = None
    version_skill: str | None = None
    catalogo: str | None = None
    version_catalogo: str | None = None
    entrada_skill: EntradaSkill | None = None
    configuracion: ConfiguracionSkill | None = None
    catalogo_controles: CatalogoControles | None = None

    def resumen(self) -> dict[str, Any]:
        return self.model_dump(include={"clave", "estado", "motivo", "skill", "version_skill", "catalogo", "version_catalogo"}, mode="json")


def _especificidad(entrada: EntradaSkill, clave: ClaveResolucion) -> int | None:
    aplica = entrada.spec.aplica_a
    if entrada.spec.dimension != clave.dimension:
        return None
    if clave.tipo_modelo in aplica.tipo_modelo:
        puntaje = 2
    elif "*" in aplica.tipo_modelo:
        puntaje = 1
    else:
        return None
    for atributo, valor in aplica.atributos.items():
        if clave.atributos.get(atributo) != valor:
            return None
        puntaje += 1
    return puntaje


def resolver(registro: Registro, clave: ClaveResolucion) -> Resolucion:
    candidatas = [(p, e) for e in registro.skills_activas() if (p := _especificidad(e, clave)) is not None]
    if not candidatas:
        return Resolucion(
            clave=clave,
            estado=EstadoResolucion.SIN_COBERTURA,
            motivo=f"Ninguna skill cubre {clave.dimension} × {clave.tipo_modelo}: la dimensión pasa a revisión manual completa",
        )
    mejor = max(p for p, _ in candidatas)
    ganadoras = [e for p, e in candidatas if p == mejor]
    if len(ganadoras) > 1:
        return Resolucion(
            clave=clave,
            estado=EstadoResolucion.EMPATE,
            motivo=f"Empate entre {[e.spec.nombre for e in ganadoras]}: defecto del registro, se detiene y escala",
        )
    entrada = ganadoras[0]
    configuracion = entrada.spec.configuracion_para(clave.tipo_modelo)
    if configuracion is None:
        return Resolucion(
            clave=clave, estado=EstadoResolucion.SIN_COBERTURA,
            motivo=f"{entrada.spec.nombre} no tiene configuración para {clave.tipo_modelo}",
        )
    try:
        catalogo = registro.catalogo(configuracion.catalogo, configuracion.version_catalogo)
    except ErrorRegistro as error:
        return Resolucion(clave=clave, estado=EstadoResolucion.ERROR, motivo=str(error))
    return Resolucion(
        clave=clave,
        estado=EstadoResolucion.RESUELTA,
        skill=entrada.spec.nombre,
        version_skill=entrada.spec.version,
        catalogo=catalogo.nombre,
        version_catalogo=catalogo.version,
        entrada_skill=entrada,
        configuracion=configuracion,
        catalogo_controles=catalogo,
    )
