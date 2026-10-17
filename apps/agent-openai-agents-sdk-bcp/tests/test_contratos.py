import pytest
from pydantic import ValidationError

from mrm.contratos.control import Control
from mrm.contratos.resultado import (
    EstadoEjecucion,
    Evidencia,
    ResultadoComponente,
    ResultadoControl,
    TipoEvidencia,
    VeredictoComponente,
    VeredictoControl,
    veredicto_integral,
)
from mrm.contratos.version import es_compatible

BASE_CONTROL = dict(
    id="X-001", version="1.0.0", nombre="x", evidencia_requerida="x", tipo="deterministico", tier_minimo=2,
    severidad="Alta", referencia="x", regla="r",
)


def test_enunciado_debe_seguir_ears():
    Control(**BASE_CONTROL, enunciado_ears="Cuando ocurra X, el sistema deberá levantar un hallazgo.")
    with pytest.raises(ValidationError):
        Control(**BASE_CONTROL, enunciado_ears="Verificar que la documentación sea adecuada.")


def test_tier_es_filtro_del_control():
    control = Control(**BASE_CONTROL, enunciado_ears="Cuando ocurra X, el sistema deberá levantar un hallazgo.")
    assert control.aplica_a_tier(1) and control.aplica_a_tier(2) and not control.aplica_a_tier(3)


def test_error_tecnico_nunca_produce_match_ni_diverge():
    with pytest.raises(ValidationError):
        ResultadoComponente(componente_id="c", control_id="x", estrategia="e", estado_ejecucion=EstadoEjecucion.ERROR,
                            veredicto=VeredictoComponente.COINCIDE, comparados=1, coincidencias=1)
    with pytest.raises(ValidationError):
        ResultadoComponente(componente_id="c", control_id="x", estrategia="e", estado_ejecucion=EstadoEjecucion.NO_EJECUTADA,
                            veredicto=VeredictoComponente.DIVERGE)


def test_ausencia_de_evidencia_nunca_produce_match_ni_cumple():
    with pytest.raises(ValidationError):
        ResultadoComponente(componente_id="c", control_id="x", estrategia="e", estado_ejecucion=EstadoEjecucion.COMPLETADA,
                            veredicto=VeredictoComponente.COINCIDE, comparados=0)
    with pytest.raises(ValidationError):
        ResultadoControl(control_id="x", nombre="x", tipo="deterministico", veredicto=VeredictoControl.CUMPLE,
                         severidad="Alta", justificacion="sin evidencia")


def test_veredicto_integral_no_es_mejor_que_el_peor():
    evidencia = [Evidencia(tipo=TipoEvidencia.HECHO, fuente="f", ubicacion="u")]

    def resultado(veredicto):
        return ResultadoControl(control_id="x", nombre="x", tipo="deterministico", veredicto=veredicto,
                                severidad="Media", justificacion="j", evidencia=evidencia)

    assert veredicto_integral([resultado(VeredictoControl.CUMPLE), resultado(VeredictoControl.NO_CONCLUYENTE)]) is VeredictoControl.NO_CONCLUYENTE
    assert veredicto_integral([resultado(VeredictoControl.NO_CONCLUYENTE), resultado(VeredictoControl.NO_CUMPLE)]) is VeredictoControl.NO_CUMPLE
    assert veredicto_integral([]) is None


def test_compatibilidad_semantica():
    assert es_compatible("1.3.0", "1.0.0")
    assert not es_compatible("2.0.0", "1.0.0")  # una versión mayor exige migración explícita
    assert not es_compatible("1.0.0", "1.2.0")
