import pytest

from mrm.contratos.herramienta import ErrorHerramienta
from mrm.herramientas.comparar_series.herramienta import CompararSeries

comparar = CompararSeries()


def test_tramos_coincidentes_y_divergentes_con_etiquetas():
    salida = comparar({
        "referencia": [1.0, 2.0, 3.0, 4.0, 5.0], "implementacion": [1.0, 2.0, 3.5, 4.5, 5.0],
        "etiquetas": [3, 4, 5, 6, 7], "tolerancia": {"absoluta": 1e-9},
    })
    assert (salida.comparados, salida.coincidencias) == (5, 3)
    assert salida.primera_divergencia == 5
    assert salida.tramos_coincidentes == [[3, 4], [7, 7]]
    assert salida.tramos_divergentes == [[5, 6]]
    assert salida.max_dif_abs == pytest.approx(0.5)


def test_tolerancia_relativa_y_escalares():
    salida = comparar({"referencia": [1000.0], "implementacion": [1000.0001], "tolerancia": {"absoluta": 0, "relativa": 1e-6}})
    assert salida.coincidencias == 1


def test_longitudes_distintas_y_valores_no_comparables():
    salida = comparar({"referencia": [1, 2, 3], "implementacion": [1, None], "tolerancia": {"absoluta": 0}})
    assert salida.comparados == 1 and salida.no_comparables == 2
    assert salida.longitud_implementacion == 2


def test_texto_sin_mayusculas_ni_tildes():
    salida = comparar({"referencia": ["Pequeña Empresa"], "implementacion": ["PEQUEÑA EMPRESA"], "tolerancia": {"absoluta": 0}})
    assert salida.coincidencias == 1


def test_etiquetas_insuficientes():
    with pytest.raises(ErrorHerramienta) as error:
        comparar({"referencia": [1, 2], "implementacion": [1, 2], "etiquetas": [1], "tolerancia": {"absoluta": 0}})
    assert error.value.codigo == "etiquetas_incompatibles"
