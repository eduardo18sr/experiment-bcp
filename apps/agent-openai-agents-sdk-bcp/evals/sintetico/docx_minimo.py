"""Escritor mínimo de .docx para documentos sintéticos (sin dependencias externas).

Escribe un paquete OOXML válido con estilos de título. Permite elegir los identificadores de estilo para
probar documentos de Word en inglés ("Heading1") y en español ("Ttulo1", cuyo nombre interno sigue siendo
"heading 1"), que es como los guarda Word.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ESTILOS_INGLES = {0: "Title", 1: "Heading1", 2: "Heading2", 3: "Heading3"}
ESTILOS_ESPANOL = {0: "Puesto", 1: "Ttulo1", 2: "Ttulo2", 3: "Ttulo3"}

_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _parrafo(texto: str, estilo: str | None = None, nivel_esquema: int | None = None) -> str:
    propiedades = ""
    if estilo or nivel_esquema is not None:
        propiedades = "<w:pPr>"
        propiedades += f'<w:pStyle w:val="{estilo}"/>' if estilo else ""
        propiedades += f'<w:outlineLvl w:val="{nivel_esquema}"/>' if nivel_esquema is not None else ""
        propiedades += "</w:pPr>"
    return f'<w:p>{propiedades}<w:r><w:t xml:space="preserve">{escape(texto)}</w:t></w:r></w:p>'


def _tabla(filas: list[list[str]]) -> str:
    cuerpo = "".join(
        "<w:tr>" + "".join(f"<w:tc>{_parrafo(celda)}</w:tc>" for celda in fila) + "</w:tr>" for fila in filas
    )
    return f"<w:tbl><w:tblPr/>{cuerpo}</w:tbl>"


def _estilos(ids: dict[int, str]) -> str:
    estilos = []
    for nivel, identificador in ids.items():
        nombre = "Title" if nivel == 0 else f"heading {nivel}"
        estilos.append(
            f'<w:style w:type="paragraph" w:styleId="{identificador}"><w:name w:val="{nombre}"/>'
            f'<w:basedOn w:val="Normal"/><w:qFormat/></w:style>'
        )
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {_NS}>'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
        + "".join(estilos)
        + "</w:styles>"
    )


def escribir_docx(ruta: Path, bloques: list[tuple], estilos: dict[int, str] = ESTILOS_INGLES) -> None:
    """bloques: ("titulo", nivel, texto) · ("parrafo", texto) · ("tabla", filas) · ("esquema", nivel, texto).

    "esquema" crea un título sin estilo, marcado solo con nivel de esquema en el párrafo.
    """
    cuerpo = []
    for bloque in bloques:
        tipo = bloque[0]
        if tipo == "titulo":
            cuerpo.append(_parrafo(bloque[2], estilo=estilos[bloque[1]]))
        elif tipo == "esquema":
            cuerpo.append(_parrafo(bloque[2], nivel_esquema=bloque[1] - 1))
        elif tipo == "parrafo":
            cuerpo.append(_parrafo(bloque[1]))
        elif tipo == "tabla":
            cuerpo.append(_tabla(bloque[1]))
    documento = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_NS}><w:body>'
        + "".join(cuerpo)
        + '<w:sectPr/></w:body></w:document>'
    )
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as archivo:
        archivo.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            "</Types>",
        )
        archivo.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        archivo.writestr(
            "word/_rels/document.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>",
        )
        archivo.writestr("word/document.xml", documento)
        archivo.writestr("word/styles.xml", _estilos(estilos))
