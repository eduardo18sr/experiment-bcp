"""Fixtures compartidas: expedientes sintéticos, bóveda de conocimiento demo y plataforma local."""

from __future__ import annotations

from pathlib import Path

import pytest

RAIZ_APP = Path(__file__).resolve().parent
BOVEDA_DEMO = RAIZ_APP / "evals" / "conocimiento_demo"


@pytest.fixture(scope="session")
def casos(tmp_path_factory) -> Path:
    """Genera una vez los tres expedientes sintéticos y el inventario."""
    from evals.sintetico.generador import generar_casos

    destino = tmp_path_factory.mktemp("expedientes")
    generar_casos(destino)
    return destino


@pytest.fixture(scope="session")
def consultor_demo():
    from mrm.conocimiento.consulta import ConsultorGrafo
    from mrm.conocimiento.ingesta_obsidian import ingerir_boveda

    return ConsultorGrafo(ingerir_boveda(BOVEDA_DEMO))


@pytest.fixture
def crear_plataforma(casos, tmp_path, consultor_demo):
    from mrm.chasis.plataforma import Configuracion, Plataforma

    def crear(juez=None):
        configuracion = Configuracion(raiz_expedientes=str(casos), raiz_resultados=str(tmp_path / "resultados"))
        return Plataforma(configuracion, juez=juez, consultor=consultor_demo)

    return crear


@pytest.fixture(scope="session")
def libro_caso_a(casos):
    from mrm.herramientas.extraer_excel.herramienta import ExtraerExcel

    return ExtraerExcel()({"ruta": str(casos / "CASO_A_PD_CURVA" / "referencia" / "calculadora_pd.xlsx")}).libro


@pytest.fixture(scope="session")
def libro_caso_b(casos):
    from mrm.herramientas.extraer_excel.herramienta import ExtraerExcel

    return ExtraerExcel()({"ruta": str(casos / "CASO_B_PRICING" / "referencia" / "tarifario_pricing.xlsx")}).libro
