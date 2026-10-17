"""Almacenamiento de expedientes, inventario y resultados.

Dos adaptadores con la misma interfaz: carpeta local (tests, desarrollo, Volumes montados) y Volumes de
Unity Catalog vía Files API (Databricks Apps, donde los Volumes no están montados como sistema de archivos).
"""

from __future__ import annotations

import io
import re
import tempfile
from pathlib import Path
from typing import Protocol

import yaml
from pydantic import BaseModel

from mrm.chasis.expediente import ExpedienteAuditable
from mrm.contratos.expediente import ModeloInventario

_ID_SEGURO = re.compile(r"^[A-Za-z0-9_\-\.]+$")


class ErrorAlmacen(Exception):
    pass


def _validar_id(identificador: str) -> str:
    if not _ID_SEGURO.match(identificador) or identificador in (".", ".."):
        raise ErrorAlmacen(f"Identificador inválido: {identificador!r}")
    return identificador


class ResumenExpediente(BaseModel):
    id: str
    modelo_id: str
    descripcion: str = ""


class InventarioModelos:
    """Inventario MRM: la única fuente del tier y del tipo de modelo."""

    def __init__(self, modelos: list[ModeloInventario]):
        self._modelos = {m.id: m for m in modelos}

    @classmethod
    def desde_texto(cls, texto: str) -> "InventarioModelos":
        datos = yaml.safe_load(texto) or {}
        return cls([ModeloInventario.model_validate(m) for m in datos.get("modelos", [])])

    def obtener(self, modelo_id: str) -> ModeloInventario:
        if modelo_id not in self._modelos:
            raise ErrorAlmacen(f"El modelo {modelo_id} no está en el inventario: no se puede determinar su tier")
        return self._modelos[modelo_id]


class Almacen(Protocol):
    def listar_expedientes(self) -> list[ResumenExpediente]: ...
    def preparar(self, expediente_id: str) -> Path: ...
    def inventario(self) -> InventarioModelos: ...
    def guardar(self, expediente: ExpedienteAuditable, informe: str) -> None: ...
    def obtener(self, id_validacion: str) -> ExpedienteAuditable | None: ...
    def informe(self, id_validacion: str) -> str | None: ...
    def listar_validaciones(self) -> list[dict]: ...


def _resumen(id_expediente: str, texto_yaml: str) -> ResumenExpediente:
    datos = yaml.safe_load(texto_yaml) or {}
    return ResumenExpediente(id=datos.get("id", id_expediente), modelo_id=datos.get("modelo_id", "?"), descripcion=datos.get("descripcion", ""))


def _resumen_validacion(expediente: ExpedienteAuditable) -> dict:
    return {
        "id_validacion": expediente.id_validacion,
        "expediente_id": expediente.expediente_id,
        "fecha_utc": expediente.fecha_utc,
        "veredicto_integral": expediente.veredicto_integral.value if expediente.veredicto_integral else None,
        "conteos": expediente.conteos(),
    }


class AlmacenLocal:
    def __init__(self, raiz_expedientes: Path, raiz_resultados: Path):
        self.raiz_expedientes = Path(raiz_expedientes)
        self.raiz_resultados = Path(raiz_resultados)

    def listar_expedientes(self) -> list[ResumenExpediente]:
        return [
            _resumen(carpeta.name, (carpeta / "expediente.yaml").read_text(encoding="utf-8"))
            for carpeta in sorted(self.raiz_expedientes.iterdir())
            if (carpeta / "expediente.yaml").is_file()
        ]

    def preparar(self, expediente_id: str) -> Path:
        carpeta = self.raiz_expedientes / _validar_id(expediente_id)
        if not (carpeta / "expediente.yaml").is_file():
            raise ErrorAlmacen(f"No existe el expediente {expediente_id}")
        return carpeta

    def inventario(self) -> InventarioModelos:
        return InventarioModelos.desde_texto((self.raiz_expedientes / "inventario.yaml").read_text(encoding="utf-8"))

    def guardar(self, expediente: ExpedienteAuditable, informe: str) -> None:
        carpeta = self.raiz_resultados / _validar_id(expediente.id_validacion)
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "expediente.json").write_text(expediente.model_dump_json(indent=2), encoding="utf-8")
        (carpeta / "informe.md").write_text(informe, encoding="utf-8")

    def obtener(self, id_validacion: str) -> ExpedienteAuditable | None:
        ruta = self.raiz_resultados / _validar_id(id_validacion) / "expediente.json"
        return ExpedienteAuditable.model_validate_json(ruta.read_text(encoding="utf-8")) if ruta.is_file() else None

    def informe(self, id_validacion: str) -> str | None:
        ruta = self.raiz_resultados / _validar_id(id_validacion) / "informe.md"
        return ruta.read_text(encoding="utf-8") if ruta.is_file() else None

    def listar_validaciones(self) -> list[dict]:
        if not self.raiz_resultados.is_dir():
            return []
        resultados = []
        for carpeta in self.raiz_resultados.iterdir():
            expediente = self.obtener(carpeta.name) if (carpeta / "expediente.json").is_file() else None
            if expediente:
                resultados.append(_resumen_validacion(expediente))
        return sorted(resultados, key=lambda r: r["fecha_utc"], reverse=True)


