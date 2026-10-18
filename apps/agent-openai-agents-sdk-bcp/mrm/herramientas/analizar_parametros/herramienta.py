"""Herramienta `analizar_parametros`: cruza tablas de parámetros de la referencia con los archivos del proyecto.

Responde, por archivo candidato, dos preguntas independientes (R4–R7):
- uso: ¿el código lo carga (ACTIVO), solo lo menciona en un comentario (COMENTADO), lo construye
  dinámicamente (DINAMICO) o no lo referencia (NO_REFERENCIADO)?
- coincidencia: ¿sus valores reproducen la tabla de la referencia (COINCIDE, NO_COINCIDE, NO_COMPARABLE)?
Compara también tablas sin fórmulas y tablas anchas, orientadas por filas o por columnas.
"""

from __future__ import annotations

import csv
import fnmatch
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from mrm.contratos.canonico import LibroCanonico
from mrm.contratos.herramienta import Herramienta, TipoHerramienta
from mrm.herramientas._comun.celdas import a_numero, matriz_rango, nombre_normalizado
from mrm.contratos.repositorio import EstadoReferencia, ReferenciaArchivo

COBERTURA_MINIMA = 0.5
MAX_DIFERENCIAS = 25


class EspecTabla(BaseModel):
    id: str
    hoja: str
    rango: str
    orientacion: Literal["filas", "columnas"]
    clave: str
    archivos: str
    clave_archivo: str | None = None


class ToleranciaParametros(BaseModel):
    absoluta: float
    relativa: float = 0.0


class EntradaAnalizarParametros(BaseModel):
    libro: LibroCanonico
    tablas: list[EspecTabla]
    raiz_proyecto: str
    referencias: list[ReferenciaArchivo]
    tolerancia: ToleranciaParametros


class Diferencia(BaseModel):
    clave: str
    nombre: str
    valor_referencia: Any
    valor_archivo: Any


class AnalisisArchivo(BaseModel):
    ruta: str
    uso: Literal["ACTIVO", "COMENTADO", "DINAMICO", "NO_REFERENCIADO"]
    referencias: list[ReferenciaArchivo] = Field(default_factory=list)
    coincidencia: Literal["COINCIDE", "NO_COINCIDE", "NO_COMPARABLE"]
    clasificacion: str
    cobertura_nombres: float
    comparados: int
    coincidencias: int
    faltantes: int
    max_dif_abs: float | None
    diferencias: list[Diferencia] = Field(default_factory=list)


class AnalisisTabla(BaseModel):
    id: str
    registros_referencia: int
    nombres_referencia: list[str]
    archivos: list[AnalisisArchivo]
    advertencias: list[str] = Field(default_factory=list)


class SalidaAnalizarParametros(BaseModel):
    tablas: list[AnalisisTabla]


def _clave(valor: Any) -> str:
    numero = a_numero(valor)
    if numero is not None:
        return repr(float(numero))
    return nombre_normalizado(valor)


def tabla_referencia(libro: LibroCanonico, espec: EspecTabla) -> dict[tuple[str, str], Any]:
    """Normaliza la tabla de la referencia a {(clave, nombre): valor}."""
    matriz = [[libro.celdas[r].valor if r in libro.celdas else None for r in fila] for fila in matriz_rango(espec.hoja, espec.rango)]
    registros: dict[tuple[str, str], Any] = {}
    if espec.orientacion == "filas":
        claves = matriz[0][1:]
        for fila in matriz[1:]:
            nombre = nombre_normalizado(fila[0])
            for clave, valor in zip(claves, fila[1:]):
                if clave is not None and nombre:
                    registros[(_clave(clave), nombre)] = valor
    else:
        encabezados = [nombre_normalizado(h) for h in matriz[0]]
        clave_norm = nombre_normalizado(espec.clave)
        if clave_norm not in encabezados:
            raise ValueError(f"La tabla {espec.id} no tiene la columna clave {espec.clave!r}")
        indice_clave = encabezados.index(clave_norm)
        for fila in matriz[1:]:
            if fila[indice_clave] is None:
                continue
            for indice, (nombre, valor) in enumerate(zip(encabezados, fila)):
                if indice != indice_clave and nombre:
                    registros[(_clave(fila[indice_clave]), nombre)] = valor
    return registros


def tabla_archivo(ruta: Path, clave: str) -> dict[tuple[str, str], Any] | None:
    with open(ruta, newline="", encoding="utf-8-sig") as archivo:
        lector = csv.DictReader(archivo)
        if not lector.fieldnames:
            return None
        encabezados = {nombre_normalizado(h): h for h in lector.fieldnames}
        clave_norm = nombre_normalizado(clave)
        if clave_norm not in encabezados:
            return None
        registros: dict[tuple[str, str], Any] = {}
        for fila in lector:
            valor_clave = fila[encabezados[clave_norm]]
            for nombre, original in encabezados.items():
                if nombre != clave_norm:
                    registros[(_clave(valor_clave), nombre)] = fila[original]
        return registros


