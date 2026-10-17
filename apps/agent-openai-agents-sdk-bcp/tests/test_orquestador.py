import hashlib
import shutil
from pathlib import Path

import pytest
import yaml

from mrm.chasis.almacen import AlmacenLocal
from mrm.chasis.orquestador import Orquestador
from mrm.chasis.politica import PoliticaTiering
from mrm.chasis.registro import RAIZ_MRM, Registro
from mrm.contratos.resultado import Aplicabilidad, VeredictoControl
from mrm.juicio.puerto import CitaCodigo, CitaPractica, JuezProgramado, VeredictoJuicio

AGENTE = {"id": "validador-implementacion", "version": "0.1.0", "etapa_autonomia": "sombra"}


def _veredictos(expediente, prefijo: str = ""):
    return {
        r.control_id: (r.veredicto.value if r.veredicto else r.aplicabilidad.value)
        for r in expediente.resultados()
        if r.control_id.startswith(prefijo)
    }


def _dimension(expediente, nombre: str):
    return next(d for d in expediente.dimensiones if d.dimension == nombre)


def test_caso_b_pricing_detecta_solo_el_parametro(crear_plataforma):
    expediente, _ = crear_plataforma().validar("CASO_B_PRICING")
    assert _veredictos(expediente, "IMP-") == {
        "IMP-PRC-001": "cumple", "IMP-PRC-002": "cumple", "IMP-PRC-003": "no_cumple", "IMP-PRC-004": "cumple",
        "IMP-PRC-005": Aplicabilidad.NO_APLICA.value, "IMP-PRC-006": "cumple",
    }
    excluidos = [c.control_id for c in _dimension(expediente, "entorno_tecnologico").controles_excluidos]
    assert excluidos == ["IMP-PRC-007"]  # tier 2 > tier mínimo 1


def test_caso_c_sin_falsos_positivos(crear_plataforma):
    expediente, _ = crear_plataforma().validar("CASO_C_SCORING")
    implementacion = _dimension(expediente, "entorno_tecnologico").resultados_control
    assert all(r.veredicto in (VeredictoControl.CUMPLE, None) for r in implementacion)
    assert not any(r.requiere_revision_humana for r in implementacion)  # tier 3, todo cumple
    assert expediente.huecos_cobertura == []  # tier 3 exige implementación y documentación: ambas cubiertas
    # Sin juez, el control de juicio documental escala y el veredicto integral no puede ser mejor que eso.
    assert _veredictos(expediente, "DOC-")["DOC-PD-002"] == "no_concluyente"
    assert expediente.veredicto_integral is VeredictoControl.NO_CONCLUYENTE
    assert expediente.requiere_revision_humana


def test_resumen_para_llm_no_lleva_valores(crear_plataforma):
    expediente, _ = crear_plataforma().validar("CASO_B_PRICING")
    resumen = expediente.resumen_para_llm()
    texto = str(resumen)
    assert "0.031" not in texto and "0.03" not in texto
    assert all("valor" not in e for c in resumen["controles"] for e in c["evidencia"])


def _linea(casos: Path, texto: str) -> int:
    lineas = (casos / "CASO_A_PD_CURVA" / "implementacion" / "motor" / "parametros.py").read_text(encoding="utf-8").splitlines()
    return next(i for i, linea in enumerate(lineas, start=1) if texto in linea and not linea.strip().startswith("#"))


def test_juez_con_citas_verificables(crear_plataforma, casos):
    linea = _linea(casos, "theta_Tt_VERSION_ACTIVA.csv")
    juez = JuezProgramado({
        "IMP-PD-007": VeredictoJuicio(
            veredicto="no_cumple",
            justificacion="La versión de parámetros está escrita en el código.",
            citas_codigo=[CitaCodigo(ruta="motor/parametros.py", linea=linea, cita='"theta_Tt_VERSION_ACTIVA.csv"')],
            citas_practicas=[CitaPractica(nota="Declarar la versión de parámetros en configuración",
                                          cita="se declara en configuración versionada")],
        )
    })
    expediente, _ = crear_plataforma(juez=juez).validar("CASO_A_PD_CURVA")
    resultado = next(r for r in expediente.resultados() if r.control_id == "IMP-PD-007")
    assert resultado.veredicto is VeredictoControl.NO_CUMPLE
    assert "Control de juicio en etapa sombra" in resultado.motivos_escalamiento
    solicitud = next(s for s in juez.solicitudes if s.control_id == "IMP-PD-007")
    assert solicitud.practicas and solicitud.codigo and not solicitud.documento  # contexto limpio
    assert expediente.llamadas_llm == 2  # IMP-PD-007 y el juicio documental DOC-PD-002


def test_guardrail_anula_una_cita_inventada(crear_plataforma):
    juez = JuezProgramado({
        "IMP-PD-007": VeredictoJuicio(
            veredicto="cumple",
            justificacion="Todo correcto.",
            citas_codigo=[CitaCodigo(ruta="motor/parametros.py", linea=3, cita="config = cargar_configuracion()")],
            citas_practicas=[CitaPractica(nota="Separar los parámetros del código", cita="Una práctica que no existe.")],
        )
    })
    expediente, _ = crear_plataforma(juez=juez).validar("CASO_A_PD_CURVA")
    resultado = next(r for r in expediente.resultados() if r.control_id == "IMP-PD-007")
    assert resultado.veredicto is VeredictoControl.NO_CONCLUYENTE
    assert resultado.justificacion.startswith("[Veredicto original 'cumple' anulado")
    assert sum("Evidencia no sustentada" in l for l in resultado.limitaciones) == 2
    assert resultado.requiere_revision_humana


