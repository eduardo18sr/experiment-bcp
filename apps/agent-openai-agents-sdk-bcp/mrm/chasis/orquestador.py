"""Orquestador: una skill por dimensión, en paralelo y con contexto limpio, y gobierno de la salida.

Agregar una casuística, una herramienta o una dimensión no modifica este archivo: si alguna vez hace falta,
la descomposición del dominio quedó mal hecha (framework F6, regla dura).
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from mrm.chasis.almacen import Almacen
from mrm.chasis.contexto import ContextoEjecucion
from mrm.chasis.expediente import ExpedienteAuditable, HuecoCobertura, ResultadoDimension
from mrm.chasis.guardrails import VerificadorEvidencia, aplicar_guardrails
from mrm.chasis.hitl import marcar_escalamiento
from mrm.chasis.informe import generar_informe
from mrm.chasis.politica import PoliticaTiering, filtrar_por_tier
from mrm.chasis.registro import Registro
from mrm.chasis.resolutor import ClaveResolucion, EstadoResolucion, Resolucion, resolver
from mrm.chasis.trazas import span
from mrm.contratos.control import Control
from mrm.contratos.expediente import ModeloInventario, SolicitudValidacion
from mrm.contratos.resultado import ResultadoControl, Trazabilidad, VeredictoControl, veredicto_integral
from mrm.herramientas._comun.celdas import sha256_archivo


def _sin_resultado(control: Control, motivo: str) -> ResultadoControl:
    return ResultadoControl(
        control_id=control.id, nombre=control.nombre, tipo=control.tipo, veredicto=VeredictoControl.NO_CONCLUYENTE,
        severidad=control.severidad, justificacion=motivo, limitaciones=[motivo],
    )


class Orquestador:
    def __init__(
        self,
        registro: Registro,
        politica: PoliticaTiering,
        almacen: Almacen,
        agente: dict[str, Any],
        dependencias: dict[str, Any] | None = None,
        juez: Any = None,
        max_paralelo: int = 4,
    ):
        self.registro = registro
        self.politica = politica
        self.almacen = almacen
        self.agente = agente
        self.dependencias = dependencias or {}
        self.juez = juez
        self.max_paralelo = max_paralelo

    def validar(self, expediente_id: str, solicitante: str = "sistema") -> tuple[ExpedienteAuditable, str]:
        inicio = time.perf_counter()
        directorio = self.almacen.preparar(expediente_id)
        with open(directorio / "expediente.yaml", encoding="utf-8") as archivo:
            solicitud = SolicitudValidacion.model_validate(yaml.safe_load(archivo))
        modelo = self.almacen.inventario().obtener(solicitud.modelo_id)

        obligatorias = self.politica.dimensiones_para(modelo.tier)
        ampliaciones = [d for d in solicitud.dimensiones if d not in obligatorias]
        dimensiones = obligatorias + ampliaciones
        etapa = self.agente.get("etapa_autonomia", "sombra")

        with span("validacion", {"expediente": expediente_id, "tier": modelo.tier}):
            resoluciones = [
                resolver(self.registro, ClaveResolucion(dimension=d, tipo_modelo=modelo.tipo_modelo, tier=modelo.tier, atributos=modelo.atributos))
                for d in dimensiones
            ]
            resueltas = [r for r in resoluciones if r.estado is EstadoResolucion.RESUELTA]
            with ThreadPoolExecutor(max_workers=self.max_paralelo) as grupo:
                futuros = [grupo.submit(self._ejecutar_dimension, r, solicitud, modelo, directorio) for r in resueltas]
                ejecutadas = [f.result() for f in futuros]

        verificador = VerificadorEvidencia(directorio, self.dependencias.get("conocimiento"))
        dimensiones_resultado, invocaciones, llamadas_llm = [], [], 0
        for dimension, contexto in ejecutadas:
            dimension.resultados_control = [
                marcar_escalamiento(aplicar_guardrails(r, verificador), modelo.tier, etapa, self.politica.hitl)
                for r in dimension.resultados_control
            ]
            dimensiones_resultado.append(dimension)
            if contexto is not None:
                invocaciones.extend(contexto.invocaciones)
            llamadas_llm += int(dimension.hechos.get("llamadas_juez", 0))

        huecos = [HuecoCobertura(dimension=r.clave.dimension, motivo=r.motivo) for r in resoluciones if r.estado is not EstadoResolucion.RESUELTA]
        resultados = [r for d in dimensiones_resultado for r in d.resultados_control]
        integral = veredicto_integral(resultados)
        if any(d.error for d in dimensiones_resultado):
            integral = VeredictoControl.NO_CUMPLE if integral is VeredictoControl.NO_CUMPLE else VeredictoControl.NO_CONCLUYENTE
        motivos = sorted({m for r in resultados for m in r.motivos_escalamiento})
        if huecos:
            motivos.append(f"{len(huecos)} dimensión(es) obligatoria(s) sin cobertura automática")
        if etapa == "sombra":
            motivos.append("Agente en etapa de sombra: la salida no se usa sin revisión del equipo")

        expediente = ExpedienteAuditable(
            id_validacion=f"{expediente_id}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}",
            expediente_id=expediente_id,
            fecha_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            solicitante=solicitante,
            agente={k: self.agente.get(k) for k in ("id", "version", "modelo_base")},
            modelo=modelo,
            politica_tiering=f"{self.politica.version} ({self.politica.estado})",
            etapa_autonomia=etapa,
            dimensiones_obligatorias=obligatorias,
            ampliaciones_cobertura=ampliaciones,
            huecos_cobertura=huecos,
            dimensiones=dimensiones_resultado,
            invocaciones=invocaciones,
            huellas_entradas=self._huellas(directorio),
            solicitud=solicitud.model_dump(mode="json"),
            veredicto_integral=integral,
            requiere_revision_humana=bool(motivos),
            motivos_revision=motivos,
            duracion_s=round(time.perf_counter() - inicio, 2),
            llamadas_llm=llamadas_llm,
        )
        informe = generar_informe(expediente)
        self.almacen.guardar(expediente, informe)
        return expediente, informe

    def _ejecutar_dimension(
        self, resolucion: Resolucion, solicitud: SolicitudValidacion, modelo: ModeloInventario, directorio: Path
    ) -> tuple[ResultadoDimension, ContextoEjecucion | None]:
        entrada = resolucion.entrada_skill
        catalogo = resolucion.catalogo_controles
        aplicables, excluidos = filtrar_por_tier(catalogo, modelo.tier, self.politica)
        dimension = ResultadoDimension(dimension=resolucion.clave.dimension, resolucion=resolucion.resumen(), controles_excluidos=excluidos)
        try:
            contexto = ContextoEjecucion(
                registro=self.registro, spec=entrada.spec, solicitud=solicitud, modelo=modelo, catalogo=catalogo,
                controles=aplicables, configuracion=resolucion.configuracion, dir_expediente=directorio,
                dependencias=self.dependencias, juez=self.juez,
            )
            with span(f"skill:{entrada.spec.nombre}", {"dimension": dimension.dimension}):
                resultado = entrada.clase().ejecutar(contexto)
        except Exception as error:  # noqa: BLE001 - un fallo de skill nunca se convierte en 'cumple'
            dimension.error = f"{type(error).__name__}: {error}"
            dimension.limitaciones.append(f"La skill falló: {dimension.error}")
            dimension.resultados_control = [_sin_resultado(c, f"La skill falló: {dimension.error}") for c in aplicables]
            return dimension, None

        versiones = contexto.versiones_herramientas()
        por_id = {c.id: c for c in aplicables}
        devueltos = {r.control_id for r in resultado.resultados_control}
        # Un control aplicable sin resultado nunca desaparece en silencio.
        resultado.resultados_control.extend(
            _sin_resultado(c, "La skill no devolvió resultado para este control (defecto de la skill)")
            for c in aplicables if c.id not in devueltos
        )
        dimension.resultados_control = [
            r.model_copy(update={"trazabilidad": Trazabilidad(
                skill=entrada.spec.nombre, version_skill=entrada.spec.version, catalogo=catalogo.nombre,
                version_catalogo=catalogo.version, version_control=por_id[r.control_id].version, herramientas=versiones,
            )})
            for r in resultado.resultados_control
            if r.control_id in por_id
        ]
        dimension.resultados_componentes = resultado.resultados_componentes
        dimension.hechos = resultado.hechos
        dimension.limitaciones.extend(resultado.limitaciones)
        return dimension, contexto

    @staticmethod
    def _huellas(directorio: Path) -> dict[str, str]:
        return {
            ruta.relative_to(directorio).as_posix(): sha256_archivo(ruta)
            for ruta in sorted(directorio.rglob("*"))
            if ruta.is_file() and "__pycache__" not in ruta.parts
        }