def _uso(nombre_archivo: str, referencias: list[ReferenciaArchivo]) -> tuple[str, list[ReferenciaArchivo]]:
    propias = [r for r in referencias if r.estado is not EstadoReferencia.DINAMICO and r.objetivo == nombre_archivo]
    dinamicas = [r for r in referencias if r.estado is EstadoReferencia.DINAMICO and fnmatch.fnmatch(nombre_archivo, r.objetivo)]
    if any(r.estado is EstadoReferencia.ACTIVO for r in propias):
        return "ACTIVO", propias
    if dinamicas:
        return "DINAMICO", dinamicas + propias
    if propias:
        return "COMENTADO", propias
    return "NO_REFERENCIADO", []


def _clasificar(uso: str, coincidencia: str) -> str:
    if coincidencia == "NO_COMPARABLE":
        return "NO_COMPARABLE"
    if uso == "DINAMICO":
        return "USO_DINAMICO_INDETERMINADO"
    if uso == "ACTIVO":
        return "SE_USA_Y_COINCIDE" if coincidencia == "COINCIDE" else "SE_USA_SIN_COINCIDENCIA"
    return "COINCIDE_PERO_NO_SE_USA" if coincidencia == "COINCIDE" else "NO_SE_USA_NI_COINCIDE"


class AnalizarParametros(Herramienta[EntradaAnalizarParametros, SalidaAnalizarParametros]):
    nombre = "analizar_parametros"
    version = "1.0.0"
    tipo = TipoHerramienta.DETERMINISTICO
    errores = ("tabla_invalida", "raiz_no_encontrada")
    Entrada = EntradaAnalizarParametros
    Salida = SalidaAnalizarParametros

    def ejecutar(self, entrada: EntradaAnalizarParametros) -> SalidaAnalizarParametros:
        raiz = Path(entrada.raiz_proyecto)
        if not raiz.is_dir():
            raise self.fallar("raiz_no_encontrada", f"No existe {raiz.name}")
        return SalidaAnalizarParametros(tablas=[self._analizar_tabla(entrada, espec, raiz) for espec in entrada.tablas])

    def _analizar_tabla(self, entrada, espec: EspecTabla, raiz: Path) -> AnalisisTabla:
        try:
            referencia = tabla_referencia(entrada.libro, espec)
        except (ValueError, KeyError) as error:
            raise self.fallar("tabla_invalida", str(error)) from error
        nombres = sorted({nombre for _, nombre in referencia})
        analisis = AnalisisTabla(id=espec.id, registros_referencia=len(referencia), nombres_referencia=nombres, archivos=[])
        candidatos = sorted(p for p in raiz.glob(espec.archivos) if p.is_file() and p.suffix.lower() == ".csv")
        if not candidatos:
            analisis.advertencias.append(f"Ningún archivo coincide con {espec.archivos}")
        for ruta in candidatos:
            analisis.archivos.append(self._analizar_archivo(entrada, espec, referencia, nombres, ruta, raiz))
        return analisis

    def _analizar_archivo(self, entrada, espec, referencia, nombres, ruta: Path, raiz: Path) -> AnalisisArchivo:
        uso, referencias = _uso(ruta.name, entrada.referencias)
        archivo = tabla_archivo(ruta, espec.clave_archivo or espec.clave)
        nombres_archivo = {nombre for _, nombre in archivo} if archivo else set()
        cobertura = len(set(nombres) & nombres_archivo) / len(nombres) if nombres else 0.0
        base = dict(ruta=ruta.relative_to(raiz).as_posix(), uso=uso, referencias=referencias, cobertura_nombres=cobertura)
        if archivo is None or cobertura < COBERTURA_MINIMA:
            return AnalisisArchivo(
                **base, coincidencia="NO_COMPARABLE", clasificacion="NO_COMPARABLE",
                comparados=0, coincidencias=0, faltantes=len(referencia), max_dif_abs=None,
            )

        tol = entrada.tolerancia
        comparados = coincidencias = faltantes = 0
        max_dif: float | None = None
        diferencias: list[Diferencia] = []
        for (clave, nombre), valor_ref in sorted(referencia.items()):
            if (clave, nombre) not in archivo:
                faltantes += 1
                continue
            valor_arch = archivo[(clave, nombre)]
            num_ref, num_arch = a_numero(valor_ref), a_numero(valor_arch)
            comparados += 1
            if num_ref is not None and num_arch is not None:
                dif = abs(num_ref - num_arch)
                max_dif = dif if max_dif is None else max(max_dif, dif)
                igual = dif <= max(tol.absoluta, tol.relativa * max(abs(num_ref), abs(num_arch)))
            else:
                igual = nombre_normalizado(valor_ref) == nombre_normalizado(valor_arch)
            if igual:
                coincidencias += 1
            elif len(diferencias) < MAX_DIFERENCIAS:
                diferencias.append(Diferencia(clave=clave, nombre=nombre, valor_referencia=valor_ref, valor_archivo=valor_arch))

        coincide = comparados > 0 and coincidencias == comparados and faltantes == 0
        coincidencia = "COINCIDE" if coincide else "NO_COINCIDE"
        return AnalisisArchivo(
            **base,
            coincidencia=coincidencia,
            clasificacion=_clasificar(uso, coincidencia),
            comparados=comparados,
            coincidencias=coincidencias,
            faltantes=faltantes,
            max_dif_abs=max_dif,
            diferencias=diferencias,
        )
