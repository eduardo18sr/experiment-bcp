"""Traductor de fórmulas Excel al árbol canónico (ver `mrm/contratos/canonico.py`).

Precedencia de Excel, de menor a mayor: comparación, `&`, `+ -`, `* /`, `^`, `%`, negación.
La negación se aplica antes que la potencia (`=-2^2` vale 4) y `^` asocia por la izquierda.
"""

from __future__ import annotations

import re
from typing import Any

_ESPECIFICACION_TOKENS = [
    ("ESP", r"\s+"),
    ("CADENA", r'"(?:[^"]|"")*"'),
    ("ERROR", r"#(?:NULL!|DIV/0!|VALUE!|REF!|NAME\?|NUM!|N/A)"),
    ("NUMERO", r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"),
    (
        "REF",
        r"(?:(?:'(?:[^']|'')+'|[A-Za-z_][\w\.]*)!)?\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?(?![\w(])",
    ),
    ("FUNCION", r"[A-Za-z_][\w\.]*(?=\()"),
    ("IDENT", r"[A-Za-z_][\w\.]*"),
    ("OP", r"<=|>=|<>|[-+*/^&=<>%]"),
    ("PAREN_A", r"\("),
    ("PAREN_C", r"\)"),
    ("SEP", r"[,;]"),
]
_TOKENIZADOR = re.compile("|".join(f"(?P<{nombre}>{patron})" for nombre, patron in _ESPECIFICACION_TOKENS))
_COMPARACION = {"=", "<>", "<", ">", "<=", ">="}


class ErrorFormula(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(f"[{codigo}] {mensaje}")
        self.codigo = codigo


def tokenizar(formula: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    posicion = 0
    while posicion < len(formula):
        coincidencia = _TOKENIZADOR.match(formula, posicion)
        if not coincidencia:
            raise ErrorFormula("formula_invalida", f"Símbolo no reconocido en {formula!r}, posición {posicion}")
        tipo = coincidencia.lastgroup
        if tipo != "ESP":
            tokens.append((tipo, coincidencia.group()))
        posicion = coincidencia.end()
    return tokens


def _nodo_referencia(texto: str, hoja_actual: str) -> dict[str, Any]:
    if "!" in texto:
        hoja, rango = texto.rsplit("!", 1)
        if hoja.startswith("'"):
            hoja = hoja[1:-1].replace("''", "'")
    else:
        hoja, rango = hoja_actual, texto
    rango = rango.replace("$", "").upper()
    if ":" in rango:
        desde, hasta = rango.split(":")
        return {"t": "rango", "hoja": hoja, "desde": desde, "hasta": hasta}
    return {"t": "ref", "hoja": hoja, "celda": rango}


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], hoja: str, formula: str):
        self.tokens = tokens
        self.i = 0
        self.hoja = hoja
        self.formula = formula

    def _ver(self) -> tuple[str | None, str | None]:
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def _tomar(self) -> tuple[str | None, str | None]:
        token = self._ver()
        self.i += 1
        return token

    def _es(self, tipo: str, *valores: str) -> bool:
        actual_tipo, actual_valor = self._ver()
        return actual_tipo == tipo and (not valores or actual_valor in valores)

    def _fallar(self, detalle: str) -> ErrorFormula:
        return ErrorFormula("formula_invalida", f"{detalle} en {self.formula!r}")

    def analizar(self) -> dict[str, Any]:
        nodo = self._comparacion()
        if self.i != len(self.tokens):
            raise self._fallar(f"Símbolo inesperado {self._ver()[1]!r}")
        return nodo

    def _binaria(self, siguiente, operadores: set[str]) -> dict[str, Any]:
        izquierda = siguiente()
        while self._es("OP") and self._ver()[1] in operadores:
            _, operador = self._tomar()
            derecha = siguiente()
            izquierda = {"t": "bin", "op": operador, "a": izquierda, "b": derecha}
        return izquierda

    def _comparacion(self):
        return self._binaria(self._concatenacion, _COMPARACION)

    def _concatenacion(self):
        return self._binaria(self._aditiva, {"&"})

    def _aditiva(self):
        return self._binaria(self._multiplicativa, {"+", "-"})

    def _multiplicativa(self):
        return self._binaria(self._potencia, {"*", "/"})

    def _potencia(self):
        return self._binaria(self._unaria, {"^"})

    def _unaria(self) -> dict[str, Any]:
        if self._es("OP", "-", "+"):
            _, operador = self._tomar()
            operando = self._unaria()
            return operando if operador == "+" else {"t": "un", "op": "-", "x": operando}
        return self._postfija()

    def _postfija(self) -> dict[str, Any]:
        nodo = self._primaria()
        while self._es("OP", "%"):
            self._tomar()
            nodo = {"t": "pct", "x": nodo}
        return nodo

    def _primaria(self) -> dict[str, Any]:
        tipo, valor = self._tomar()
        if tipo == "NUMERO":
            return {"t": "num", "v": float(valor)}
        if tipo == "CADENA":
            return {"t": "str", "v": valor[1:-1].replace('""', '"')}
        if tipo == "ERROR":
            return {"t": "error", "v": valor}
        if tipo == "REF":
            return _nodo_referencia(valor, self.hoja)
        if tipo == "FUNCION":
            return self._funcion(valor)
        if tipo == "IDENT":
            if valor.upper() in ("TRUE", "FALSE", "VERDADERO", "FALSO"):
                return {"t": "bool", "v": valor.upper() in ("TRUE", "VERDADERO")}
            return {"t": "nombre", "v": valor}
        if tipo == "PAREN_A":
            nodo = self._comparacion()
            if not self._es("PAREN_C"):
                raise self._fallar("Falta ')'")
            self._tomar()
            return nodo
        raise self._fallar(f"Se esperaba un operando y llegó {valor!r}")

    def _funcion(self, nombre: str) -> dict[str, Any]:
        nombre = nombre.upper()
        for prefijo in ("_XLFN.", "_XLWS."):
            if nombre.startswith(prefijo):
                nombre = nombre[len(prefijo):]
        self._tomar()  # '('
        argumentos: list[dict[str, Any]] = []
        if self._es("PAREN_C"):
            self._tomar()
            return {"t": "fn", "nombre": nombre, "args": argumentos}
        while True:
            if self._es("SEP") or self._es("PAREN_C"):
                argumentos.append({"t": "vacio"})
            else:
                argumentos.append(self._comparacion())
            if self._es("SEP"):
                self._tomar()
                continue
            if self._es("PAREN_C"):
                self._tomar()
                return {"t": "fn", "nombre": nombre, "args": argumentos}
            raise self._fallar(f"Argumentos mal formados en {nombre}")


def analizar_formula(formula: str, hoja: str) -> dict[str, Any]:
    """Traduce '=IF(H8<=19,1,2)' a su árbol canónico. Las referencias sin hoja se anclan a `hoja`."""
    texto = formula.strip()
    if texto.startswith("="):
        texto = texto[1:]
    if not texto:
        raise ErrorFormula("formula_invalida", "Fórmula vacía")
    return _Parser(tokenizar(texto), hoja, formula).analizar()
