"""Recorridos del árbol canónico compartidos por el oráculo y por el generador de fronteras."""

from __future__ import annotations

from mrm.contratos.canonico import LibroCanonico, recorrer
from mrm.herramientas._comun.celdas import lista_rango, separar


def refs_de_objetivo(objetivo: str) -> list[str]:
    hoja, rango = separar(objetivo)
    return lista_rango(hoja, rango)


def celdas_alcanzables(libro: LibroCanonico, refs: list[str]) -> list[str]:
    """Celdas con fórmula de las que dependen (transitivamente) las referencias dadas."""
    pendientes = list(refs)
    vistas: set[str] = set()
    con_formula: list[str] = []
    while pendientes:
        ref = pendientes.pop()
        if ref in vistas:
            continue
        vistas.add(ref)
        celda = libro.celdas.get(ref)
        if celda is None or celda.arbol is None:
            continue
        con_formula.append(ref)
        for nodo in recorrer(celda.arbol):
            if nodo["t"] == "ref":
                pendientes.append(f"{nodo['hoja']}!{nodo['celda']}")
            elif nodo["t"] == "rango":
                pendientes.extend(lista_rango(nodo["hoja"], f"{nodo['desde']}:{nodo['hasta']}"))
            elif nodo["t"] == "nombre" and nodo["v"] in libro.nombres_definidos:
                hoja, _, rango = libro.nombres_definidos[nodo["v"]].rpartition("!")
                pendientes.extend(lista_rango(hoja.strip("'"), rango))
    return con_formula
