"""Representación canónica (framework C.3).

Todo extractor traduce a esta forma y todo comparador la consume. Así, un formato de entrada nuevo
solo obliga a escribir un extractor; la lógica de comparación no se toca.

Árbol de operaciones (cada nodo es un dict JSON):
    {"t": "num", "v": 1.5}                    {"t": "str", "v": "PYME"}        {"t": "bool", "v": true}
    {"t": "ref", "hoja": "H", "celda": "A1"}  {"t": "rango", "hoja": "H", "desde": "A1", "hasta": "B3"}
    {"t": "nombre", "v": "tasa"}              {"t": "un", "op": "-", "x": nodo} {"t": "pct", "x": nodo}
    {"t": "bin", "op": "+", "a": nodo, "b": nodo}
    {"t": "fn", "nombre": "IF", "args": [nodo, ...]}                         {"t": "vacio"}
    {"t": "error", "v": "#N/A"}
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

OPERADORES_COMPARACION = ("=", "<>", "<", ">", "<=", ">=")


class CeldaCanonica(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str = Field(description="Hoja!A1")
    valor: Any = Field(default=None, description="Valor literal, o el valor en caché si es fórmula")
    formula: str | None = None
    arbol: dict[str, Any] | None = None


class LibroCanonico(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archivo: str
    sha256: str
    hojas: list[str]
    celdas: dict[str, CeldaCanonica]
    nombres_definidos: dict[str, str] = Field(default_factory=dict)
    tiene_cache: bool
    advertencias: list[str] = Field(default_factory=list)


class CalculoCanonico(BaseModel):
    """Vista `calculo_canonico` v1.0 del framework: qué se calcula, con qué entradas y operaciones."""

    salida: str
    entradas: list[str]
    constantes: list[float]
    condiciones: list[dict[str, Any]]
    operaciones: dict[str, Any]


def recorrer(nodo: dict[str, Any]):
    """Recorre el árbol en profundidad."""
    yield nodo
    tipo = nodo.get("t")
    if tipo == "un" or tipo == "pct":
        yield from recorrer(nodo["x"])
    elif tipo == "bin":
        yield from recorrer(nodo["a"])
        yield from recorrer(nodo["b"])
    elif tipo == "fn":
        for argumento in nodo["args"]:
            yield from recorrer(argumento)


def a_calculo(celda: CeldaCanonica) -> CalculoCanonico:
    """Deriva la vista canónica de cálculo de una celda con fórmula."""
    if celda.arbol is None:
        raise ValueError(f"La celda {celda.ref} no tiene árbol de fórmula")
    entradas: list[str] = []
    constantes: list[float] = []
    condiciones: list[dict[str, Any]] = []
    for nodo in recorrer(celda.arbol):
        if nodo["t"] == "ref":
            entradas.append(f"{nodo['hoja']}!{nodo['celda']}")
        elif nodo["t"] == "rango":
            entradas.append(f"{nodo['hoja']}!{nodo['desde']}:{nodo['hasta']}")
        elif nodo["t"] == "num":
            constantes.append(nodo["v"])
        elif nodo["t"] == "bin" and nodo["op"] in OPERADORES_COMPARACION:
            condiciones.append(nodo)
    return CalculoCanonico(
        salida=celda.ref,
        entradas=sorted(set(entradas)),
        constantes=constantes,
        condiciones=condiciones,
        operaciones=celda.arbol,
    )
