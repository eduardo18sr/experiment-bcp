"""Herramienta `comparar_series`: el motor de comparación numérica (R11).

Compara dos series (o dos escalares) punto a punto con tolerancia declarada. Devuelve hechos:
cuántos se compararon, cuántos coinciden, dónde empieza la divergencia y qué tramos coinciden.
No sabe qué representa cada serie ni si una diferencia es un hallazgo.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

from mrm.contratos.herramienta import Herramienta, TipoHerramienta
from mrm.herramientas._comun.celdas import a_numero, nombre_normalizado


class ToleranciaComparacion(BaseModel):
    absoluta: float = Field(ge=0)
    relativa: float = Field(default=0.0, ge=0)


class EntradaComparar(BaseModel):
    referencia: list[Any]
    implementacion: list[Any]
    etiquetas: list[Any] | None = None
    tolerancia: ToleranciaComparacion


class PuntoComparado(BaseModel):
    etiqueta: Any
    referencia: Any
    implementacion: Any
    dif_abs: float | None = None
    coincide: bool | None = Field(description="None si el punto no es comparable")


class SalidaComparar(BaseModel):
    comparados: int
    coincidencias: int
    no_comparables: int
    longitud_referencia: int
    longitud_implementacion: int
    max_dif_abs: float | None
    max_dif_rel: float | None
    primera_divergencia: Any = None
    tramos_coincidentes: list[list[Any]]
    tramos_divergentes: list[list[Any]]
    detalle: list[PuntoComparado]


def _tramos(puntos: list[PuntoComparado], buscado: bool) -> list[list[Any]]:
    tramos: list[list[Any]] = []
    inicio = anterior = None
    for punto in puntos:
        if punto.coincide is buscado:
            if inicio is None:
                inicio = punto.etiqueta
            anterior = punto.etiqueta
        elif inicio is not None:
            tramos.append([inicio, anterior])
            inicio = None
    if inicio is not None:
        tramos.append([inicio, anterior])
    return tramos


class CompararSeries(Herramienta[EntradaComparar, SalidaComparar]):
    nombre = "comparar_series"
    version = "1.0.0"
    tipo = TipoHerramienta.DETERMINISTICO
    errores = ("etiquetas_incompatibles",)
    Entrada = EntradaComparar
    Salida = SalidaComparar

    def ejecutar(self, entrada: EntradaComparar) -> SalidaComparar:
        longitud = max(len(entrada.referencia), len(entrada.implementacion))
        etiquetas = entrada.etiquetas if entrada.etiquetas is not None else list(range(1, longitud + 1))
        if len(etiquetas) < longitud:
            raise self.fallar("etiquetas_incompatibles", f"{len(etiquetas)} etiquetas para {longitud} puntos")

        tol = entrada.tolerancia
        puntos: list[PuntoComparado] = []
        max_abs = max_rel = None
        for indice in range(longitud):
            ref = entrada.referencia[indice] if indice < len(entrada.referencia) else None
            imp = entrada.implementacion[indice] if indice < len(entrada.implementacion) else None
            num_ref, num_imp = a_numero(ref), a_numero(imp)
            if num_ref is not None and num_imp is not None and not (math.isnan(num_ref) or math.isnan(num_imp)):
                dif = abs(num_ref - num_imp)
                escala = max(abs(num_ref), abs(num_imp))
                relativa = dif / escala if escala else 0.0
                max_abs = dif if max_abs is None else max(max_abs, dif)
                max_rel = relativa if max_rel is None else max(max_rel, relativa)
                coincide = dif <= max(tol.absoluta, tol.relativa * escala)
                puntos.append(PuntoComparado(etiqueta=etiquetas[indice], referencia=ref, implementacion=imp, dif_abs=dif, coincide=coincide))
            elif isinstance(ref, str) and isinstance(imp, str):
                coincide = nombre_normalizado(ref) == nombre_normalizado(imp)
                puntos.append(PuntoComparado(etiqueta=etiquetas[indice], referencia=ref, implementacion=imp, coincide=coincide))
            else:
                puntos.append(PuntoComparado(etiqueta=etiquetas[indice], referencia=ref, implementacion=imp, coincide=None))

        comparables = [p for p in puntos if p.coincide is not None]
        primera = next((p.etiqueta for p in puntos if p.coincide is False), None)
        return SalidaComparar(
            comparados=len(comparables),
            coincidencias=sum(1 for p in comparables if p.coincide),
            no_comparables=len(puntos) - len(comparables),
            longitud_referencia=len(entrada.referencia),
            longitud_implementacion=len(entrada.implementacion),
            max_dif_abs=max_abs,
            max_dif_rel=max_rel,
            primera_divergencia=primera,
            tramos_coincidentes=_tramos(puntos, True),
            tramos_divergentes=_tramos(puntos, False),
            detalle=puntos,
        )
