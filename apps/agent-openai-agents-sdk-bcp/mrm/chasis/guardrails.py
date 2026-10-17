"""Guardrails de salida, en código (framework F5).

El agente validador es de solo lectura: su riesgo no está en las acciones sino en las afirmaciones.
- Toda cita debe existir literalmente en su fuente; si no, el control se marca no sustentado y escala.
- 'cumple' sin evidencia verificable no se acepta.
- La salida se valida contra el esquema del contrato (lo hacen los modelos pydantic al construirse).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mrm.contratos.resultado import Evidencia, ResultadoControl, TipoEvidencia, VeredictoControl
from mrm.herramientas._comun.celdas import separar


class VerificadorEvidencia:
    def __init__(self, dir_expediente: Path, consultor_conocimiento: Any = None):
        self.dir = dir_expediente.resolve()
        self.consultor = consultor_conocimiento
        self._libros: dict[str, Any] = {}

    def _ruta(self, relativa: str) -> Path | None:
        ruta = (self.dir / relativa).resolve()
        return ruta if (self.dir in ruta.parents and ruta.exists()) else None

    def _celdas(self, relativa: str) -> set[str] | None:
        if relativa not in self._libros:
            ruta = self._ruta(relativa)
            if ruta is None:
                self._libros[relativa] = None
            else:
                import openpyxl

                libro = openpyxl.load_workbook(ruta, read_only=False)
                self._libros[relativa] = {f"{h}!{c.coordinate}" for h in libro.sheetnames for fila in libro[h].iter_rows() for c in fila if c.value is not None}
        return self._libros[relativa]

    def verificar(self, evidencia: Evidencia) -> str | None:
        """Devuelve None si la evidencia es verificable, o el motivo por el que no lo es."""
        if evidencia.tipo is TipoEvidencia.HECHO:
            return None
        if evidencia.tipo is TipoEvidencia.CELDA:
            celdas = self._celdas(evidencia.fuente)
            if celdas is None:
                return f"No existe el archivo {evidencia.fuente}"
            hoja, rango = separar(evidencia.ubicacion)
            primera = rango.split(":")[0]
            return None if f"{hoja}!{primera}" in celdas else f"La celda {hoja}!{primera} no existe en {evidencia.fuente}"
        if evidencia.tipo is TipoEvidencia.ARCHIVO:
            return None if self._ruta(evidencia.fuente) else f"No existe el archivo {evidencia.fuente}"
        if evidencia.tipo is TipoEvidencia.LINEA_CODIGO:
            ruta = self._ruta(evidencia.fuente)
            if ruta is None:
                return f"No existe el archivo {evidencia.fuente}"
            lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
            try:
                numero = int(evidencia.ubicacion)
            except ValueError:
                return f"Ubicación de línea inválida: {evidencia.ubicacion}"
            if not 1 <= numero <= len(lineas):
                return f"{evidencia.fuente} no tiene la línea {numero}"
            if evidencia.cita and " ".join(evidencia.cita.split()) not in " ".join(lineas[numero - 1].split()):
                return f"La cita no aparece literalmente en {evidencia.fuente}:{numero}"
            return None
        if evidencia.tipo is TipoEvidencia.NOTA_CONOCIMIENTO:
            if self.consultor is None:
                return "No hay grafo de conocimiento para verificar la cita"
            if not evidencia.cita or not self.consultor.cita_existe(evidencia.fuente, evidencia.cita):
                return f"La cita no aparece literalmente en la nota [[{evidencia.fuente}]]"
            return None
        return f"Tipo de evidencia no verificable: {evidencia.tipo}"


def aplicar_guardrails(resultado: ResultadoControl, verificador: VerificadorEvidencia) -> ResultadoControl:
    if resultado.veredicto is None:
        return resultado
    fallos = [m for e in resultado.evidencia if (m := verificador.verificar(e))]
    if not fallos:
        return resultado
    datos = resultado.model_dump()
    datos["veredicto"] = VeredictoControl.NO_CONCLUYENTE
    datos["limitaciones"] = resultado.limitaciones + [f"Evidencia no sustentada: {m}" for m in fallos]
    datos["justificacion"] = f"[Veredicto original '{resultado.veredicto.value}' anulado por el guardrail de evidencia] {resultado.justificacion}"
    datos["evidencia"] = [e for e in resultado.evidencia if verificador.verificar(e) is None]
    return ResultadoControl.model_validate(datos)