def test_fallo_de_skill_nunca_es_cumple(crear_plataforma, monkeypatch):
    from mrm.skills.validar_implementacion_calculo import procedimiento

    def explotar(self, contexto):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(procedimiento.ValidarImplementacionCalculo, "ejecutar", explotar)
    expediente, _ = crear_plataforma().validar("CASO_C_SCORING")
    assert expediente.veredicto_integral is VeredictoControl.NO_CONCLUYENTE
    implementacion = _dimension(expediente, "entorno_tecnologico")
    assert implementacion.error and "fallo simulado" in implementacion.error
    assert all(r.veredicto is VeredictoControl.NO_CONCLUYENTE for r in implementacion.resultados_control)
    assert len(implementacion.resultados_control) == 5
    assert _dimension(expediente, "documentacion").error is None  # una dimensión que falla no arrastra a las demás


def test_skill_no_puede_usar_herramientas_no_declaradas(casos):
    from mrm.chasis.contexto import ContextoEjecucion
    from mrm.contratos.expediente import ModeloInventario, SolicitudValidacion

    registro = Registro()
    entrada = registro.skills["validar-implementacion-calculo"]
    spec = entrada.spec.model_copy(update={"herramientas_requeridas": entrada.spec.herramientas_requeridas[:1]})
    solicitud = SolicitudValidacion.model_validate(yaml.safe_load((casos / "CASO_C_SCORING" / "expediente.yaml").read_text(encoding="utf-8")))
    contexto = ContextoEjecucion(
        registro=registro, spec=spec, solicitud=solicitud,
        modelo=ModeloInventario(id="M", nombre="M", tipo_modelo="pd", tier=3),
        catalogo=registro.catalogo("implementacion_pd", "1.0.0"), controles=[], configuracion=spec.configuraciones[0],
        dir_expediente=casos / "CASO_C_SCORING", dependencias={},
    )
    with pytest.raises(PermissionError):
        contexto.herramienta("ejecutar_funcion")
    with pytest.raises(PermissionError):
        contexto.ruta("../inventario.yaml")


def _huella_chasis() -> str:
    digest = hashlib.sha256()
    for ruta in sorted((RAIZ_MRM / "chasis").glob("*.py")):
        digest.update(ruta.read_bytes())
    return digest.hexdigest()


def test_nueva_dimension_sin_tocar_el_chasis(casos, tmp_path):
    """Ruta S: una skill y un catálogo nuevos, registrados por configuración. El chasis no cambia."""
    huella_antes = _huella_chasis()
    raiz = tmp_path / "mrm"
    shutil.copytree(RAIZ_MRM, raiz, ignore=shutil.ignore_patterns("*.py", "__pycache__", "tests"))
    (raiz / "skills" / "revisar_calidad_minima").mkdir()
    (raiz / "skills" / "revisar_calidad_minima" / "skill.yaml").write_text(yaml.safe_dump({
        "nombre": "revisar-calidad-minima", "version": "0.1.0", "dimension": "calidad_datos",
        "descripcion": "Verifica que el expediente traiga la referencia metodológica.",
        "aplica_a": {"tipo_modelo": ["*"]}, "procedimiento": ["Comprobar la presencia de la referencia"],
        "herramientas_requeridas": [], "reglas": ["referencia_presente"],
        "configuraciones": [{"tipo_modelo": "*", "catalogo": "calidad_general", "version_catalogo": "0.1.0"}],
    }, allow_unicode=True), encoding="utf-8")
    (raiz / "catalogos" / "calidad_general.yaml").write_text(yaml.safe_dump({
        "nombre": "calidad_general", "version": "0.1.0", "dimension": "calidad_datos", "tipo_modelo": "*",
        "controles": [{
            "id": "CAL-GEN-001", "version": "0.1.0", "nombre": "Referencia metodológica presente",
            "enunciado_ears": "Cuando el expediente no incluya la referencia metodológica, el sistema deberá levantar un hallazgo de severidad Alta.",
            "evidencia_requerida": "Ruta del archivo", "tipo": "deterministico", "tier_minimo": 4, "severidad": "Alta",
            "referencia": "Política interna (ejemplo)", "regla": "referencia_presente",
        }],
    }, allow_unicode=True), encoding="utf-8")
    registro_skills = yaml.safe_load((raiz / "registro" / "skills.yaml").read_text(encoding="utf-8"))
    registro_skills["skills"].append({
        "spec": "skills/revisar_calidad_minima/skill.yaml",
        "implementacion": "tests.apoyo.skill_minima:SkillMinimaReferencia",
    })
    (raiz / "registro" / "skills.yaml").write_text(yaml.safe_dump(registro_skills), encoding="utf-8")

    registro = Registro(raiz)
    assert registro.verificar_integridad() == []
    orquestador = Orquestador(registro, PoliticaTiering.cargar(), AlmacenLocal(casos, tmp_path / "res"), AGENTE)
    expediente, _ = orquestador.validar("CASO_B_PRICING")  # tier 2: implementación, documentación y calidad de datos
    assert expediente.huecos_cobertura == []
    assert {d.dimension for d in expediente.dimensiones} == {"entorno_tecnologico", "documentacion", "calidad_datos"}
    assert _veredictos(expediente)["CAL-GEN-001"] == "cumple"
    assert _huella_chasis() == huella_antes
