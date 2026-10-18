"""Direcciones de celdas y rangos al estilo Excel."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any

_CELDA = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d+)$")


def columna_a_numero(letras: str) -> int:
    numero = 0
    for letra in letras.upper():
        numero = numero * 26 + (ord(letra) - ord("A") + 1)
    return numero


def numero_a_columna(numero: int) -> str:
    letras = ""
    while numero > 0:
        numero, resto = divmod(numero - 1, 26)
        letras = chr(ord("A") + resto) + letras
    return letras


def partir_celda(celda: str) -> tuple[int, int]:
    """'BZ27' -> (fila 27, columna 78)."""
    coincidencia = _CELDA.match(celda.strip())
    if not coincidencia:
        raise ValueError(f"Celda inválida: {celda!r}")
    return int(coincidencia.group(2)), columna_a_numero(coincidencia.group(1))


def celda(fila: int, columna: int) -> str:
    return f"{numero_a_columna(columna)}{fila}"


def separar(ref_completa: str) -> tuple[str, str]:
    """'Hoja!A1:B2' -> ('Hoja', 'A1:B2')."""
    if "!" not in ref_completa:
        raise ValueError(f"Referencia sin hoja: {ref_completa!r}")
    hoja, rango = ref_completa.rsplit("!", 1)
    return hoja.strip("'"), rango.replace("$", "").upper()


def matriz_rango(hoja: str, rango: str) -> list[list[str]]:
    """Expande 'I27:BZ28' a una matriz de referencias completas ('Hoja!I27', ...)."""
    rango = rango.replace("$", "").upper()
    desde, _, hasta = rango.partition(":")
    hasta = hasta or desde
    fila_1, col_1 = partir_celda(desde)
    fila_2, col_2 = partir_celda(hasta)
    fila_1, fila_2 = sorted((fila_1, fila_2))
    col_1, col_2 = sorted((col_1, col_2))
    return [[f"{hoja}!{celda(f, c)}" for c in range(col_1, col_2 + 1)] for f in range(fila_1, fila_2 + 1)]


def lista_rango(hoja: str, rango: str) -> list[str]:
    """Rango aplanado por filas."""
    return [ref for fila in matriz_rango(hoja, rango) for ref in fila]


def sha256_archivo(ruta: Path) -> str:
    digest = hashlib.sha256()
    with open(ruta, "rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 16), b""):
            digest.update(bloque)
    return digest.hexdigest()


def nombre_normalizado(valor: Any) -> str:
    """'Alpha 1 (t)' -> 'alpha_1_t'. Sin tildes, minúsculas, separador '_'."""
    texto = unicodedata.normalize("NFKD", str(valor).strip().lower())
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"[^a-z0-9]+", "_", texto)
    return re.sub(r"_+", "_", texto).strip("_")


def a_numero(valor: Any) -> float | None:
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return float(str(valor).strip().replace(",", "."))
    except ValueError:
        return None
