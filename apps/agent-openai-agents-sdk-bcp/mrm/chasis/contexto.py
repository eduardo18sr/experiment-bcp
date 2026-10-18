"""Contexto de ejecución de una skill: contexto limpio por dimensión e inyección de herramientas declaradas."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from mrm.chasis.registro import Registro
from mrm.chasis.trazas import span
from mrm.contratos.control import CatalogoControles, Control
from mrm.contratos.expediente import ModeloInventario, SolicitudValidacion
from mrm.contratos.herramienta import ErrorHerramienta
from mrm.contratos.skill import ConfiguracionSkill, SkillSpec


class InvocacionHerramienta(BaseModel):
    """Registro de cada llamada a una herramienta: qué, qué versión, cuánto tardó y cómo terminó."""

    herramienta: str
    version: str
    dimension: str
    huella_entrada: str
    duracion_s: float
    estado: str
    error: str | None = None


def _huella(entrada: Any) -> str:
    """Huella de la entrada sin volcar datos: SHA-256 de su serialización."""
    if isinstance(entrada, BaseModel):
        texto = entrada.model_dump_json()
    else:
        texto = json.dumps(entrada, sort_keys=True, default=str)
    return hashlib.sha256(texto.encode()).hexdigest()[:16]


class ContextoEjecucion:
    def __init__(
        self,
        *,
        registro: Registro,
        spec: SkillSpec,
        solicitud: SolicitudValidacion,
        modelo: ModeloInventario,
        catalogo: CatalogoControles,
        controles: list[Control],
        configuracion: ConfiguracionSkill,
        dir_expediente: Path,
        dependencias: dict[str, Any],
        juez: Any = None,
    ):
        self.solicitud = solicitud
        self.modelo = modelo  # inmutable: el tier nunca se modifica ni se reinterpreta
        self.catalogo = catalogo
        self.controles = controles
        self.configuracion = configuracion
        self.juez = juez if spec.usa_juez else None
        self._spec = spec
        self._dir = dir_expediente.resolve()
        self._herramientas = {}
        for dependencia in spec.herramientas_requeridas:
            entrada = registro.resolver_herramienta(dependencia.nombre, dependencia.version_minima)
            self._herramientas[dependencia.nombre] = (entrada.contrato.version, entrada.clase.desde_dependencias(dependencias))
        self.invocaciones: list[InvocacionHerramienta] = []

    def herramienta(self, nombre: str) -> Callable[[Any], Any]:
        if nombre not in self._herramientas:
            raise PermissionError(f"La skill {self._spec.nombre} no declaró la herramienta {nombre} en su skill.yaml")
        version, instancia = self._herramientas[nombre]

        def invocar(entrada: Any) -> Any:
            inicio = time.perf_counter()
            registro = dict(herramienta=nombre, version=version, dimension=self._spec.dimension, huella_entrada=_huella(entrada))
            with span(f"herramienta:{nombre}", {"version": version, "skill": self._spec.nombre}):
                try:
                    salida = instancia(entrada)
                except ErrorHerramienta as error:
                    self.invocaciones.append(InvocacionHerramienta(**registro, duracion_s=time.perf_counter() - inicio, estado="ERROR", error=error.codigo))
                    raise
            self.invocaciones.append(InvocacionHerramienta(**registro, duracion_s=round(time.perf_counter() - inicio, 4), estado="OK"))
            return salida

        return invocar

    def version_herramienta(self, nombre: str) -> str:
        return self._herramientas[nombre][0]

    def versiones_herramientas(self) -> dict[str, str]:
        return {nombre: version for nombre, (version, _) in self._herramientas.items()}

    def ruta(self, relativa: str) -> Path:
        """Resuelve una ruta del expediente impidiendo salir de su carpeta."""
        ruta = (self._dir / relativa).resolve()
        if self._dir not in ruta.parents and ruta != self._dir:
            raise PermissionError(f"Ruta fuera del expediente: {relativa}")
        return ruta
