"""Herramienta `extraer_documento`: documento Word o Markdown -> estructura canónica de secciones.

Extracción determinística (framework C.3): Word y Markdown tienen capa de texto. Un PDF escaneado o una
imagen necesitarían OCR, con confianza declarada, y van en otra herramienta.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pydantic import BaseModel, Field

from mrm.contratos.herramienta import Herramienta, TipoHerramienta
from mrm.herramientas._comun.celdas import sha256_archivo

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_TITULO_ESTILO = re.compile(r"^(?:heading|t[ií]tulo|encabezado)\s*(\d)$", re.IGNORECASE)
_TITULO_MD = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FILA_MD = re.compile(r"^\s*\|(.*)\|\s*$")
_SEPARADOR_MD = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


class EntradaExtraerDocumento(BaseModel):
    ruta: str


class Tabla(BaseModel):
    filas: list[list[str]]


class Seccion(BaseModel):
    id: str = Field(description="Posición de la sección en el documento: s0, s1, ...")
    titulo: str
    nivel: int = Field(description="0 para el preámbulo o el título del documento; 1..9 para los títulos")
    camino: list[str] = Field(description="Títulos ancestros, del más general al propio")
    parrafos: list[str] = Field(default_factory=list)
    tablas: list[Tabla] = Field(default_factory=list)


class DocumentoCanonico(BaseModel):
    archivo: str
    sha256: str
    formato: str
    secciones: list[Seccion]
    advertencias: list[str] = Field(default_factory=list)


class SalidaExtraerDocumento(BaseModel):
    documento: DocumentoCanonico


class _Constructor:
    """Arma las secciones a medida que llegan títulos, párrafos y tablas, en orden de lectura."""

    def __init__(self):
        self.secciones: list[Seccion] = [Seccion(id="s0", titulo="Preámbulo", nivel=0, camino=["Preámbulo"])]
        self._pila: list[tuple[int, str]] = []

    def titulo(self, texto: str, nivel: int) -> None:
        while self._pila and self._pila[-1][0] >= nivel:
            self._pila.pop()
        self._pila.append((nivel, texto))
        self.secciones.append(
            Seccion(id=f"s{len(self.secciones)}", titulo=texto, nivel=nivel, camino=[t for _, t in self._pila])
        )

    def parrafo(self, texto: str) -> None:
        if texto.strip():
            self.secciones[-1].parrafos.append(texto.strip())

    def tabla(self, filas: list[list[str]]) -> None:
        if filas:
            self.secciones[-1].tablas.append(Tabla(filas=filas))

    def resultado(self) -> list[Seccion]:
        preambulo = self.secciones[0]
        return self.secciones if (preambulo.parrafos or preambulo.tablas) else self.secciones[1:]


def _texto_parrafo(parrafo: ElementTree.Element) -> str:
    partes = []
    for elemento in parrafo.iter():
        if elemento.tag == f"{W}t" and elemento.text:
            partes.append(elemento.text)
        elif elemento.tag == f"{W}tab":
            partes.append("\t")
        elif elemento.tag in (f"{W}br", f"{W}cr"):
            partes.append("\n")
    return "".join(partes)


def _niveles_de_estilo(archivo: zipfile.ZipFile) -> dict[str, int]:
    """styleId -> nivel de título. Usa el nombre interno ('heading 1', igual en Word en español) y el outlineLvl."""
    if "word/styles.xml" not in archivo.namelist():
        return {}
    raiz = ElementTree.fromstring(archivo.read("word/styles.xml"))
    nombres, bases, esquemas = {}, {}, {}
    for estilo in raiz.iter(f"{W}style"):
        if estilo.get(f"{W}type") != "paragraph":
            continue
        identificador = estilo.get(f"{W}styleId")
        nombre = estilo.find(f"{W}name")
        base = estilo.find(f"{W}basedOn")
        esquema = estilo.find(f"{W}pPr/{W}outlineLvl")
        nombres[identificador] = nombre.get(f"{W}val") if nombre is not None else identificador
        if base is not None:
            bases[identificador] = base.get(f"{W}val")
        if esquema is not None:
            esquemas[identificador] = int(esquema.get(f"{W}val")) + 1

    def nivel(identificador: str, profundidad: int = 0) -> int | None:
        if identificador is None or profundidad > 10:
            return None
        coincidencia = _TITULO_ESTILO.match((nombres.get(identificador) or "").strip())
        if coincidencia:
            return int(coincidencia.group(1))
        if (nombres.get(identificador) or "").strip().lower() in ("title", "título", "titulo"):
            return 0
        if identificador in esquemas:
            return esquemas[identificador]
        return nivel(bases.get(identificador), profundidad + 1)

    return {i: n for i in nombres if (n := nivel(i)) is not None}


def _leer_docx(ruta: Path) -> list[Seccion]:
    with zipfile.ZipFile(ruta) as archivo:
        niveles = _niveles_de_estilo(archivo)
        cuerpo = ElementTree.fromstring(archivo.read("word/document.xml")).find(f"{W}body")
    constructor = _Constructor()
    for elemento in list(cuerpo) if cuerpo is not None else []:
        if elemento.tag == f"{W}p":
            texto = _texto_parrafo(elemento)
            estilo = elemento.find(f"{W}pPr/{W}pStyle")
            esquema = elemento.find(f"{W}pPr/{W}outlineLvl")
            nivel = niveles.get(estilo.get(f"{W}val")) if estilo is not None else None
            if esquema is not None:
                nivel = int(esquema.get(f"{W}val")) + 1
            if nivel is not None and texto.strip():
                constructor.titulo(texto.strip(), nivel)
            else:
                constructor.parrafo(texto)
        elif elemento.tag == f"{W}tbl":
            filas = [
                [" ".join(_texto_parrafo(p).strip() for p in celda.iter(f"{W}p")).strip() for celda in fila.iter(f"{W}tc")]
                for fila in elemento.iter(f"{W}tr")
            ]
            constructor.tabla(filas)
    return constructor.resultado()


def _leer_markdown(ruta: Path) -> list[Seccion]:
    constructor = _Constructor()
    parrafo: list[str] = []
    tabla: list[list[str]] = []

    def cerrar() -> None:
        nonlocal parrafo, tabla
        if parrafo:
            constructor.parrafo(" ".join(parrafo))
            parrafo = []
        if tabla:
            constructor.tabla(tabla)
            tabla = []

    en_codigo = False
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if linea.strip().startswith("```"):
            en_codigo = not en_codigo
            continue
        titulo = None if en_codigo else _TITULO_MD.match(linea)
        if titulo:
            cerrar()
            constructor.titulo(titulo.group(2).strip(), len(titulo.group(1)))
        elif not en_codigo and _SEPARADOR_MD.match(linea) and tabla:
            continue
        elif not en_codigo and _FILA_MD.match(linea):
            if parrafo:
                constructor.parrafo(" ".join(parrafo))
                parrafo = []
            tabla.append([c.strip() for c in _FILA_MD.match(linea).group(1).split("|")])
        elif not linea.strip():
            cerrar()
        else:
            if tabla:
                constructor.tabla(tabla)
                tabla = []
            parrafo.append(linea.strip())
    cerrar()
    return constructor.resultado()


class ExtraerDocumento(Herramienta[EntradaExtraerDocumento, SalidaExtraerDocumento]):
    nombre = "extraer_documento"
    version = "1.0.0"
    tipo = TipoHerramienta.DETERMINISTICO
    errores = ("archivo_no_encontrado", "formato_no_soportado", "documento_corrupto")
    Entrada = EntradaExtraerDocumento
    Salida = SalidaExtraerDocumento

    def ejecutar(self, entrada: EntradaExtraerDocumento) -> SalidaExtraerDocumento:
        ruta = Path(entrada.ruta)
        if not ruta.is_file():
            raise self.fallar("archivo_no_encontrado", f"No existe {ruta.name}")
        formato = ruta.suffix.lower().lstrip(".")
        if formato not in ("docx", "md"):
            raise self.fallar("formato_no_soportado", f"Extensión .{formato} no soportada (se aceptan .docx y .md)")
        try:
            secciones = _leer_docx(ruta) if formato == "docx" else _leer_markdown(ruta)
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, UnicodeDecodeError) as error:
            raise self.fallar("documento_corrupto", f"No se pudo leer {ruta.name}: {type(error).__name__}") from error
        advertencias = []
        if not any(s.nivel > 0 for s in secciones):
            advertencias.append("El documento no tiene títulos reconocibles: todo el contenido quedó en el preámbulo")
        return SalidaExtraerDocumento(
            documento=DocumentoCanonico(
                archivo=ruta.name, sha256=sha256_archivo(ruta), formato=formato, secciones=secciones, advertencias=advertencias
            )
        )
