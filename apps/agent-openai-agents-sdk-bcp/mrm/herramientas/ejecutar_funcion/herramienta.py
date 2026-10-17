"""Herramienta `ejecutar_funcion`: ejecuta la función productiva en una copia aislada (R2).

Garantías:
- Nunca toca el proyecto evaluado: trabaja sobre una copia verificada por SHA-256, archivo por archivo.
- Solo ejecuta con autorización explícita del expediente.
- Las sustituciones (variante diagnóstica) se aplican a la copia y quedan registradas en un parche auditable.
- Corre en un subproceso aislado (`python -I`) con timeout; el script ejecutor vive fuera de la copia.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mrm.contratos.herramienta import Herramienta, TipoHerramienta
from mrm.herramientas._comun.celdas import sha256_archivo

EXCLUIDOS = (".git", "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache")
RUNNER = Path(__file__).with_name("runner.py")


class Sustitucion(BaseModel):
    archivo: str = Field(description="Ruta relativa a la raíz del proyecto")
    linea: int | None = Field(default=None, description="Línea donde aplicar; None aplica a todo el archivo")
    buscar: str
    reemplazar: str


class EntradaEjecutar(BaseModel):
    raiz_proyecto: str
    funcion: str = Field(description="modulo:funcion")
    casos: list[dict[str, Any]] = Field(description="Argumentos con nombre, uno por caso")
    sustituciones: list[Sustitucion] = Field(default_factory=list)
    autorizado: bool = False
    variante: str = "activa"
    timeout_s: float = 120.0


class RegistroParche(BaseModel):
    archivo: str
    linea: int | None
    antes: str
    despues: str
    sha256_antes: str
    sha256_despues: str


class ResultadoCaso(BaseModel):
    indice: int
    ok: bool
    salida: Any = None
    error: str | None = None


class SalidaEjecutar(BaseModel):
    variante: str
    copia_verificada: bool
    original_intacto: bool
    sha256_manifiesto: str
    parche: list[RegistroParche]
    resultados: list[ResultadoCaso]
    duracion_s: float
    stderr_resumen: str = ""


def manifiesto(raiz: Path) -> dict[str, str]:
    archivos = {}
    for ruta in sorted(raiz.rglob("*")):
        relativa = ruta.relative_to(raiz)
        if ruta.is_file() and not any(parte in EXCLUIDOS for parte in relativa.parts):
            archivos[relativa.as_posix()] = sha256_archivo(ruta)
    return archivos


def hash_manifiesto(archivos: dict[str, str]) -> str:
    return hashlib.sha256("\n".join(f"{k}:{v}" for k, v in sorted(archivos.items())).encode()).hexdigest()


class EjecutarFuncion(Herramienta[EntradaEjecutar, SalidaEjecutar]):
    nombre = "ejecutar_funcion"
    version = "1.0.0"
    tipo = TipoHerramienta.DETERMINISTICO
    errores = (
        "ejecucion_no_autorizada",
        "raiz_no_encontrada",
        "copia_no_verificada",
        "sustitucion_sin_efecto",
        "timeout",
        "fallo_proceso",
    )
    Entrada = EntradaEjecutar
    Salida = SalidaEjecutar

    def ejecutar(self, entrada: EntradaEjecutar) -> SalidaEjecutar:
        if not entrada.autorizado:
            raise self.fallar("ejecucion_no_autorizada", "El expediente no autoriza ejecutar el código evaluado")
        original = Path(entrada.raiz_proyecto)
        if not original.is_dir():
            raise self.fallar("raiz_no_encontrada", f"No existe {original.name}")

        inicio = time.perf_counter()
        manifiesto_original = manifiesto(original)
        with tempfile.TemporaryDirectory(prefix="mrm_copia_") as dir_copia, tempfile.TemporaryDirectory(
            prefix="mrm_runner_"
        ) as dir_runner:
            copia = Path(dir_copia) / "proyecto"
            shutil.copytree(original, copia, ignore=shutil.ignore_patterns(*EXCLUIDOS))
            if manifiesto(copia) != manifiesto_original:
                raise self.fallar("copia_no_verificada", "La copia no coincide con el original (SHA-256)")
            parche = [self._sustituir(copia, s) for s in entrada.sustituciones]

            runner = Path(dir_runner) / "runner.py"
            shutil.copy2(RUNNER, runner)
            ruta_entrada = Path(dir_runner) / "entrada.json"
            ruta_salida = Path(dir_runner) / "salida.json"
            ruta_entrada.write_text(json.dumps({"funcion": entrada.funcion, "casos": entrada.casos}), encoding="utf-8")
            try:
                proceso = subprocess.run(
                    [sys.executable, "-I", str(runner), str(copia), str(ruta_entrada), str(ruta_salida)],
                    cwd=copia,
                    capture_output=True,
                    text=True,
                    timeout=entrada.timeout_s,
                )
            except subprocess.TimeoutExpired as error:
                raise self.fallar("timeout", f"La ejecución superó {entrada.timeout_s} s") from error
            if proceso.returncode != 0 or not ruta_salida.exists():
                ultima = (proceso.stderr or "").strip().splitlines()[-1:] or ["sin detalle"]
                raise self.fallar("fallo_proceso", f"El proceso terminó con código {proceso.returncode}: {ultima[0]}")
            resultados = json.loads(ruta_salida.read_text(encoding="utf-8"))["resultados"]

        return SalidaEjecutar(
            variante=entrada.variante,
            copia_verificada=True,
            original_intacto=manifiesto(original) == manifiesto_original,
            sha256_manifiesto=hash_manifiesto(manifiesto_original),
            parche=parche,
            resultados=[ResultadoCaso(**r) for r in resultados],
            duracion_s=round(time.perf_counter() - inicio, 3),
            stderr_resumen=(proceso.stderr or "")[-500:],
        )

    def _sustituir(self, copia: Path, sustitucion: Sustitucion) -> RegistroParche:
        ruta = copia / sustitucion.archivo
        if not ruta.is_file():
            raise self.fallar("sustitucion_sin_efecto", f"No existe {sustitucion.archivo} en la copia")
        sha_antes = sha256_archivo(ruta)
        contenido = ruta.read_bytes()
        try:
            codificacion, texto = "utf-8", contenido.decode("utf-8")
        except UnicodeDecodeError:  # código legado: se respeta su codificación original
            codificacion, texto = "latin-1", contenido.decode("latin-1")
        lineas = texto.splitlines(keepends=True)
        indices = [sustitucion.linea - 1] if sustitucion.linea else range(len(lineas))
        antes = despues = ""
        cambios = 0
        for indice in indices:
            if 0 <= indice < len(lineas) and sustitucion.buscar in lineas[indice]:
                antes = lineas[indice].rstrip("\n")
                lineas[indice] = lineas[indice].replace(sustitucion.buscar, sustitucion.reemplazar)
                despues = lineas[indice].rstrip("\n")
                cambios += 1
        if not cambios:
            raise self.fallar(
                "sustitucion_sin_efecto",
                f"'{sustitucion.buscar}' no aparece en {sustitucion.archivo}"
                + (f" línea {sustitucion.linea}" if sustitucion.linea else ""),
            )
        ruta.write_bytes("".join(lineas).encode(codificacion))
        return RegistroParche(
            archivo=sustitucion.archivo,
            linea=sustitucion.linea,
            antes=antes.strip(),
            despues=despues.strip(),
            sha256_antes=sha_antes,
            sha256_despues=sha256_archivo(ruta),
        )
