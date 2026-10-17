"""Caso de regresión obligatorio (`CONTEXTO_AGENTIZACION.md` §4), reproducido con datos sintéticos.

Versión activa de parámetros 0/70 contra la curva de referencia, versión alineada 70/70, curva final
extendida 10/70 (solo periodos 3-12) y límites de rango distintos (19 y 25). Todo automático.
"""

import pytest

from mrm.contratos.resultado import VeredictoControl


@pytest.fixture(scope="module")
def expediente_a(casos, tmp_path_factory, consultor_demo):
    from mrm.chasis.plataforma import Configuracion, Plataforma

    plataforma = Plataforma(
        Configuracion(raiz_expedientes=str(casos), raiz_resultados=str(tmp_path_factory.mktemp("res"))),
        consultor=consultor_demo,
    )
    expediente, informe = plataforma.validar("CASO_A_PD_CURVA", solicitante="pytest")
    return expediente, informe


def _componente(expediente, control_id, componente_id, variante):
    dimension = expediente.dimensiones[0]
    return next(
        r for r in dimension.resultados_componentes
        if r.control_id == control_id and r.componente_id == componente_id and r.variante == variante
    )


def test_version_activa_cero_de_setenta(expediente_a):
    resultado = _componente(expediente_a[0], "IMP-PD-001", "curva_pd_temporal", "activa")
    assert (resultado.coincidencias, resultado.comparados) == (0, 70)


def test_version_alineada_setenta_de_setenta(expediente_a):
    resultado = _componente(expediente_a[0], "IMP-PD-002", "curva_pd_temporal", "alineada")
    assert (resultado.coincidencias, resultado.comparados) == (70, 70)
    assert resultado.max_dif_abs < 1e-12


def test_curva_final_solo_coincide_en_periodos_3_a_12(expediente_a):
    resultado = _componente(expediente_a[0], "IMP-PD-005", "curva_pd_final", "alineada")
    assert (resultado.coincidencias, resultado.comparados) == (10, 70)
    assert resultado.detalle["tramos_coincidentes"] == [[3, 12]]


def test_uso_de_parametros(expediente_a):
    hechos = expediente_a[0].dimensiones[0].hechos
    theta = next(t for t in hechos["parametros"] if t["tabla"] == "theta_temporal")
    clasificacion = {a["ruta"]: a["clasificacion"] for a in theta["archivos"]}
    assert clasificacion["params/theta_Tt_VERSION_ACTIVA.csv"] == "SE_USA_SIN_COINCIDENCIA"
    assert clasificacion["params/theta_Tt_VERSION_EXCEL.csv"] == "COINCIDE_PERO_NO_SE_USA"


def test_parche_registrado_y_original_intacto(expediente_a):
    hechos = expediente_a[0].dimensiones[0].hechos
    assert hechos["original_intacto"] is True
    parche = hechos["parche_variante_alineada"][0]
    assert parche["archivo"] == "motor/parametros.py"
    assert "theta_Tt_VERSION_ACTIVA.csv" in parche["antes"] and "theta_Tt_VERSION_EXCEL.csv" in parche["despues"]


def test_fronteras_de_rango(expediente_a):
    resultado = next(r for r in expediente_a[0].resultados() if r.control_id == "IMP-PD-006")
    assert resultado.veredicto is VeredictoControl.NO_CUMPLE
    assert "plazo=19" in resultado.justificacion and "plazo=25" in resultado.justificacion


def test_veredictos_por_control_y_caso(expediente_a):
    veredictos = {r.control_id: r.veredicto for r in expediente_a[0].resultados() if r.control_id.startswith("IMP-")}
    assert veredictos == {
        "IMP-PD-001": VeredictoControl.NO_CUMPLE,
        "IMP-PD-002": VeredictoControl.CUMPLE,
        "IMP-PD-003": VeredictoControl.NO_CUMPLE,
        "IMP-PD-004": VeredictoControl.NO_CUMPLE,
        "IMP-PD-005": VeredictoControl.NO_CUMPLE,
        "IMP-PD-006": VeredictoControl.NO_CUMPLE,
        "IMP-PD-007": VeredictoControl.NO_CONCLUYENTE,  # sin juez configurado: escala
    }
    assert expediente_a[0].veredicto_integral is VeredictoControl.NO_CUMPLE


def test_tier_1_escala_todo_y_el_informe_lo_dice(expediente_a):
    expediente, informe = expediente_a
    assert all(r.requiere_revision_humana for r in expediente.resultados())
    assert "Modelo tier 1: revisión humana completa" in expediente.resultados()[0].motivos_escalamiento
    assert "No constituye aprobación ni rechazo del modelo" in informe
    assert "IMP-PD-001" in informe and "documentacion" in informe


def test_trazabilidad_completa(expediente_a):
    resultado = expediente_a[0].resultados()[0]
    assert resultado.trazabilidad.skill == "validar-implementacion-calculo"
    assert resultado.trazabilidad.version_catalogo == "1.0.0"
    assert resultado.trazabilidad.herramientas["ejecutar_funcion"] == "1.0.0"
    assert len(expediente_a[0].huellas_entradas) >= 8
