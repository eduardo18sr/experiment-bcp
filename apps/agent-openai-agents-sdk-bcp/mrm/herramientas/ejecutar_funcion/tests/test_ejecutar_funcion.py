import textwrap

import pytest

from mrm.contratos.herramienta import ErrorHerramienta
from mrm.herramientas.ejecutar_funcion.herramienta import EjecutarFuncion, manifiesto


@pytest.fixture
def proyecto(tmp_path):
    raiz = tmp_path / "proyecto"
    (raiz / "calc").mkdir(parents=True)
    (raiz / "calc" / "__init__.py").write_text("", encoding="utf-8")
    (raiz / "calc" / "base.py").write_text(textwrap.dedent('''
        import time

        ARCHIVO = "version_a.txt"


        def doble(x):
            print("ruido que no debe romper la salida")
            return {"valor": 2 * x, "archivo": ARCHIVO}


        def falla(x):
            raise ValueError("entrada inválida")


        def lenta(x):
            time.sleep(10)
    '''), encoding="utf-8")
    return raiz


def test_requiere_autorizacion(proyecto):
    with pytest.raises(ErrorHerramienta) as error:
        EjecutarFuncion()({"raiz_proyecto": str(proyecto), "funcion": "calc.base:doble", "casos": [{"x": 1}]})
    assert error.value.codigo == "ejecucion_no_autorizada"


def test_ejecuta_en_copia_y_no_toca_el_original(proyecto):
    antes = manifiesto(proyecto)
    salida = EjecutarFuncion()({
        "raiz_proyecto": str(proyecto), "funcion": "calc.base:doble", "casos": [{"x": 1}, {"x": 2.5}], "autorizado": True,
    })
    assert salida.copia_verificada and salida.original_intacto
    assert [r.salida["valor"] for r in salida.resultados] == [2, 5.0]
    assert manifiesto(proyecto) == antes


def test_sustitucion_queda_registrada_solo_en_la_copia(proyecto):
    salida = EjecutarFuncion()({
        "raiz_proyecto": str(proyecto), "funcion": "calc.base:doble", "casos": [{"x": 1}], "autorizado": True,
        "variante": "alineada",
        "sustituciones": [{"archivo": "calc/base.py", "linea": 4, "buscar": "version_a.txt", "reemplazar": "version_b.txt"}],
    })
    assert salida.resultados[0].salida["archivo"] == "version_b.txt"
    assert salida.parche[0].antes == 'ARCHIVO = "version_a.txt"'
    assert salida.parche[0].sha256_antes != salida.parche[0].sha256_despues
    assert 'version_a.txt' in (proyecto / "calc" / "base.py").read_text(encoding="utf-8")


def test_sustitucion_sin_efecto(proyecto):
    with pytest.raises(ErrorHerramienta) as error:
        EjecutarFuncion()({
            "raiz_proyecto": str(proyecto), "funcion": "calc.base:doble", "casos": [{"x": 1}], "autorizado": True,
            "sustituciones": [{"archivo": "calc/base.py", "linea": 1, "buscar": "version_a.txt", "reemplazar": "x"}],
        })
    assert error.value.codigo == "sustitucion_sin_efecto"


def test_error_de_la_funcion_se_informa_por_caso(proyecto):
    salida = EjecutarFuncion()({"raiz_proyecto": str(proyecto), "funcion": "calc.base:falla", "casos": [{"x": 1}], "autorizado": True})
    assert not salida.resultados[0].ok
    assert "ValueError" in salida.resultados[0].error


def test_funcion_inexistente(proyecto):
    salida = EjecutarFuncion()({"raiz_proyecto": str(proyecto), "funcion": "calc.base:no_existe", "casos": [{"x": 1}], "autorizado": True})
    assert "AttributeError" in salida.resultados[0].error


def test_timeout(proyecto):
    with pytest.raises(ErrorHerramienta) as error:
        EjecutarFuncion()({"raiz_proyecto": str(proyecto), "funcion": "calc.base:lenta", "casos": [{"x": 1}], "autorizado": True, "timeout_s": 1})
    assert error.value.codigo == "timeout"
