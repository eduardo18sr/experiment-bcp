"""Fachada de la plataforma: el único punto de entrada para la API, el agente conversacional y los jobs.

Configuración por variables de entorno (nunca rutas ni secretos en el código):
- MRM_RAIZ_EXPEDIENTES  carpeta o Volume con los expedientes e `inventario.yaml`. Sin valor: modo demo con casos sintéticos.
- MRM_RAIZ_RESULTADOS   carpeta o Volume donde se guardan expedientes auditables e informes.
- MRM_GRAFO             bóveda Obsidian, `grafo.json` local o `grafo.json` en un Volume. Sin valor: bóveda demo.
- MRM_INDICE_VECTORIAL  índice de Vector Search sobre `kg_fragmentos` (opcional).
- MRM_JUEZ_HABILITADO   "true" para usar el juez LLM en controles de juicio.
- MRM_ENDPOINT_JUEZ     endpoint de Model Serving del juez.
"""

from __future__ import annotations

import functools
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from mrm.chasis.almacen import crear_almacen
from mrm.chasis.expediente import ExpedienteAuditable
from mrm.chasis.orquestador import Orquestador
from mrm.chasis.politica import PoliticaTiering
from mrm.chasis.registro import RAIZ_MRM, ErrorRegistro, Registro

logger = logging.getLogger(__name__)
RAIZ_APP = RAIZ_MRM.parent
BOVEDA_DEMO = RAIZ_APP / "evals" / "conocimiento_demo"


class Configuracion(BaseModel):
    raiz_expedientes: str
    raiz_resultados: str
    origen_grafo: str | None = None
    indice_vectorial: str | None = None
    juez_habilitado: bool = False
    endpoint_juez: str = "databricks-claude-sonnet-5-5"
    modo_demo: bool = False

    @classmethod
    def desde_entorno(cls) -> "Configuracion":
        raiz_expedientes = os.environ.get("MRM_RAIZ_EXPEDIENTES")
        modo_demo = not raiz_expedientes
        if modo_demo:
            from evals.sintetico.generador import generar_casos

            raiz_expedientes = tempfile.mkdtemp(prefix="mrm_demo_")
            generar_casos(Path(raiz_expedientes))
            logger.info("Modo demo: expedientes sintéticos generados en %s", raiz_expedientes)
        return cls(
            raiz_expedientes=raiz_expedientes,
            raiz_resultados=os.environ.get("MRM_RAIZ_RESULTADOS") or tempfile.mkdtemp(prefix="mrm_resultados_"),
            origen_grafo=os.environ.get("MRM_GRAFO") or (str(BOVEDA_DEMO) if BOVEDA_DEMO.is_dir() else None),
            indice_vectorial=os.environ.get("MRM_INDICE_VECTORIAL") or None,
            juez_habilitado=os.environ.get("MRM_JUEZ_HABILITADO", "false").lower() in ("1", "true", "si", "sí"),
            endpoint_juez=os.environ.get("MRM_ENDPOINT_JUEZ", "databricks-claude-sonnet-5-5"),
            modo_demo=modo_demo,
        )


def _agente(agente_id: str = "validador-implementacion") -> dict[str, Any]:
    with open(RAIZ_MRM / "registro" / "agentes.yaml", encoding="utf-8") as archivo:
        agentes = yaml.safe_load(archivo)["agentes"]
    return next(a for a in agentes if a["id"] == agente_id)


class Plataforma:
    def __init__(self, configuracion: Configuracion, juez: Any = None, consultor: Any = None):
        self.configuracion = configuracion
        self.registro = Registro()
        defectos = self.registro.verificar_integridad()
        if defectos:
            raise ErrorRegistro("Registro inconsistente:\n- " + "\n- ".join(defectos))
        self.politica = PoliticaTiering.cargar()
        self.almacen = crear_almacen(configuracion.raiz_expedientes, configuracion.raiz_resultados)
        self.consultor = consultor if consultor is not None else self._crear_consultor()
        if juez is None and configuracion.juez_habilitado:
            from mrm.juicio.juez_databricks import JuezAgentesDatabricks

            juez = JuezAgentesDatabricks(configuracion.endpoint_juez)
        self.juez = juez
        self.agente = _agente()
        self.orquestador = Orquestador(
            registro=self.registro,
            politica=self.politica,
            almacen=self.almacen,
            agente=self.agente,
            dependencias={"conocimiento": self.consultor},
            juez=self.juez,
        )

    def _crear_consultor(self):
        if not self.configuracion.origen_grafo:
            return None
        from mrm.conocimiento.consulta import ConsultorGrafo
        from mrm.conocimiento.fuentes import BuscadorVectorSearch, cargar_grafo

        try:
            grafo = cargar_grafo(self.configuracion.origen_grafo)
        except Exception:  # noqa: BLE001 - sin grafo, los controles de juicio quedan no concluyentes
            logger.warning("No se pudo cargar el grafo de conocimiento", exc_info=True)
            return None
        semantico = BuscadorVectorSearch(self.configuracion.indice_vectorial) if self.configuracion.indice_vectorial else None
        return ConsultorGrafo(grafo, semantico)

    # --- operaciones ------------------------------------------------------------------------------------
    def listar_expedientes(self) -> list[dict]:
        return [e.model_dump() for e in self.almacen.listar_expedientes()]

    def validar(self, expediente_id: str, solicitante: str = "sistema") -> tuple[ExpedienteAuditable, str]:
        return self.orquestador.validar(expediente_id, solicitante)

    def obtener_validacion(self, id_validacion: str) -> ExpedienteAuditable | None:
        return self.almacen.obtener(id_validacion)

    def informe(self, id_validacion: str) -> str | None:
        return self.almacen.informe(id_validacion)

    def listar_validaciones(self) -> list[dict]:
        return self.almacen.listar_validaciones()

    def capacidades(self) -> dict[str, Any]:
        return {
            "agente": self.agente,
            "politica_tiering": self.politica.model_dump(),
            "juez": getattr(self.juez, "nombre", None),
            "grafo_conocimiento": {
                "disponible": self.consultor is not None,
                "notas": len(self.consultor.grafo.nodos) if self.consultor else 0,
                "busqueda_semantica": bool(self.configuracion.indice_vectorial),
            },
            "modo_demo": self.configuracion.modo_demo,
            **self.registro.describir(),
        }

    def buscar_conocimiento(self, consulta: str, k: int = 5) -> list[dict]:
        if self.consultor is None:
            return []
        return [p.model_dump() for p in self.consultor.buscar(consulta, k)]


@functools.lru_cache(maxsize=1)
def obtener_plataforma() -> Plataforma:
    return Plataforma(Configuracion.desde_entorno())