class AlmacenVolumenUC:
    """Volumes de Unity Catalog vía Files API. Los expedientes se descargan a una caché local antes de validar."""

    def __init__(self, raiz_expedientes: str, raiz_resultados: str, cliente=None):
        from databricks.sdk import WorkspaceClient

        self.raiz_expedientes = raiz_expedientes.rstrip("/")
        self.raiz_resultados = raiz_resultados.rstrip("/")
        self.cliente = cliente or WorkspaceClient()
        self.cache = Path(tempfile.mkdtemp(prefix="mrm_expedientes_"))

    def _leer(self, ruta: str) -> bytes:
        return self.cliente.files.download(ruta).contents.read()

    def _escribir(self, ruta: str, contenido: bytes) -> None:
        self.cliente.files.upload(ruta, io.BytesIO(contenido), overwrite=True)

    def _descargar_arbol(self, remoto: str, local: Path) -> None:
        local.mkdir(parents=True, exist_ok=True)
        for entrada in self.cliente.files.list_directory_contents(remoto):
            destino = local / entrada.name
            if entrada.is_directory:
                self._descargar_arbol(entrada.path, destino)
            else:
                destino.write_bytes(self._leer(entrada.path))

    def listar_expedientes(self) -> list[ResumenExpediente]:
        resumenes = []
        for entrada in self.cliente.files.list_directory_contents(self.raiz_expedientes):
            if entrada.is_directory:
                try:
                    resumenes.append(_resumen(entrada.name, self._leer(f"{entrada.path}/expediente.yaml").decode("utf-8")))
                except Exception:  # noqa: BLE001 - carpetas sin expediente se ignoran
                    continue
        return sorted(resumenes, key=lambda r: r.id)

    def preparar(self, expediente_id: str) -> Path:
        destino = self.cache / _validar_id(expediente_id)
        self._descargar_arbol(f"{self.raiz_expedientes}/{expediente_id}", destino)
        if not (destino / "expediente.yaml").is_file():
            raise ErrorAlmacen(f"No existe el expediente {expediente_id}")
        return destino

    def inventario(self) -> InventarioModelos:
        return InventarioModelos.desde_texto(self._leer(f"{self.raiz_expedientes}/inventario.yaml").decode("utf-8"))

    def guardar(self, expediente: ExpedienteAuditable, informe: str) -> None:
        base = f"{self.raiz_resultados}/{_validar_id(expediente.id_validacion)}"
        self._escribir(f"{base}/expediente.json", expediente.model_dump_json(indent=2).encode("utf-8"))
        self._escribir(f"{base}/informe.md", informe.encode("utf-8"))

    def obtener(self, id_validacion: str) -> ExpedienteAuditable | None:
        try:
            contenido = self._leer(f"{self.raiz_resultados}/{_validar_id(id_validacion)}/expediente.json")
        except Exception:  # noqa: BLE001
            return None
        return ExpedienteAuditable.model_validate_json(contenido)

    def informe(self, id_validacion: str) -> str | None:
        try:
            return self._leer(f"{self.raiz_resultados}/{_validar_id(id_validacion)}/informe.md").decode("utf-8")
        except Exception:  # noqa: BLE001
            return None

    def listar_validaciones(self) -> list[dict]:
        resultados = []
        try:
            entradas = list(self.cliente.files.list_directory_contents(self.raiz_resultados))
        except Exception:  # noqa: BLE001
            return []
        for entrada in entradas:
            expediente = self.obtener(entrada.name) if entrada.is_directory else None
            if expediente:
                resultados.append(_resumen_validacion(expediente))
        return sorted(resultados, key=lambda r: r["fecha_utc"], reverse=True)


def crear_almacen(raiz_expedientes: str, raiz_resultados: str) -> Almacen:
    if raiz_expedientes.startswith("/Volumes/") and not Path(raiz_expedientes).exists():
        return AlmacenVolumenUC(raiz_expedientes, raiz_resultados)
    return AlmacenLocal(Path(raiz_expedientes), Path(raiz_resultados))
