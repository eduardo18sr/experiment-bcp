"""Arnés de evaluación (framework F0, plano 3): corre casos etiquetados contra una versión del agente.

Métricas del área, definidas una sola vez para que signifiquen lo mismo en todos los agentes:
- recall_hallazgos_criticos: de los controles etiquetados no_cumple con severidad Alta, cuántos detecta.
- precision_no_cumple: de los no_cumple que emite, cuántos están etiquetados no_cumple.
- fidelidad_evidencia: fracción de controles cuya evidencia no tuvo que anular el guardrail.
- exactitud_deterministicos: veredicto exacto en controles determinísticos.
Los controles de juicio solo se miden si hay juez configurado; si no, se informan como no evaluados.

Uso:  python -m evals.harness [--etiquetas RUTA] [--expedientes RUTA] [--mlflow]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

RAIZ = Path(__file__).resolve().parent


def _etiqueta_obtenida(expediente, control_id: str) -> str:
    excluidos = {c.control_id for d in expediente.dimensiones for c in d.controles_excluidos}
    if control_id in excluidos:
        return "excluido"
    for resultado in expediente.resultados():
        if resultado.control_id == control_id:
            return resultado.veredicto.value if resultado.veredicto else "no_aplica"
    return "ausente"


def evaluar(plataforma, etiquetas: dict[str, dict[str, str]]) -> dict[str, Any]:
    detalle, criticos, detectados, emitidos, emitidos_ok, exactos, total_det, anulados, con_evidencia = [], 0, 0, 0, 0, 0, 0, 0, 0
    juicio_no_evaluado = []
    for caso, esperadas in etiquetas.items():
        expediente, _ = plataforma.validar(caso, solicitante="arnes-evaluacion")
        controles = {r.control_id: r for r in expediente.resultados()}
        for control_id, esperada in esperadas.items():
            obtenida = _etiqueta_obtenida(expediente, control_id)
            resultado = controles.get(control_id)
            es_juicio = resultado is not None and resultado.tipo.value == "juicio"
            if es_juicio and plataforma.juez is None:
                juicio_no_evaluado.append(f"{caso}/{control_id}")
                continue
            if resultado is not None:
                anulado = any("Evidencia no sustentada" in l for l in resultado.limitaciones)
                if resultado.evidencia or anulado:
                    con_evidencia += 1
                    anulados += anulado
            if esperada == "no_cumple" and resultado is not None and resultado.severidad.value == "Alta":
                criticos += 1
                detectados += obtenida == "no_cumple"
            if obtenida == "no_cumple":
                emitidos += 1
                emitidos_ok += esperada == "no_cumple"
            if not es_juicio:
                total_det += 1
                exactos += obtenida == esperada
            detalle.append({"caso": caso, "control": control_id, "esperada": esperada, "obtenida": obtenida, "acierto": obtenida == esperada})
    return {
        "metricas": {
            "recall_hallazgos_criticos": detectados / criticos if criticos else None,
            "precision_no_cumple": emitidos_ok / emitidos if emitidos else None,
            "fidelidad_evidencia": 1 - anulados / con_evidencia if con_evidencia else None,
            "exactitud_deterministicos": exactos / total_det if total_det else None,
        },
        "controles_juicio_no_evaluados": juicio_no_evaluado,
        "fallos": [d for d in detalle if not d["acierto"]],
        "detalle": detalle,
    }


def cumple_umbrales(metricas: dict[str, float | None], umbrales: dict[str, Any]) -> list[str]:
    incumplidos = []
    for nombre, minimo in umbrales.items():
        if nombre == "estado":
            continue
        valor = metricas.get(nombre)
        if valor is None or valor < minimo:
            incumplidos.append(f"{nombre}: {valor} < {minimo}")
    return incumplidos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--etiquetas", default=str(RAIZ / "desarrollo" / "etiquetas.yaml"))
    parser.add_argument("--expedientes", default=None, help="Carpeta o Volume con expedientes; por defecto genera los sintéticos")
    parser.add_argument("--mlflow", action="store_true", help="Registra métricas en MLflow")
    argumentos = parser.parse_args(argv)

    from mrm.chasis.plataforma import Configuracion, Plataforma

    expedientes = argumentos.expedientes
    if expedientes is None:
        from evals.sintetico.generador import generar_casos

        expedientes = tempfile.mkdtemp(prefix="mrm_evals_")
        generar_casos(Path(expedientes))
    configuracion = Configuracion(
        raiz_expedientes=expedientes,
        raiz_resultados=os.environ.get("MRM_RAIZ_RESULTADOS") or tempfile.mkdtemp(prefix="mrm_evals_res_"),
        origen_grafo=os.environ.get("MRM_GRAFO") or str(RAIZ / "conocimiento_demo"),
        indice_vectorial=os.environ.get("MRM_INDICE_VECTORIAL") or None,
        juez_habilitado=os.environ.get("MRM_JUEZ_HABILITADO", "false").lower() in ("1", "true"),
        endpoint_juez=os.environ.get("MRM_ENDPOINT_JUEZ", "databricks-claude-sonnet-5-5"),
    )
    plataforma = Plataforma(configuracion)
    etiquetas = yaml.safe_load(Path(argumentos.etiquetas).read_text(encoding="utf-8"))
    umbrales = yaml.safe_load((RAIZ / "umbrales.yaml").read_text(encoding="utf-8"))
    reporte = evaluar(plataforma, etiquetas)
    reporte["umbrales_incumplidos"] = cumple_umbrales(reporte["metricas"], umbrales)
    print(json.dumps({k: v for k, v in reporte.items() if k != "detalle"}, indent=2, ensure_ascii=False))

    if argumentos.mlflow:
        import mlflow

        with mlflow.start_run(run_name="evals-validador-implementacion"):
            mlflow.log_metrics({k: v for k, v in reporte["metricas"].items() if v is not None})
            mlflow.log_dict(reporte, "reporte_evals.json")
    return 1 if reporte["umbrales_incumplidos"] else 0


if __name__ == "__main__":
    sys.exit(main())
