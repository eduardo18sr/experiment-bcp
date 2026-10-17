"""Skill `revisar-documentacion` (ruta S): presencia y estructura determinísticas, suficiencia por juicio."""

import shutil

import pytest

from mrm.contratos.resultado import TipoEvidencia, VeredictoControl
from mrm.juicio.puerto import CitaDocumento, CitaPractica, JuezProgramado, VeredictoJuicio

DOC_A = "documentacion/metodologia_pd.docx"
SECCION_A = "2. Perímetro de aplicación"


def _documentales(expediente):
    return {r.control_id: r for d in expediente.dimensiones if d.dimension == "documentacion" for r in d.resultados_control}


@pytest.fixture
def copia_casos(casos, tmp_path):
    destino = tmp_path / "expedientes"
    shutil.copytree(casos, destino)
    return destino


@pytest.fixture
def plataforma_en(tmp_path, consultor_demo):
    from mrm.chasis.plataforma import Configuracion, Plataforma

    def crear(raiz, juez=None):
        return Plataforma(Configuracion(raiz_expedientes=str(raiz), raiz_resultados=str(tmp_path / "res")), juez=juez, consultor=consultor_demo)

    return crear


def test_caso_a_sin_juez(crear_plataforma):
    expediente, _ = crear_plataforma().validar("CASO_A_PD_CURVA")
    resultados = _documentales(expediente)
    assert {k: r.veredicto.value for k, r in resultados.items()} == {
        "DOC-PD-001": "cumple", "DOC-PD-002": "no_concluyente", "DOC-PD-003": "no_cumple", "DOC-PD-004": "cumple",
    }
    ausencia = resultados["DOC-PD-003"]
    assert SECCION_A in ausencia.evidencia[0].descripcion  # la evidencia de una ausencia lista las secciones que sí hay
    assert "Hallazgo de severidad Media" not in ausencia.motivos_escalamiento  # Media no escala por severidad...
    assert "Modelo tier 1: revisión humana completa" in ausencia.motivos_escalamiento  # ...pero tier 1 sí


def test_juez_documental_con_citas_verificables(crear_plataforma):
    juez = JuezProgramado({
        "DOC-PD-002": VeredictoJuicio(
            veredicto="no_cumple",
            justificacion="Declara segmento y producto, pero no el canal ni la vigencia.",
            citas_documento=[CitaDocumento(documento=DOC_A, seccion=SECCION_A, cita="segmento personas naturales")],
            citas_practicas=[CitaPractica(nota="Declarar el perímetro de aplicación del modelo",
                                          cita="por qué canal y durante qué vigencia")],
        )
    })
    expediente, _ = crear_plataforma(juez=juez).validar("CASO_A_PD_CURVA")
    resultado = _documentales(expediente)["DOC-PD-002"]
    assert resultado.veredicto is VeredictoControl.NO_CUMPLE
    assert {e.tipo for e in resultado.evidencia} == {TipoEvidencia.ARCHIVO, TipoEvidencia.NOTA_CONOCIMIENTO}
    solicitud = next(s for s in juez.solicitudes if s.control_id == "DOC-PD-002")
    assert not solicitud.codigo and "préstamo personal" in solicitud.documento[0].texto  # contexto limpio: solo la sección
    assert "canal" in solicitud.rubrica and "vigencia" in solicitud.rubrica
    assert any(p.nota == "Declarar el perímetro de aplicación del modelo" for p in solicitud.practicas)


def test_cita_de_documento_inventada_se_anula(crear_plataforma):
    juez = JuezProgramado({
        "DOC-PD-002": VeredictoJuicio(
            veredicto="cumple",
            justificacion="Declara los cuatro elementos.",
            citas_documento=[CitaDocumento(documento=DOC_A, seccion=SECCION_A, cita="canal digital con vigencia hasta 2027")],
        )
    })
    expediente, _ = crear_plataforma(juez=juez).validar("CASO_A_PD_CURVA")
    resultado = _documentales(expediente)["DOC-PD-002"]
    assert resultado.veredicto is VeredictoControl.NO_CONCLUYENTE
    assert resultado.justificacion.startswith("[Veredicto original 'cumple' anulado")
    assert resultado.requiere_revision_humana


def test_expediente_sin_documentacion_no_concluye(copia_casos, plataforma_en):
    shutil.rmtree(copia_casos / "CASO_C_SCORING" / "documentacion")
    expediente, _ = plataforma_en(copia_casos).validar("CASO_C_SCORING")
    resultados = _documentales(expediente)
    assert all(r.veredicto is VeredictoControl.NO_CONCLUYENTE for r in resultados.values())
    assert "no trae documentación" in resultados["DOC-PD-001"].justificacion


def test_seccion_vacia_en_markdown_y_falta_de_seccion_ahorra_el_llm(copia_casos, plataforma_en):
    carpeta = copia_casos / "CASO_C_SCORING" / "documentacion"
    shutil.rmtree(carpeta)
    carpeta.mkdir()
    (carpeta / "metodologia.md").write_text(
        "# Scorecard\n\n## Versión de parámetros\n\n## Diccionario de variables\n\n| Variable | Descripción |\n|---|---|\n| edad | Edad |\n",
        encoding="utf-8",
    )
    juez = JuezProgramado({})
    expediente, _ = plataforma_en(copia_casos, juez=juez).validar("CASO_C_SCORING")
    resultados = _documentales(expediente)
    assert resultados["DOC-PD-003"].veredicto is VeredictoControl.NO_CUMPLE
    assert "existe pero tiene 0 caracteres" in resultados["DOC-PD-003"].justificacion
    assert resultados["DOC-PD-004"].veredicto is VeredictoControl.CUMPLE
    # Sin sección de perímetro el juicio se resuelve de forma determinística, sin llamar al juez.
    assert resultados["DOC-PD-002"].veredicto is VeredictoControl.NO_CUMPLE
    assert not any(s.control_id == "DOC-PD-002" for s in juez.solicitudes)
