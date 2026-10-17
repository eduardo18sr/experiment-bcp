import math

import pytest

from mrm.contratos.canonico import CeldaCanonica, LibroCanonico
from mrm.contratos.herramienta import ErrorHerramienta
from mrm.herramientas.evaluar_formulas.herramienta import EvaluarFormulas
from mrm.herramientas.evaluar_formulas.motor import ErrorEvaluacion, ErrorExcel, Evaluador
from mrm.herramientas.extraer_excel.formulas import analizar_formula


def libro(celdas: dict, cache: dict | None = None) -> LibroCanonico:
    cache = cache or {}
    resultado = {}
    for ref, valor in celdas.items():
        if isinstance(valor, str) and valor.startswith("="):
            resultado[ref] = CeldaCanonica(ref=ref, formula=valor, valor=cache.get(ref), arbol=analizar_formula(valor, ref.split("!")[0]))
        else:
            resultado[ref] = CeldaCanonica(ref=ref, valor=valor)
    return LibroCanonico(archivo="x.xlsx", sha256="0" * 64, hojas=sorted({r.split("!")[0] for r in celdas}),
                         celdas=resultado, tiene_cache=bool(cache))


class TestSemanticaExcel:
    def test_if_anidado_y_sobrescrituras(self):
        datos = libro({"S!A1": 18, "S!A2": "=IF(A1<=19,1,IF(A1<=25,2,3))"})
        assert Evaluador(datos).valor("S!A2") == 1
        assert Evaluador(datos, {"S!A1": 20}).valor("S!A2") == 2
        assert Evaluador(datos, {"S!A1": 26}).valor("S!A2") == 3

    def test_round_lejos_de_cero_como_excel(self):
        datos = libro({"S!A1": "=ROUND(2.675,2)", "S!A2": "=ROUND(-2.5,0)", "S!A3": "=ROUND(1234.5,-2)"})
        evaluador = Evaluador(datos)
        assert evaluador.valor("S!A1") == 2.68
        assert evaluador.valor("S!A2") == -3.0
        assert evaluador.valor("S!A3") == 1200.0

    def test_vlookup_exacto_sin_mayusculas_y_aproximado(self):
        datos = libro({
            "T!A1": "MINORISTA", "T!B1": 1, "T!A2": "PYME", "T!B2": 2,
            "T!C1": 10, "T!D1": 100, "T!C2": 20, "T!D2": 200,
            "S!A1": '=VLOOKUP("pyme",T!A1:B2,2,FALSE)',
            "S!A2": "=VLOOKUP(15,T!C1:D2,2)",
            "S!A3": '=VLOOKUP("X",T!A1:B2,2,FALSE)',
        })
        evaluador = Evaluador(datos)
        assert evaluador.valor("S!A1") == 2
        assert evaluador.valor("S!A2") == 100
        assert evaluador.valor("S!A3") == ErrorExcel("#N/A")

    def test_errores_se_propagan_y_iferror_los_captura(self):
        datos = libro({"S!A1": "=1/0", "S!A2": "=A1+1", "S!A3": "=IFERROR(A2,7)", "S!A4": "=LN(0)"})
        evaluador = Evaluador(datos)
        assert evaluador.valor("S!A2") == ErrorExcel("#DIV/0!")
        assert evaluador.valor("S!A3") == 7
        assert evaluador.valor("S!A4") == ErrorExcel("#NUM!")

    def test_logistica_y_constantes_de_escala(self):
        datos = libro({"S!A1": "=40/LN(2)", "S!A2": "=400-A1*LN(50)", "S!A3": "=1/(1+EXP(-0))"})
        evaluador = Evaluador(datos)
        assert math.isclose(evaluador.valor("S!A1"), 40 / math.log(2))
        assert math.isclose(evaluador.valor("S!A2"), 400 - 40 / math.log(2) * math.log(50))
        assert evaluador.valor("S!A3") == 0.5

    def test_funcion_no_soportada_y_circular(self):
        with pytest.raises(ErrorEvaluacion) as error:
            Evaluador(libro({"S!A1": "=XNPV(1,2,3)"})).valor("S!A1")
        assert error.value.codigo == "funcion_no_soportada"
        with pytest.raises(ErrorEvaluacion) as error:
            Evaluador(libro({"S!A1": "=A2+1", "S!A2": "=A1+1"})).valor("S!A1")
        assert error.value.codigo == "referencia_circular"


class TestOraculo:
    def test_oraculo_reproduce_la_cache_del_caso_a(self, libro_caso_a):
        salida = EvaluarFormulas()({"libro": libro_caso_a, "objetivos": ["Calculadora!I27:BZ27", "Calculadora!I28:BZ28", "Calculadora!H14"]})
        assert salida.oraculo_valido is True
        assert salida.celdas_validadas >= 140
        assert len(salida.resultados[0].valores["Calculadora!I27:BZ27"]) == 70

    def test_oraculo_reproduce_la_cache_del_caso_b(self, libro_caso_b):
        salida = EvaluarFormulas()({"libro": libro_caso_b, "objetivos": ["Calculo!B9", "Calculo!B11"]})
        assert salida.oraculo_valido is True

    def test_detecta_cache_que_no_reproduce(self):
        datos = libro({"S!A1": 2, "S!A2": "=A1*3"}, cache={"S!A2": 7})
        salida = EvaluarFormulas()({"libro": datos, "objetivos": ["S!A2"]})
        assert salida.oraculo_valido is False
        assert salida.discrepancias_cache[0].ref == "S!A2"

    def test_funcion_no_soportada_invalida_el_oraculo(self):
        datos = libro({"S!A1": "=XNPV(1,2,3)"}, cache={"S!A1": 1.0})
        salida = EvaluarFormulas()({"libro": datos, "objetivos": ["S!A1"]})
        assert salida.oraculo_valido is False
        assert "funcion_no_soportada" in salida.errores_oraculo[0]
        assert salida.resultados[0].error

    def test_sin_cache_no_se_puede_validar(self):
        salida = EvaluarFormulas()({"libro": libro({"S!A1": 2, "S!A2": "=A1*3"}), "objetivos": ["S!A2"]})
        assert salida.oraculo_valido is None
        assert salida.resultados[0].valores["S!A2"] == [6.0]

    def test_escenarios_de_frontera_en_el_caso_a(self, libro_caso_a):
        salida = EvaluarFormulas()({
            "libro": libro_caso_a, "objetivos": ["Calculadora!H12"],
            "escenarios": [{"Calculadora!H8": 19}, {"Calculadora!H8": 20}], "validar_cache": False,
        })
        a19, a20 = (r.valores["Calculadora!H12"][0] for r in salida.resultados)
        assert math.isclose(a19 - a20, 0.10)  # en 19 aplica el intercepto del primer rango

    def test_objetivo_invalido(self, libro_caso_a):
        with pytest.raises(ErrorHerramienta) as error:
            EvaluarFormulas()({"libro": libro_caso_a, "objetivos": ["sin_hoja"]})
        assert error.value.codigo == "objetivo_invalido"
