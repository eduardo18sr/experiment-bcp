import pytest

from mrm.contratos.herramienta import ErrorHerramienta
from mrm.herramientas.extraer_excel.formulas import ErrorFormula, analizar_formula
from mrm.herramientas.extraer_excel.herramienta import ExtraerExcel


class TestTraductorFormulas:
    def test_precedencia_excel_negacion_antes_que_potencia(self):
        arbol = analizar_formula("=-2^2", "H")
        assert arbol == {"t": "bin", "op": "^", "a": {"t": "un", "op": "-", "x": {"t": "num", "v": 2.0}}, "b": {"t": "num", "v": 2.0}}

    def test_referencias_se_anclan_a_la_hoja_y_pierden_el_dolar(self):
        arbol = analizar_formula("=IF($H$8<=19,L9+M9*H9,0)", "Calculadora")
        condicion = arbol["args"][0]
        assert condicion["op"] == "<="
        assert condicion["a"] == {"t": "ref", "hoja": "Calculadora", "celda": "H8"}

    def test_vlookup_con_rango_de_otra_hoja(self):
        arbol = analizar_formula("=VLOOKUP(B2,Tarifario!$A$2:$D$5,2,FALSE)", "Calculo")
        assert arbol["nombre"] == "VLOOKUP"
        assert arbol["args"][1] == {"t": "rango", "hoja": "Tarifario", "desde": "A2", "hasta": "D5"}
        assert arbol["args"][3] == {"t": "bool", "v": False}

    def test_hoja_entre_comillas_y_funcion_con_digitos(self):
        arbol = analizar_formula("=LOG10('Hoja 1'!A1)", "X")
        assert arbol == {"t": "fn", "nombre": "LOG10", "args": [{"t": "ref", "hoja": "Hoja 1", "celda": "A1"}]}

    def test_argumento_vacio(self):
        arbol = analizar_formula("=VLOOKUP(A1,B1:C3,2,)", "X")
        assert arbol["args"][3] == {"t": "vacio"}

    def test_formula_mal_formada(self):
        with pytest.raises(ErrorFormula):
            analizar_formula("=SUM(A1:A3", "X")


class TestExtraerExcel:
    def test_caso_a_tiene_cache_y_arboles(self, libro_caso_a):
        assert libro_caso_a.tiene_cache
        celda = libro_caso_a.celdas["Calculadora!H12"]
        assert celda.formula.startswith("=IF(")
        assert celda.arbol["nombre"] == "IF"
        assert libro_caso_a.celdas["Calculadora!H8"].valor == 18
        assert len(libro_caso_a.sha256) == 64

    def test_caso_b_dos_hojas(self, libro_caso_b):
        assert libro_caso_b.hojas == ["Calculo", "Tarifario"]
        assert libro_caso_b.celdas["Tarifario!A3"].valor == "PYME"

    def test_libro_sin_cache_advierte(self, tmp_path):
        import openpyxl

        libro = openpyxl.Workbook()
        libro.active["A1"] = 2
        libro.active["A2"] = "=A1*3"
        ruta = tmp_path / "sin_cache.xlsx"
        libro.save(ruta)
        salida = ExtraerExcel()({"ruta": str(ruta)}).libro
        assert not salida.tiene_cache
        assert any("caché" in a for a in salida.advertencias)

    def test_errores_declarados(self, tmp_path):
        with pytest.raises(ErrorHerramienta) as error:
            ExtraerExcel()({"ruta": str(tmp_path / "no_existe.xlsx")})
        assert error.value.codigo == "archivo_no_encontrado"
        otro = tmp_path / "datos.csv"
        otro.write_text("a,b\n1,2\n")
        with pytest.raises(ErrorHerramienta) as error:
            ExtraerExcel()({"ruta": str(otro)})
        assert error.value.codigo == "formato_no_soportado"
