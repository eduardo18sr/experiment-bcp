import shutil

import pytest
import yaml

from mrm.chasis.politica import PoliticaTiering, filtrar_por_tier
from mrm.chasis.registro import RAIZ_MRM, ErrorRegistro, Registro
from mrm.chasis.resolutor import ClaveResolucion, EstadoResolucion, resolver


@pytest.fixture(scope="module")
def registro():
    return Registro()


def test_registro_real_es_integro(registro):
    assert registro.verificar_integridad() == []


def test_detecta_contrato_desalineado_con_la_implementacion(registro):
    entrada = registro.herramientas["comparar_series"][0]
    original = entrada.contrato.version
    entrada.contrato.version = "9.9.9"
    try:
        assert any("comparar_series" in d for d in registro.verificar_integridad())
    finally:
        entrada.contrato.version = original


def test_resolucion_por_especificidad_y_huecos(registro):
    clave = ClaveResolucion(dimension="entorno_tecnologico", tipo_modelo="pd", tier=1)
    resolucion = resolver(registro, clave)
    assert resolucion.estado is EstadoResolucion.RESUELTA
    assert (resolucion.skill, resolucion.catalogo) == ("validar-implementacion-calculo", "implementacion_pd")
    assert resolver(registro, clave.model_copy(update={"tipo_modelo": "lgd"})).estado is EstadoResolucion.SIN_COBERTURA
    documental = resolver(registro, clave.model_copy(update={"dimension": "documentacion"}))
    assert (documental.skill, documental.catalogo) == ("revisar-documentacion", "documentacion_pd")
    assert resolver(registro, clave.model_copy(update={"dimension": "calidad_datos"})).estado is EstadoResolucion.SIN_COBERTURA


def test_la_version_mayor_no_se_resuelve_sola(registro):
    with pytest.raises(ErrorRegistro):
        registro.resolver_herramienta("comparar_series", "2.0.0")


def test_selector_de_tier(registro):
    catalogo = registro.catalogo("implementacion_pd", "1.0.0")
    aplicables, excluidos = filtrar_por_tier(catalogo, 3, PoliticaTiering.cargar())
    assert {c.control_id for c in excluidos} == {"IMP-PD-006", "IMP-PD-007"}
    assert "tier mínimo" in excluidos[0].motivo
    assert len(aplicables) == 5


def test_empate_es_defecto_del_registro(tmp_path):
    raiz = tmp_path / "mrm"
    shutil.copytree(RAIZ_MRM, raiz, ignore=shutil.ignore_patterns("*.py", "__pycache__", "tests"))
    spec = yaml.safe_load((raiz / "skills/validar_implementacion_calculo/skill.yaml").read_text(encoding="utf-8"))
    spec["nombre"] = "otra-skill-de-implementacion"
    (raiz / "skills/validar_implementacion_calculo/otra.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    registro_yaml = yaml.safe_load((raiz / "registro/skills.yaml").read_text(encoding="utf-8"))
    registro_yaml["skills"].append({
        "spec": "skills/validar_implementacion_calculo/otra.yaml",
        "implementacion": "mrm.skills.validar_implementacion_calculo.procedimiento:ValidarImplementacionCalculo",
    })
    (raiz / "registro/skills.yaml").write_text(yaml.safe_dump(registro_yaml), encoding="utf-8")

    registro = Registro(raiz)
    assert any("Empate" in d for d in registro.verificar_integridad())
    resolucion = resolver(registro, ClaveResolucion(dimension="entorno_tecnologico", tipo_modelo="pd", tier=1))
    assert resolucion.estado is EstadoResolucion.EMPATE
