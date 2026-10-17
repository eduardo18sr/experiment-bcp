"""Herramienta `generar_casos_frontera`: matriz de casos en los límites de las condiciones de rango (R12).

Los límites distintos entre referencia e implementación (p. ej. `<=19` frente a `19-24`) solo se ven
evaluando justo antes, en y después de cada umbral. Esta herramienta encuentra las condiciones de la
referencia que comparan una entrada con una constante y propone esos puntos. No ejecuta nada.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, Field

from mrm.contratos.canonico import LibroCanonico, recorrer
from mrm.contratos.herramienta import Herramienta, TipoHerramienta
from mrm.herramientas._comun.arbol import celdas_alcanzables, refs_de_objetivo

_INVERSO = {"<": ">", ">": "<", "<=": ">=", ">=": "<=", "=": "=", "<>": "<>"}


class EntradaFrontera(BaseModel):
    nombre: str
    ref: str = Field(description="Hoja!Celda de la entrada en la referencia")
    tipo: Literal["numero", "entero", "texto"] = "numero"
    paso: float | None = None


class EntradaGenerarFronteras(BaseModel):
    libro: LibroCanonico
    objetivos: list[str]
    entradas: list[EntradaFrontera]
    max_casos: int = 60


class Condicion(BaseModel):
    celda: str
    entrada: str
    operador: str
    umbral: float


class CasoFrontera(BaseModel):
    entrada: str
    operador: str
    umbral: float
    valor: float
    posicion: Literal["antes", "en", "despues"]
    sobrescrituras: dict[str, Any]


class SalidaGenerarFronteras(BaseModel):
    condiciones: list[Condicion]
    casos: list[CasoFrontera]
    truncado: bool = False


def _puntos(umbral: float, entrada: EntradaFrontera) -> list[tuple[float, str]]:
    if entrada.tipo == "entero":
        if float(umbral).is_integer():
            centro = int(umbral)
            return [(centro - 1, "antes"), (centro, "en"), (centro + 1, "despues")]
        return [(math.floor(umbral), "antes"), (math.ceil(umbral), "despues")]
    paso = entrada.paso or max(abs(umbral), 1.0) * 1e-6
    return [(umbral - paso, "antes"), (umbral, "en"), (umbral + paso, "despues")]


class GenerarCasosFrontera(Herramienta[EntradaGenerarFronteras, SalidaGenerarFronteras]):
    nombre = "generar_casos_frontera"
    version = "1.0.0"
    tipo = TipoHerramienta.DETERMINISTICO
    errores = ("objetivo_invalido",)
    Entrada = EntradaGenerarFronteras
    Salida = SalidaGenerarFronteras

    def ejecutar(self, entrada: EntradaGenerarFronteras) -> SalidaGenerarFronteras:
        try:
            refs = [r for objetivo in entrada.objetivos for r in refs_de_objetivo(objetivo)]
        except ValueError as error:
            raise self.fallar("objetivo_invalido", str(error)) from error
        por_ref = {e.ref.replace("$", ""): e for e in entrada.entradas if e.tipo != "texto"}

        condiciones: dict[tuple[str, str, float], Condicion] = {}
        for ref in sorted(celdas_alcanzables(entrada.libro, refs)):
            for nodo in recorrer(entrada.libro.celdas[ref].arbol):
                if nodo["t"] != "bin" or nodo["op"] not in _INVERSO:
                    continue
                a, b, operador = nodo["a"], nodo["b"], nodo["op"]
                if b.get("t") == "ref" and a.get("t") == "num":
                    a, b, operador = b, a, _INVERSO[operador]
                if a.get("t") != "ref" or b.get("t") != "num":
                    continue
                destino = f"{a['hoja']}!{a['celda']}"
                if destino in por_ref:
                    clave = (destino, operador, float(b["v"]))
                    condiciones.setdefault(
                        clave, Condicion(celda=ref, entrada=por_ref[destino].nombre, operador=operador, umbral=float(b["v"]))
                    )

        casos: list[CasoFrontera] = []
        vistos: set[tuple[str, float]] = set()
        for (destino, operador, umbral), condicion in sorted(condiciones.items(), key=lambda x: (x[0][0], x[0][2])):
            for valor, posicion in _puntos(umbral, por_ref[destino]):
                if (destino, valor) in vistos:
                    continue
                vistos.add((destino, valor))
                casos.append(
                    CasoFrontera(
                        entrada=condicion.entrada,
                        operador=operador,
                        umbral=umbral,
                        valor=valor,
                        posicion=posicion,
                        sobrescrituras={destino: valor},
                    )
                )
        truncado = len(casos) > entrada.max_casos
        return SalidaGenerarFronteras(
            condiciones=list(condiciones.values()), casos=casos[: entrada.max_casos], truncado=truncado
        )
