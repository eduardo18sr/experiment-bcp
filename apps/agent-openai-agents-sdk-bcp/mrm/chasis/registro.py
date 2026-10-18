"""Registros de herramientas, skills y catálogos, con verificación de integridad (R10).

Los registros son la declaración legible por máquina de lo que existe, en qué versión y quién responde.
La verificación de integridad corre al arrancar y en integración continua: un registro inconsistente es un
defecto que detiene la plataforma, no una decisión que se toma en ejecución.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from mrm.contratos.control import CatalogoControles
from mrm.contratos.herramienta import ContratoHerramienta, Herramienta
from mrm.contratos.skill import Skill, SkillSpec
from mrm.contratos.version import es_compatible, parsear

RAIZ_MRM = Path(__file__).resolve().parent.parent


class ErrorRegistro(Exception):
    pass


def _importar(referencia: str) -> Any:
    modulo, _, nombre = referencia.partition(":")
    return getattr(importlib.import_module(modulo), nombre)


def _leer_yaml(ruta: Path) -> Any:
    with open(ruta, encoding="utf-8") as archivo:
        return yaml.safe_load(archivo)


@dataclass
class EntradaHerramienta:
    contrato: ContratoHerramienta
    clase: type[Herramienta]
    estado: str


@dataclass
class EntradaSkill:
    spec: SkillSpec
    clase: type[Skill]
    estado: str


class Registro:
    def __init__(self, raiz: Path = RAIZ_MRM):
        self.raiz = raiz
        self.herramientas: dict[str, list[EntradaHerramienta]] = {}
        self.skills: dict[str, EntradaSkill] = {}
        self.catalogos: dict[tuple[str, str], CatalogoControles] = {}
        self._cargar()

    # --- carga -------------------------------------------------------------------------------------------
    def _cargar(self) -> None:
        for entrada in _leer_yaml(self.raiz / "registro" / "herramientas.yaml")["herramientas"]:
            contrato = ContratoHerramienta.model_validate(_leer_yaml(self.raiz / entrada["contrato"]))
            clase = _importar(entrada["implementacion"])
            self.herramientas.setdefault(contrato.nombre, []).append(
                EntradaHerramienta(contrato=contrato, clase=clase, estado=entrada.get("estado", "activo"))
            )
        for entrada in _leer_yaml(self.raiz / "registro" / "skills.yaml")["skills"]:
            spec = SkillSpec.model_validate(_leer_yaml(self.raiz / entrada["spec"]))
            if spec.nombre in self.skills:
                raise ErrorRegistro(f"Skill registrada dos veces: {spec.nombre}")
            self.skills[spec.nombre] = EntradaSkill(spec=spec, clase=_importar(entrada["implementacion"]), estado=entrada.get("estado", "activo"))
        for ruta in sorted((self.raiz / "catalogos").glob("*.yaml")):
            catalogo = CatalogoControles.model_validate(_leer_yaml(ruta))
            clave = (catalogo.nombre, catalogo.version)
            if clave in self.catalogos:
                raise ErrorRegistro(f"Catálogo repetido: {clave}")
            self.catalogos[clave] = catalogo

    # --- consultas ---------------------------------------------------------------------------------------
    def resolver_herramienta(self, nombre: str, version_minima: str) -> EntradaHerramienta:
        candidatas = [
            h for h in self.herramientas.get(nombre, [])
            if h.estado == "activo" and es_compatible(h.contrato.version, version_minima)
        ]
        if not candidatas:
            raise ErrorRegistro(f"No hay una versión activa de {nombre} compatible con >= {version_minima}")
        return max(candidatas, key=lambda h: parsear(h.contrato.version))

    def catalogo(self, nombre: str, version: str) -> CatalogoControles:
        try:
            return self.catalogos[(nombre, version)]
        except KeyError as error:
            raise ErrorRegistro(f"Catálogo inexistente: {nombre}@{version}") from error

    def skills_activas(self) -> list[EntradaSkill]:
        return [s for s in self.skills.values() if s.estado == "activo"]

    # --- integridad --------------------------------------------------------------------------------------
    def verificar_integridad(self) -> list[str]:
        """Devuelve la lista de defectos del registro. Vacía significa íntegro."""
        defectos: list[str] = []
        for nombre, versiones in self.herramientas.items():
            for h in versiones:
                c, k = h.contrato, h.clase
                if (k.nombre, k.version, k.tipo.value) != (c.nombre, c.version, c.tipo.value):
                    defectos.append(f"{nombre}: la implementación declara {k.nombre}@{k.version} ({k.tipo.value}) y el contrato {c.nombre}@{c.version} ({c.tipo.value})")
                if set(k.errores) != set(c.errores):
                    defectos.append(f"{nombre}: errores de la implementación {sorted(k.errores)} distintos del contrato {sorted(c.errores)}")
                for lado, campos, modelo in (("entrada", c.entrada, k.Entrada), ("salida", c.salida, k.Salida)):
                    if set(campos) != set(modelo.model_fields):
                        defectos.append(f"{nombre}: campos de {lado} del contrato {sorted(campos)} distintos de la implementación {sorted(modelo.model_fields)}")
        for entrada in self.skills.values():
            spec = entrada.spec
            for dependencia in spec.herramientas_requeridas:
                try:
                    self.resolver_herramienta(dependencia.nombre, dependencia.version_minima)
                except ErrorRegistro as error:
                    defectos.append(f"{spec.nombre}: {error}")
            for configuracion in spec.configuraciones:
                clave = (configuracion.catalogo, configuracion.version_catalogo)
                catalogo = self.catalogos.get(clave)
                if catalogo is None:
                    defectos.append(f"{spec.nombre}: el catálogo {clave} no existe")
                    continue
                if catalogo.dimension != spec.dimension:
                    defectos.append(f"{spec.nombre}: el catálogo {catalogo.nombre} es de la dimensión {catalogo.dimension}")
                for control in catalogo.controles:
                    if control.regla not in spec.reglas:
                        defectos.append(f"{catalogo.nombre}/{control.id}: la regla {control.regla} no la ofrece {spec.nombre}")
        defectos.extend(self._empates())
        return defectos

    def _empates(self) -> list[str]:
        """Dos skills que reclaman la misma clave con la misma especificidad son un defecto del registro."""
        defectos = []
        activas = self.skills_activas()
        for i, a in enumerate(activas):
            for b in activas[i + 1:]:
                if a.spec.dimension != b.spec.dimension or a.spec.aplica_a.atributos != b.spec.aplica_a.atributos:
                    continue
                comunes = set(a.spec.aplica_a.tipo_modelo) & set(b.spec.aplica_a.tipo_modelo)
                if comunes:
                    defectos.append(f"Empate en el registro: {a.spec.nombre} y {b.spec.nombre} reclaman {a.spec.dimension} × {sorted(comunes)}")
        return defectos

    def describir(self) -> dict[str, Any]:
        return {
            "herramientas": [
                {"nombre": h.contrato.nombre, "version": h.contrato.version, "tipo": h.contrato.tipo.value,
                 "estado": h.estado, "propietario": h.contrato.propietario, "descripcion": " ".join(h.contrato.descripcion.split())}
                for versiones in self.herramientas.values() for h in versiones
            ],
            "skills": [
                {"nombre": s.spec.nombre, "version": s.spec.version, "dimension": s.spec.dimension,
                 "tipos_modelo": s.spec.aplica_a.tipo_modelo, "estado": s.estado,
                 "herramientas": [f"{d.nombre}>={d.version_minima}" for d in s.spec.herramientas_requeridas]}
                for s in self.skills.values()
            ],
            "catalogos": [
                {"nombre": c.nombre, "version": c.version, "dimension": c.dimension, "tipo_modelo": c.tipo_modelo,
                 "controles": [{"id": x.id, "nombre": x.nombre, "tipo": x.tipo.value, "severidad": x.severidad.value,
                                "tier_minimo": x.tier_minimo} for x in c.controles]}
                for c in self.catalogos.values()
            ],
        }
