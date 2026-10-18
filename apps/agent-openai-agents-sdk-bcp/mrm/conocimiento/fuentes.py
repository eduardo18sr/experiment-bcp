"""Adaptadores de origen del grafo y de semillas semánticas (Databricks)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mrm.conocimiento.ingesta_obsidian import ingerir_boveda
from mrm.conocimiento.modelo import Grafo

logger = logging.getLogger(__name__)


def cargar_grafo(origen: str) -> Grafo:
    """Carga el grafo desde una bóveda local, un `grafo.json` local o un `grafo.json` en un Volume de UC."""
    ruta = Path(origen)
    if ruta.is_dir():
        return ingerir_boveda(ruta)
    if ruta.is_file():
        return Grafo.cargar(ruta)
    if origen.startswith("/Volumes/"):
        from databricks.sdk import WorkspaceClient

        contenido = WorkspaceClient().files.download(origen).contents.read()
        return Grafo.model_validate(json.loads(contenido))
    raise FileNotFoundError(f"No se encontró el grafo de conocimiento en {origen}")


class BuscadorVectorSearch:
    """Semillas semánticas desde un índice de Mosaic AI Vector Search sobre la tabla `kg_fragmentos`."""

    def __init__(self, indice: str, columna_id: str = "id"):
        from databricks.sdk import WorkspaceClient

        self.indice = indice
        self.columna_id = columna_id
        self.cliente = WorkspaceClient()

    def buscar(self, consulta: str, k: int) -> list[tuple[str, float]]:
        try:
            respuesta = self.cliente.vector_search_indexes.query_index(
                index_name=self.indice, columns=[self.columna_id], query_text=consulta, num_results=k
            )
        except Exception:  # noqa: BLE001 - la recuperación semántica es auxiliar: se degrada a léxica
            logger.warning("Vector Search no disponible; se usa solo recuperación léxica", exc_info=True)
            return []
        filas = (respuesta.result.data_array if respuesta.result else None) or []
        # Cada fila trae las columnas pedidas y, al final, el puntaje de similitud.
        return [(str(fila[0]), float(fila[-1])) for fila in filas]
