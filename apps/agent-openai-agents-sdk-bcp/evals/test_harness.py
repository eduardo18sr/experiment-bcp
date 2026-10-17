"""El arnés corre sin intervención manual y el agente cumple los umbrales provisionales en desarrollo."""

from pathlib import Path

import yaml

from evals.harness import cumple_umbrales, evaluar

RAIZ = Path(__file__).resolve().parent


def test_arnes_sobre_casos_sinteticos(crear_plataforma):
    etiquetas = yaml.safe_load((RAIZ / "desarrollo" / "etiquetas.yaml").read_text(encoding="utf-8"))
    reporte = evaluar(crear_plataforma(), etiquetas)
    metricas = reporte["metricas"]
    assert reporte["fallos"] == []
    assert metricas["recall_hallazgos_criticos"] == 1.0
    assert metricas["precision_no_cumple"] == 1.0
    assert metricas["fidelidad_evidencia"] == 1.0
    assert reporte["controles_juicio_no_evaluados"] == [
        "CASO_A_PD_CURVA/IMP-PD-007", "CASO_A_PD_CURVA/DOC-PD-002", "CASO_B_PRICING/DOC-PRC-002", "CASO_C_SCORING/DOC-PD-002",
    ]
    umbrales = yaml.safe_load((RAIZ / "umbrales.yaml").read_text(encoding="utf-8"))
    assert cumple_umbrales(metricas, umbrales) == []
