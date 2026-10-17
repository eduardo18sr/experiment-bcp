"""Herramienta `evaluar_formulas`: el oráculo de la referencia (R3).

Antes de usar el oráculo con entradas nuevas, se valida contra los valores que Excel dejó en caché:
si no reproduce el propio libro, no se puede confiar en lo que calcule para otros escenarios.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

from mrm.contratos.canonico import LibroCanonico
from mrm.contratos.herramienta import Herramienta, TipoHerramienta
from mrm.herramientas._comun.arbol import celdas_alcanzables, refs_de_objetivo
from mrm.herramientas.evaluar_formulas.motor import ErrorEvaluacion, ErrorExcel, Evaluador

MAX_DISCREPANCIAS = 50


class Tolerancia(BaseModel):
    absoluta: float = 1e-9
    relativa: float = 1e-9


class EntradaEvaluarFormulas(BaseModel):
    libro: LibroCanonico
    objetivos: list[str] = Field(description="Celdas o rangos completos: 'Hoja!H13', 'Hoja!I27:BZ27'")
    escenarios: list[dict[str, Any]] = Field(
        default_factory=lambda: [{}], description="Sobrescrituras de celdas por escenario; {} es el escenario base"
    )
    validar_cache: bool = True
    tolerancia_cache: Tolerancia = Field(default_factory=Tolerancia)


class Discrepancia(BaseModel):
    ref: str
    cache: Any
    calculado: Any


class ResultadoEscenario(BaseModel):
    indice: int
    sobrescrituras: dict[str, Any]
    valores: dict[str, list[Any]] = Field(default_factory=dict)
    error: str | None = None


class SalidaEvaluarFormulas(BaseModel):
    oraculo_valido: bool | None = Field(description="None si el libro no tiene caché para validar")
    celdas_validadas: int
    celdas_sin_cache: int
    discrepancias_cache: list[Discrepancia]
    errores_oraculo: list[str]
    resultados: list[ResultadoEscenario]


def _serializable(valor: Any) -> Any:
    if isinstance(valor, ErrorExcel):
        return valor.codigo
    if isinstance(valor, list):
        return [_serializable(v) for v in valor]
    return valor


def _coincide(a: Any, b: Any, tolerancia: Tolerancia) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(a) or math.isnan(b):
            return False
        return abs(a - b) <= max(tolerancia.absoluta, tolerancia.relativa * max(abs(a), abs(b)))
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().upper() == b.strip().upper()
    return a == b


class EvaluarFormulas(Herramienta[EntradaEvaluarFormulas, SalidaEvaluarFormulas]):
    nombre = "evaluar_formulas"
    version = "1.0.0"
    tipo = TipoHerramienta.DETERMINISTICO
    errores = ("objetivo_invalido",)
    Entrada = EntradaEvaluarFormulas
    Salida = SalidaEvaluarFormulas

    def ejecutar(self, entrada: EntradaEvaluarFormulas) -> SalidaEvaluarFormulas:
        libro = entrada.libro
        try:
            refs_objetivo = {objetivo: refs_de_objetivo(objetivo) for objetivo in entrada.objetivos}
        except ValueError as error:
            raise self.fallar("objetivo_invalido", str(error)) from error

        alcanzables = celdas_alcanzables(libro, [r for refs in refs_objetivo.values() for r in refs])
        discrepancias: list[Discrepancia] = []
        errores_oraculo: list[str] = []
        validadas = sin_cache = 0
        oraculo_valido: bool | None = None

        if entrada.validar_cache and libro.tiene_cache:
            evaluador = Evaluador(libro)
            for ref in alcanzables:
                cache = libro.celdas[ref].valor
                if cache is None:
                    sin_cache += 1
                    continue
                try:
                    calculado = evaluador.valor(ref)
                except ErrorEvaluacion as error:
                    errores_oraculo.append(f"{ref}: {error}")
                    continue
                validadas += 1
                if not _coincide(_serializable(calculado), cache, entrada.tolerancia_cache):
                    if len(discrepancias) < MAX_DISCREPANCIAS:
                        discrepancias.append(Discrepancia(ref=ref, cache=cache, calculado=_serializable(calculado)))
            oraculo_valido = not discrepancias and not errores_oraculo and validadas > 0

        resultados = []
        for indice, sobrescrituras in enumerate(entrada.escenarios):
            evaluador = Evaluador(libro, sobrescrituras)
            resultado = ResultadoEscenario(indice=indice, sobrescrituras=sobrescrituras)
            try:
                resultado.valores = {
                    objetivo: [_serializable(evaluador.valor(ref)) for ref in refs]
                    for objetivo, refs in refs_objetivo.items()
                }
            except ErrorEvaluacion as error:
                resultado.error = str(error)
            resultados.append(resultado)

        return SalidaEvaluarFormulas(
            oraculo_valido=oraculo_valido,
            celdas_validadas=validadas,
            celdas_sin_cache=sin_cache,
            discrepancias_cache=discrepancias,
            errores_oraculo=errores_oraculo,
            resultados=resultados,
        )
