import pytest

from evals.sintetico.docx_minimo import ESTILOS_ESPANOL, ESTILOS_INGLES, escribir_docx
from mrm.contratos.herramienta import ErrorHerramienta
from mrm.herramientas.extraer_documento.herramienta import ExtraerDocumento

extraer = ExtraerDocumento()


def test_docx_en_espanol_con_estilos_traducidos_y_tabla(tmp_path):
    ruta = tmp_path / "metodologia.docx"
    escribir_docx(ruta, [
        ("titulo", 0, "Documento metodológico"),
        ("parrafo", "Versión del documento 1.0"),
        ("titulo", 1, "2. Perímetro de aplicación"),
        ("parrafo", "Aplica al segmento personas."),
        ("titulo", 2, "2.1 Exclusiones"),
        ("parrafo", "Se excluyen créditos reprogramados."),
        ("titulo", 1, "3. Variables"),
        ("tabla", [["Variable", "Descripción"], ["score", "Puntaje de originación"]]),
    ], estilos=ESTILOS_ESPANOL)
    documento = extraer({"ruta": str(ruta)}).documento
    assert documento.formato == "docx" and len(documento.sha256) == 64
    titulos = [(s.titulo, s.nivel) for s in documento.secciones]
    assert titulos == [("Documento metodológico", 0), ("2. Perímetro de aplicación", 1), ("2.1 Exclusiones", 2), ("3. Variables", 1)]
    assert documento.secciones[0].parrafos == ["Versión del documento 1.0"]
    assert documento.secciones[2].camino == ["Documento metodológico", "2. Perímetro de aplicación", "2.1 Exclusiones"]
    assert documento.secciones[3].tablas[0].filas[1] == ["score", "Puntaje de originación"]
    assert documento.advertencias == []


def test_docx_en_ingles_y_titulos_solo_por_nivel_de_esquema(tmp_path):
    ruta = tmp_path / "manual.docx"
    escribir_docx(ruta, [
        ("parrafo", "Texto antes de cualquier título."),
        ("esquema", 1, "Alcance"),
        ("parrafo", "Contenido del alcance."),
        ("titulo", 2, "Detalle"),
        ("parrafo", "Más contenido."),
    ], estilos=ESTILOS_INGLES)
    documento = extraer({"ruta": str(ruta)}).documento
    assert [(s.titulo, s.nivel) for s in documento.secciones] == [("Preámbulo", 0), ("Alcance", 1), ("Detalle", 2)]
    assert documento.secciones[0].parrafos == ["Texto antes de cualquier título."]


def test_markdown_con_tablas_y_bloques_de_codigo(tmp_path):
    ruta = tmp_path / "doc.md"
    ruta.write_text(
        "# Metodología\n\nIntroducción del modelo.\n\n## Segmentos\n\n| Segmento | Tasa |\n|---|---|\n| PYME | 14 % |\n\n"
        "```\n# esto no es un título\n```\n\n## Vigencia\nDesde enero.\n",
        encoding="utf-8",
    )
    documento = extraer({"ruta": str(ruta)}).documento
    assert [s.titulo for s in documento.secciones] == ["Metodología", "Segmentos", "Vigencia"]
    assert documento.secciones[1].tablas[0].filas == [["Segmento", "Tasa"], ["PYME", "14 %"]]
    assert documento.secciones[2].parrafos == ["Desde enero."]


def test_sin_titulos_advierte(tmp_path):
    ruta = tmp_path / "plano.md"
    ruta.write_text("Solo un párrafo.\n", encoding="utf-8")
    documento = extraer({"ruta": str(ruta)}).documento
    assert documento.secciones[0].titulo == "Preámbulo"
    assert documento.advertencias


def test_errores_declarados(tmp_path):
    for nombre, contenido, codigo in [
        ("no_existe.docx", None, "archivo_no_encontrado"),
        ("informe.pdf", b"%PDF", "formato_no_soportado"),
        ("roto.docx", b"no es un zip", "documento_corrupto"),
    ]:
        ruta = tmp_path / nombre
        if contenido is not None:
            ruta.write_bytes(contenido)
        with pytest.raises(ErrorHerramienta) as error:
            extraer({"ruta": str(ruta)})
        assert error.value.codigo == codigo
