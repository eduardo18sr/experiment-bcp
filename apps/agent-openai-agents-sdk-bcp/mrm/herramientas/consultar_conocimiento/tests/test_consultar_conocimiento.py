"""Recall del componente probabilístico (framework G.5): si está en la ruta de evidencia, se mide."""

import pytest

from mrm.contratos.herramienta import ErrorHerramienta
from mrm.herramientas.consultar_conocimiento.herramienta import ConsultarConocimiento

CONSULTAS_ETIQUETADAS = [
    ("versión del archivo de parámetros escrita en el código", "Declarar la versión de parámetros en configuración"),
    ("líneas comentadas que cargan otra versión", "No dejar versiones alternativas comentadas"),
    ("umbral de rango duplicado en dos funciones", "Una sola fuente de verdad para cada regla de negocio"),
    ("función que lee archivos y además calcula", "Dar a cada función una sola responsabilidad"),
    ("coeficientes escritos como números dentro de la función", "Separar los parámetros del código"),
]


def test_recall_en_top_3(consultor_demo):
    herramienta = ConsultarConocimiento(consultor_demo)
    aciertos = sum(
        esperada in [p.nota for p in herramienta({"consulta": consulta, "k": 3}).practicas]
        for consulta, esperada in CONSULTAS_ETIQUETADAS
    )
    assert aciertos / len(CONSULTAS_ETIQUETADAS) >= 0.8


def test_no_devuelve_mapas_ni_secciones_de_enlaces(consultor_demo):
    practicas = ConsultarConocimiento(consultor_demo)({"consulta": "buenas prácticas de código", "k": 10}).practicas
    assert all(not p.nota.startswith("Mapa - ") for p in practicas)
    assert all(p.seccion.lower() != "relacionado" for p in practicas)
    assert all(p.mapas and all(m.startswith("Mapa - Buenas prácticas de") for m in p.mapas) for p in practicas)


def test_guardrail_de_cita(consultor_demo):
    assert consultor_demo.cita_existe("No dejar versiones alternativas comentadas", "El control de versiones ya guarda la historia.")
    assert not consultor_demo.cita_existe("No dejar versiones alternativas comentadas", "Una cita inventada por el modelo.")


def test_sin_grafo():
    with pytest.raises(ErrorHerramienta) as error:
        ConsultarConocimiento(None)({"consulta": "algo"})
    assert error.value.codigo == "conocimiento_no_disponible"
