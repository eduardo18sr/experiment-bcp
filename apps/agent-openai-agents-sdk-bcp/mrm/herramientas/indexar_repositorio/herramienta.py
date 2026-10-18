"""Herramienta `indexar_repositorio`: índice de símbolos y de referencias a archivos de un proyecto Python.

Construir el índice es determinístico y barato, y reduce el trabajo de juicio a elegir entre candidatos
acotados (framework F2, paso 3). Además responde la pregunta que el AS-IS no podía (R4, R5):
qué archivos de parámetros se cargan de verdad, cuáles están comentados y cuáles dependen de rutas dinámicas.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

from pydantic import BaseModel, Field

from mrm.contratos.herramienta import Herramienta, TipoHerramienta
from mrm.contratos.repositorio import EstadoReferencia, ReferenciaArchivo
from mrm.herramientas._comun.celdas import sha256_archivo

DIRECTORIOS_EXCLUIDOS = (".git", "__pycache__", ".venv", "venv", "env", "site-packages", "node_modules", ".tox")
EXTENSIONES_DATOS = ("csv", "json", "parquet", "xlsx", "xls", "yaml", "yml", "txt", "pkl", "sas7bdat")
_ARCHIVO = re.compile(r"([\w\-.]+\.(?:" + "|".join(EXTENSIONES_DATOS) + r"))\b", re.IGNORECASE)


class EntradaIndexar(BaseModel):
    raiz: str
    excluir: list[str] = Field(default_factory=lambda: list(DIRECTORIOS_EXCLUIDOS))
    max_bytes: int = 2_000_000


class ArchivoIndexado(BaseModel):
    ruta: str
    sha256: str
    lineas: int


class FuncionIndexada(BaseModel):
    ruta: str
    modulo: str
    nombre: str
    clase: str | None = None
    linea: int
    argumentos: list[str]


class ConstanteIndexada(BaseModel):
    ruta: str
    nombre: str
    linea: int


class SalidaIndexar(BaseModel):
    archivos: list[ArchivoIndexado]
    archivos_datos: list[str] = Field(description="Archivos de datos presentes en el proyecto")
    funciones: list[FuncionIndexada]
    referencias: list[ReferenciaArchivo]
    constantes: list[ConstanteIndexada]
    advertencias: list[str]


def _modulo(relativa: Path) -> str:
    partes = list(relativa.with_suffix("").parts)
    if partes and partes[-1] == "__init__":
        partes = partes[:-1]
    return ".".join(partes)


def _patron_dinamico(nodo: ast.AST) -> str | None:
    """f"theta_{v}.csv" o "theta_" + v + ".csv" -> 'theta_*.csv' si el resultado parece un archivo de datos."""
    piezas: list[str] = []

    def visitar(n: ast.AST) -> None:
        if isinstance(n, ast.JoinedStr):
            for valor in n.values:
                if isinstance(valor, ast.Constant) and isinstance(valor.value, str):
                    piezas.append(valor.value)
                else:
                    piezas.append("*")
        elif isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            visitar(n.left)
            visitar(n.right)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            piezas.append(n.value)
        else:
            piezas.append("*")

    visitar(nodo)
    if "*" not in piezas:
        return None
    patron = re.sub(r"\*+", "*", "".join(piezas))
    nombre = patron.replace("\\", "/").rsplit("/", 1)[-1]
    if re.search(r"\.(?:" + "|".join(EXTENSIONES_DATOS) + r")$", nombre, re.IGNORECASE):
        return nombre
    return None


class IndexarRepositorio(Herramienta[EntradaIndexar, SalidaIndexar]):
    nombre = "indexar_repositorio"
    version = "1.0.0"
    tipo = TipoHerramienta.DETERMINISTICO
    errores = ("raiz_no_encontrada",)
    Entrada = EntradaIndexar
    Salida = SalidaIndexar

    def ejecutar(self, entrada: EntradaIndexar) -> SalidaIndexar:
        raiz = Path(entrada.raiz)
        if not raiz.is_dir():
            raise self.fallar("raiz_no_encontrada", f"No existe el directorio {raiz.name}")

        archivos, datos, funciones, referencias, constantes, advertencias = [], [], [], [], [], []
        for ruta in sorted(raiz.rglob("*")):
            relativa = ruta.relative_to(raiz)
            if any(parte in entrada.excluir for parte in relativa.parts) or not ruta.is_file():
                continue
            if ruta.suffix.lower().lstrip(".") in EXTENSIONES_DATOS:
                datos.append(relativa.as_posix())
                continue
            if ruta.suffix != ".py":
                continue
            if ruta.stat().st_size > entrada.max_bytes:
                advertencias.append(f"{relativa.as_posix()}: excede el tamaño máximo, no se indexa")
                continue
            fuente = ruta.read_text(encoding="utf-8", errors="replace")
            lineas = fuente.splitlines()
            archivos.append(ArchivoIndexado(ruta=relativa.as_posix(), sha256=sha256_archivo(ruta), lineas=len(lineas)))
            try:
                arbol = ast.parse(fuente)
            except SyntaxError as error:
                advertencias.append(f"{relativa.as_posix()}: no se pudo analizar ({error.msg})")
                continue
            self._indexar_arbol(arbol, relativa, lineas, funciones, referencias, constantes)
            self._indexar_comentarios(fuente, relativa, lineas, referencias)

        return SalidaIndexar(
            archivos=archivos,
            archivos_datos=datos,
            funciones=funciones,
            referencias=referencias,
            constantes=constantes,
            advertencias=advertencias,
        )

    @staticmethod
    def _indexar_arbol(arbol, relativa: Path, lineas, funciones, referencias, constantes) -> None:
        ruta = relativa.as_posix()
        modulo = _modulo(relativa)
        clases = {
            hijo: nodo.name
            for nodo in ast.walk(arbol)
            if isinstance(nodo, ast.ClassDef)
            for hijo in nodo.body
        }
        dinamicos_vistos: set[int] = set()
        # Literales que no son referencias activas: piezas de rutas dinámicas y docstrings.
        ignorados: set[int] = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.JoinedStr) or (isinstance(nodo, ast.BinOp) and isinstance(nodo.op, ast.Add)):
                ignorados.update(id(hijo) for hijo in ast.walk(nodo) if hijo is not nodo)
            elif isinstance(nodo, ast.Expr) and isinstance(nodo.value, ast.Constant):
                ignorados.add(id(nodo.value))
        for nodo in ast.walk(arbol):
            if id(nodo) in ignorados and isinstance(nodo, ast.Constant):
                continue
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funciones.append(
                    FuncionIndexada(
                        ruta=ruta,
                        modulo=modulo,
                        nombre=nodo.name,
                        clase=clases.get(nodo),
                        linea=nodo.lineno,
                        argumentos=[a.arg for a in nodo.args.args],
                    )
                )
            elif isinstance(nodo, ast.Assign) and nodo in arbol.body:
                for objetivo in nodo.targets:
                    if isinstance(objetivo, ast.Name) and objetivo.id.isupper():
                        constantes.append(ConstanteIndexada(ruta=ruta, nombre=objetivo.id, linea=nodo.lineno))
            elif isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
                for coincidencia in _ARCHIVO.finditer(nodo.value):
                    referencias.append(
                        ReferenciaArchivo(
                            ruta=ruta,
                            linea=nodo.lineno,
                            texto=lineas[nodo.lineno - 1].strip(),
                            objetivo=coincidencia.group(1).replace("\\", "/").rsplit("/", 1)[-1],
                            estado=EstadoReferencia.ACTIVO,
                        )
                    )
            elif isinstance(nodo, (ast.JoinedStr, ast.BinOp)) and nodo.lineno not in dinamicos_vistos:
                patron = _patron_dinamico(nodo)
                if patron:
                    dinamicos_vistos.add(nodo.lineno)
                    referencias.append(
                        ReferenciaArchivo(
                            ruta=ruta,
                            linea=nodo.lineno,
                            texto=lineas[nodo.lineno - 1].strip(),
                            objetivo=patron,
                            estado=EstadoReferencia.DINAMICO,
                        )
                    )

    @staticmethod
    def _indexar_comentarios(fuente: str, relativa: Path, lineas, referencias) -> None:
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(fuente).readline))
        except (tokenize.TokenError, IndentationError):
            return
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            for coincidencia in _ARCHIVO.finditer(token.string):
                linea = token.start[0]
                referencias.append(
                    ReferenciaArchivo(
                        ruta=relativa.as_posix(),
                        linea=linea,
                        texto=lineas[linea - 1].strip(),
                        objetivo=coincidencia.group(1).replace("\\", "/").rsplit("/", 1)[-1],
                        estado=EstadoReferencia.COMENTADO,
                    )
                )
