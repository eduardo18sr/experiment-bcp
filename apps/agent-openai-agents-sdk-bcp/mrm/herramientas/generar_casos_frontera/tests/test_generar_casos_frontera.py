from mrm.contratos.canonico import CeldaCanonica, LibroCanonico
from mrm.herramientas.extraer_excel.formulas import analizar_formula
from mrm.herramientas.generar_casos_frontera.herramienta import GenerarCasosFrontera


def test_caso_a_condiciones_de_plazo(libro_caso_a):
    salida = GenerarCasosFrontera()({
        "libro": libro_caso_a, "objetivos": ["Calculadora!I27:BZ27", "Calculadora!H13"],
        "entradas": [{"nombre": "plazo", "ref": "Calculadora!H8", "tipo": "entero"},
                     {"nombre": "score", "ref": "Calculadora!H11", "tipo": "numero", "paso": 1}],
    })
    assert {(c.entrada, c.operador, c.umbral) for c in salida.condiciones} == {("plazo", "<=", 19.0), ("plazo", "<=", 25.0)}
    assert [c.valor for c in salida.casos] == [18, 19, 20, 24, 25, 26]
    assert salida.casos[1].sobrescrituras == {"Calculadora!H8": 19}


def test_operador_invertido_y_entrada_continua():
    formula = "=IF(0.5<A1,1,0)"
    libro = LibroCanonico(
        archivo="x", sha256="0", hojas=["S"], tiene_cache=False,
        celdas={"S!A1": CeldaCanonica(ref="S!A1", valor=0.2),
                "S!A2": CeldaCanonica(ref="S!A2", formula=formula, arbol=analizar_formula(formula, "S"))},
    )
    salida = GenerarCasosFrontera()({
        "libro": libro, "objetivos": ["S!A2"], "entradas": [{"nombre": "ratio", "ref": "S!A1", "tipo": "numero", "paso": 0.01}],
    })
    assert salida.condiciones[0].operador == ">"  # 0.5 < A1  equivale a  A1 > 0.5
    assert [round(c.valor, 4) for c in salida.casos] == [0.49, 0.5, 0.51]


def test_entradas_de_texto_no_generan_fronteras(libro_caso_b):
    salida = GenerarCasosFrontera()({
        "libro": libro_caso_b, "objetivos": ["Calculo!B9"],
        "entradas": [{"nombre": "segmento", "ref": "Calculo!B2", "tipo": "texto"},
                     {"nombre": "plazo", "ref": "Calculo!B4", "tipo": "entero"}],
    })
    assert [(c.entrada, c.operador, c.umbral) for c in salida.condiciones] == [("plazo", ">", 12.0)]
    assert [c.valor for c in salida.casos] == [11, 12, 13]
