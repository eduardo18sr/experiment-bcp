"""Motor de evaluación del árbol canónico (oráculo de la referencia, requisito R3).

Recalcula las fórmulas a partir de los valores literales del libro, con sobrescrituras opcionales
de celdas de entrada. Reproduce la semántica de Excel en lo que importa para comparar cálculos:
errores (#DIV/0!, #NUM!...), redondeo "half away from zero", comparaciones de texto sin
distinguir mayúsculas y búsquedas exactas o aproximadas.
"""

from __future__ import annotations

import math
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Any, Callable

from mrm.contratos.canonico import LibroCanonico
from mrm.herramientas._comun.celdas import matriz_rango


class ErrorEvaluacion(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(f"[{codigo}] {mensaje}")
        self.codigo = codigo


class ErrorExcel:
    """Un valor de error de Excel. Se propaga por la aritmética como en Excel."""

    __slots__ = ("codigo",)

    def __init__(self, codigo: str):
        self.codigo = codigo

    def __eq__(self, otro: object) -> bool:
        return isinstance(otro, ErrorExcel) and otro.codigo == self.codigo

    def __hash__(self) -> int:
        return hash(self.codigo)

    def __repr__(self) -> str:
        return self.codigo


DIV0, NUM, VALOR, NA = ErrorExcel("#DIV/0!"), ErrorExcel("#NUM!"), ErrorExcel("#VALUE!"), ErrorExcel("#N/A")


def _numero(valor: Any) -> float | ErrorExcel:
    if isinstance(valor, ErrorExcel):
        return valor
    if valor is None:
        return 0.0
    if isinstance(valor, bool):
        return 1.0 if valor else 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return float(str(valor).strip())
    except ValueError:
        return VALOR


def _logico(valor: Any) -> bool | ErrorExcel:
    if isinstance(valor, ErrorExcel):
        return valor
    if isinstance(valor, str):
        texto = valor.strip().upper()
        if texto in ("TRUE", "VERDADERO"):
            return True
        if texto in ("FALSE", "FALSO"):
            return False
        return VALOR
    numero = _numero(valor)
    return numero if isinstance(numero, ErrorExcel) else numero != 0


def _redondear(valor: float, digitos: int, modo) -> float:
    cuanto = Decimal(1).scaleb(-digitos)
    return float(Decimal(repr(valor)).quantize(cuanto, rounding=modo))


def _clave_comparacion(valor: Any) -> tuple[int, Any]:
    """Excel ordena números < texto < lógicos; el texto se compara sin mayúsculas."""
    if valor is None:
        return (0, 0.0)
    if isinstance(valor, bool):
        return (2, valor)
    if isinstance(valor, (int, float)):
        return (0, float(valor))
    return (1, str(valor).upper())


def _comparar(operador: str, a: Any, b: Any) -> bool:
    if a is None and isinstance(b, str):
        a = ""
    if b is None and isinstance(a, str):
        b = ""
    clave_a, clave_b = _clave_comparacion(a), _clave_comparacion(b)
    return {
        "=": clave_a == clave_b,
        "<>": clave_a != clave_b,
        "<": clave_a < clave_b,
        ">": clave_a > clave_b,
        "<=": clave_a <= clave_b,
        ">=": clave_a >= clave_b,
    }[operador]


class Evaluador:
    """Evalúa celdas del libro canónico, con memoria y detección de referencias circulares."""

    def __init__(self, libro: LibroCanonico, sobrescrituras: dict[str, Any] | None = None):
        self.libro = libro
        self.sobrescrituras = {k.replace("$", ""): v for k, v in (sobrescrituras or {}).items()}
        self._memoria: dict[str, Any] = {}
        self._en_curso: set[str] = set()

    # --- celdas y rangos -------------------------------------------------------------------------
    def valor(self, ref: str) -> Any:
        if ref in self.sobrescrituras:
            return self.sobrescrituras[ref]
        if ref in self._memoria:
            return self._memoria[ref]
        celda = self.libro.celdas.get(ref)
        if celda is None:
            return None
        if celda.formula is None:
            return celda.valor
        if celda.arbol is None:
            raise ErrorEvaluacion("formula_no_traducible", f"{ref} tiene una fórmula que no pudo traducirse")
        if ref in self._en_curso:
            raise ErrorEvaluacion("referencia_circular", f"Referencia circular en {ref}")
        self._en_curso.add(ref)
        try:
            hoja = ref.rsplit("!", 1)[0]
            resultado = self.evaluar(celda.arbol, hoja)
        finally:
            self._en_curso.discard(ref)
        self._memoria[ref] = resultado
        return resultado

    def _matriz(self, hoja: str, desde: str, hasta: str) -> list[list[Any]]:
        return [[self.valor(ref) for ref in fila] for fila in matriz_rango(hoja, f"{desde}:{hasta}")]

    def _nombre(self, nombre: str) -> Any:
        definicion = self.libro.nombres_definidos.get(nombre)
        if definicion is None:
            raise ErrorEvaluacion("referencia_invalida", f"Nombre definido inexistente: {nombre}")
        hoja, _, rango = definicion.rpartition("!")
        hoja = hoja.strip("'")
        if ":" in rango:
            desde, hasta = rango.split(":")
            return self._matriz(hoja, desde, hasta)
        return self.valor(f"{hoja}!{rango}")

    # --- árbol -----------------------------------------------------------------------------------
    def evaluar(self, nodo: dict[str, Any], hoja: str) -> Any:
        tipo = nodo["t"]
        if tipo in ("num", "str", "bool"):
            return nodo["v"]
        if tipo == "vacio":
            return None
        if tipo == "error":
            return ErrorExcel(nodo["v"])
        if tipo == "ref":
            return self.valor(f"{nodo['hoja']}!{nodo['celda']}")
        if tipo == "rango":
            return self._matriz(nodo["hoja"], nodo["desde"], nodo["hasta"])
        if tipo == "nombre":
            return self._nombre(nodo["v"])
        if tipo == "un":
            x = _numero(self._escalar(self.evaluar(nodo["x"], hoja)))
            return x if isinstance(x, ErrorExcel) else -x
        if tipo == "pct":
            x = _numero(self._escalar(self.evaluar(nodo["x"], hoja)))
            return x if isinstance(x, ErrorExcel) else x / 100
        if tipo == "bin":
            return self._binaria(nodo, hoja)
        if tipo == "fn":
            return self._funcion(nodo, hoja)
        raise ErrorEvaluacion("formula_invalida", f"Nodo desconocido: {tipo}")

    @staticmethod
    def _escalar(valor: Any) -> Any:
        if isinstance(valor, list):
            return valor[0][0] if valor and valor[0] else None
        return valor

    def _binaria(self, nodo: dict[str, Any], hoja: str) -> Any:
        operador = nodo["op"]
        a = self._escalar(self.evaluar(nodo["a"], hoja))
        b = self._escalar(self.evaluar(nodo["b"], hoja))
        for lado in (a, b):
            if isinstance(lado, ErrorExcel):
                return lado
        if operador == "&":
            return f"{'' if a is None else a}{'' if b is None else b}"
        if operador in ("=", "<>", "<", ">", "<=", ">="):
            return _comparar(operador, a, b)
        x, y = _numero(a), _numero(b)
        for lado in (x, y):
            if isinstance(lado, ErrorExcel):
                return lado
        if operador == "+":
            return x + y
        if operador == "-":
            return x - y
        if operador == "*":
            return x * y
        if operador == "/":
            return DIV0 if y == 0 else x / y
        if operador == "^":
            try:
                resultado = x**y
            except (OverflowError, ZeroDivisionError):
                return NUM
            return NUM if isinstance(resultado, complex) else float(resultado)
        raise ErrorEvaluacion("formula_invalida", f"Operador desconocido: {operador}")

    # --- funciones -------------------------------------------------------------------------------
    def _funcion(self, nodo: dict[str, Any], hoja: str) -> Any:
        nombre = nodo["nombre"]
        argumentos = nodo["args"]
        perezosas = {"IF": self._si, "IFERROR": self._si_error, "AND": self._y, "OR": self._o}
        if nombre in perezosas:
            return perezosas[nombre](argumentos, hoja)
        implementacion = _FUNCIONES.get(nombre)
        if implementacion is None:
            raise ErrorEvaluacion("funcion_no_soportada", f"Función no soportada por el oráculo: {nombre}")
        valores = [self.evaluar(argumento, hoja) for argumento in argumentos]
        return implementacion(*valores)

    def _si(self, argumentos, hoja):
        condicion = _logico(self._escalar(self.evaluar(argumentos[0], hoja)))
        if isinstance(condicion, ErrorExcel):
            return condicion
        if condicion:
            return self.evaluar(argumentos[1], hoja) if len(argumentos) > 1 else True
        return self.evaluar(argumentos[2], hoja) if len(argumentos) > 2 else False

    def _si_error(self, argumentos, hoja):
        valor = self._escalar(self.evaluar(argumentos[0], hoja))
        return self.evaluar(argumentos[1], hoja) if isinstance(valor, ErrorExcel) else valor

    def _logicos(self, argumentos, hoja) -> list[Any]:
        valores = []
        for argumento in argumentos:
            valor = self.evaluar(argumento, hoja)
            valores.extend(_aplanar(valor) if isinstance(valor, list) else [valor])
        return [_logico(v) for v in valores if v is not None]

    def _y(self, argumentos, hoja):
        valores = self._logicos(argumentos, hoja)
        errores = [v for v in valores if isinstance(v, ErrorExcel)]
        return errores[0] if errores else all(valores)

    def _o(self, argumentos, hoja):
        valores = self._logicos(argumentos, hoja)
        errores = [v for v in valores if isinstance(v, ErrorExcel)]
        return errores[0] if errores else any(valores)


def _aplanar(valor: Any) -> list[Any]:
    if isinstance(valor, list):
        return [x for fila in valor for x in (fila if isinstance(fila, list) else [fila])]
    return [valor]


def _numeros(*valores) -> list[float] | ErrorExcel:
    resultado = []
    for valor in valores:
        for elemento in _aplanar(valor):
            if isinstance(elemento, ErrorExcel):
                return elemento
            if isinstance(elemento, (int, float)) and not isinstance(elemento, bool):
                resultado.append(float(elemento))
    return resultado


def _unaria(funcion: Callable[[float], float], dominio: Callable[[float], bool] = lambda _: True):
    def aplicar(valor):
        x = _numero(Evaluador._escalar(valor))
        if isinstance(x, ErrorExcel):
            return x
        if not dominio(x):
            return NUM
        try:
            return funcion(x)
        except (OverflowError, ValueError):
            return NUM

    return aplicar


def _redondeo(modo):
    def aplicar(valor, digitos=0):
        x = _numero(Evaluador._escalar(valor))
        d = _numero(Evaluador._escalar(digitos))
        if isinstance(x, ErrorExcel):
            return x
        if isinstance(d, ErrorExcel):
            return d
        return _redondear(x, int(d), modo)

    return aplicar


def _log(valor, base=10.0):
    x, b = _numero(Evaluador._escalar(valor)), _numero(Evaluador._escalar(base))
    if isinstance(x, ErrorExcel) or isinstance(b, ErrorExcel):
        return x if isinstance(x, ErrorExcel) else b
    if x <= 0 or b <= 0 or b == 1:
        return NUM
    return math.log(x, b)


def _suma(*valores):
    numeros = _numeros(*valores)
    return numeros if isinstance(numeros, ErrorExcel) else float(sum(numeros))


def _promedio(*valores):
    numeros = _numeros(*valores)
    if isinstance(numeros, ErrorExcel):
        return numeros
    return DIV0 if not numeros else sum(numeros) / len(numeros)


def _minimo(*valores):
    numeros = _numeros(*valores)
    return numeros if isinstance(numeros, ErrorExcel) else (min(numeros) if numeros else 0.0)


def _maximo(*valores):
    numeros = _numeros(*valores)
    return numeros if isinstance(numeros, ErrorExcel) else (max(numeros) if numeros else 0.0)


def _potencia(base, exponente):
    x, y = _numero(Evaluador._escalar(base)), _numero(Evaluador._escalar(exponente))
    if isinstance(x, ErrorExcel) or isinstance(y, ErrorExcel):
        return x if isinstance(x, ErrorExcel) else y
    try:
        resultado = x**y
    except (OverflowError, ZeroDivisionError):
        return NUM
    return NUM if isinstance(resultado, complex) else float(resultado)


def _no(valor):
    logico = _logico(Evaluador._escalar(valor))
    return logico if isinstance(logico, ErrorExcel) else not logico


def _buscarv(buscado, tabla, columna, aproximada=True):
    buscado = Evaluador._escalar(buscado)
    if isinstance(buscado, ErrorExcel):
        return buscado
    if not isinstance(tabla, list):
        return VALOR
    indice = _numero(Evaluador._escalar(columna))
    if isinstance(indice, ErrorExcel):
        return indice
    indice = int(indice)
    if indice < 1 or indice > len(tabla[0]):
        return ErrorExcel("#REF!")
    # Argumento omitido -> TRUE (valor por defecto); argumento vacío "VLOOKUP(x,t,2,)" -> FALSE, como en Excel.
    aproximada = _logico(Evaluador._escalar(aproximada)) if aproximada is not None else False
    if aproximada:
        candidata = None
        for fila in tabla:
            if fila[0] is None:
                continue
            if _clave_comparacion(fila[0]) <= _clave_comparacion(buscado):
                candidata = fila
            else:
                break
        return candidata[indice - 1] if candidata is not None else NA
    for fila in tabla:
        if fila[0] is not None and _comparar("=", fila[0], buscado):
            return fila[indice - 1]
    return NA


def _indice(tabla, fila, columna=None):
    if not isinstance(tabla, list):
        return VALOR
    f = _numero(Evaluador._escalar(fila))
    c = _numero(Evaluador._escalar(columna)) if columna is not None else 1.0
    if isinstance(f, ErrorExcel) or isinstance(c, ErrorExcel):
        return VALOR
    f, c = int(f) or 1, int(c) or 1
    if len(tabla) == 1 and columna is None:
        f, c = 1, f
    try:
        return tabla[f - 1][c - 1]
    except IndexError:
        return ErrorExcel("#REF!")


def _coincidir(buscado, rango, tipo=1):
    buscado = Evaluador._escalar(buscado)
    valores = _aplanar(rango)
    t = _numero(Evaluador._escalar(tipo)) if tipo is not None else 1.0
    if t == 0:
        for posicion, valor in enumerate(valores, start=1):
            if valor is not None and _comparar("=", valor, buscado):
                return float(posicion)
        return NA
    mejor = None
    for posicion, valor in enumerate(valores, start=1):
        if valor is None:
            continue
        if _clave_comparacion(valor) <= _clave_comparacion(buscado):
            mejor = posicion
    return float(mejor) if mejor else NA


_FUNCIONES: dict[str, Callable[..., Any]] = {
    "NOT": _no,
    "LN": _unaria(math.log, lambda x: x > 0),
    "LOG": _log,
    "LOG10": _unaria(math.log10, lambda x: x > 0),
    "EXP": _unaria(math.exp),
    "SQRT": _unaria(math.sqrt, lambda x: x >= 0),
    "ABS": _unaria(abs),
    "ROUND": _redondeo(ROUND_HALF_UP),
    "ROUNDUP": _redondeo(ROUND_UP),
    "ROUNDDOWN": _redondeo(ROUND_DOWN),
    "SUM": _suma,
    "AVERAGE": _promedio,
    "MIN": _minimo,
    "MAX": _maximo,
    "POWER": _potencia,
    "PI": lambda: math.pi,
    "VLOOKUP": _buscarv,
    "INDEX": _indice,
    "MATCH": _coincidir,
}

FUNCIONES_SOPORTADAS = tuple(sorted(set(_FUNCIONES) | {"IF", "IFERROR", "AND", "OR"}))
