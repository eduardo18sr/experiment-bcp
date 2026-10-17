"""Skill `revisar-documentacion`: controles sobre la documentación metodológica del expediente.

Los documentos se buscan en la carpeta que fija la configuración de la skill (por defecto `documentacion/`
dentro del expediente). Las citas de documentos se verifican aquí contra la sección extraída; el guardrail
del chasis todavía no sabe verificar citas dentro de documentos (ver docs/specs/deltas/DELTA-001).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from mrm.contratos.control import Control
from mrm.contratos.herramienta import ErrorHerramienta
from mrm.contratos.resultado import Evidencia, ResultadoControl, TipoEvidencia, VeredictoControl
from mrm.contratos.skill import ContextoSkill, ResultadoSkill, Skill
from mrm.herramientas._comun.celdas import nombre_normalizado
from mrm.juicio.puerto import FragmentoDocumento, PracticaContexto, SolicitudJuicio


def _normalizar_texto(texto: str) -> str:
    return " ".join(texto.split())


@dataclass
class SeccionEncontrada:
    documento: str = field(metadata={"descripcion": "Ruta relativa al expediente"})
    titulo: str = ""
    parrafos: list[str] = field(default_factory=list)
    tablas: list[list[list[str]]] = field(default_factory=list)

    @property
    def texto(self) -> str:
        celdas = [" ".join(c for c in fila if c) for tabla in self.tablas for fila in tabla]
        return "\n".join(self.parrafos + celdas)


class RevisarDocumentacion(Skill):
    nombre = "revisar-documentacion"

    def ejecutar(self, contexto: ContextoSkill) -> ResultadoSkill:
        parametros = contexto.configuracion.parametros
        carpeta = str(parametros.get("carpeta_documentos", "documentacion")).strip("/")
        extensiones = tuple(e.lower() for e in parametros.get("extensiones", [".docx", ".md"]))
        limitaciones: list[str] = []
        documentos: list[tuple[str, Any]] = []
        directorio = contexto.ruta(carpeta)
        rutas = sorted(p for p in directorio.rglob("*") if p.is_file() and p.suffix.lower() in extensiones) if directorio.is_dir() else []
        for ruta in rutas:
            relativa = f"{carpeta}/{ruta.relative_to(directorio).as_posix()}"
            try:
                documentos.append((relativa, contexto.herramienta("extraer_documento")({"ruta": str(ruta)}).documento))
            except ErrorHerramienta as error:
                limitaciones.append(f"{relativa}: {error}")
        for relativa, documento in documentos:
            limitaciones.extend(f"{relativa}: {a}" for a in documento.advertencias)

        reglas = _Reglas(contexto, documentos, carpeta)
        return ResultadoSkill(
            resultados_control=[reglas.evaluar(control) for control in contexto.controles],
            limitaciones=limitaciones,
            hechos={
                "documentos": [
                    {"ruta": r, "formato": d.formato, "secciones": len(d.secciones), "sha256": d.sha256} for r, d in documentos
                ],
                "llamadas_juez": reglas.llamadas_juez,
            },
        )


class _Reglas:
    def __init__(self, contexto: ContextoSkill, documentos: list[tuple[str, Any]], carpeta: str):
        self.contexto = contexto
        self.documentos = documentos
        self.carpeta = carpeta
        self.llamadas_juez = 0
        self._reglas: dict[str, Callable[[Control], ResultadoControl]] = {
            "presencia_seccion": self._presencia_seccion,
            "presencia_tabla": self._presencia_tabla,
            "suficiencia_contenido": self._suficiencia_contenido,
        }

    # --- utilidades -------------------------------------------------------------------------------------
    def evaluar(self, control: Control) -> ResultadoControl:
        if not self.documentos:
            return self._resultado(
                control, VeredictoControl.NO_CONCLUYENTE,
                f"El expediente no trae documentación en la carpeta '{self.carpeta}/': no se puede verificar el control.", [],
            )
        regla = self._reglas.get(control.regla)
        if regla is None:
            return self._resultado(control, VeredictoControl.NO_CONCLUYENTE, f"La skill no implementa la regla {control.regla}", [])
        try:
            return regla(control)
        except ErrorHerramienta as error:
            return self._resultado(control, VeredictoControl.NO_CONCLUYENTE, "Una herramienta falló durante la evaluación", [],
                                   limitaciones=[str(error)])

    def _criterio(self, control: Control, clave: str, defecto: Any = None) -> Any:
        return self.contexto.catalogo.criterio(control, clave, defecto)

    @staticmethod
    def _resultado(control, veredicto, justificacion, evidencia, limitaciones=None) -> ResultadoControl:
        return ResultadoControl(
            control_id=control.id, nombre=control.nombre, tipo=control.tipo, veredicto=veredicto,
            severidad=control.severidad, justificacion=justificacion, evidencia=evidencia, limitaciones=limitaciones or [],
        )

    def _buscar(self, titulos: list[str]) -> list[SeccionEncontrada]:
        """Secciones cuyo título contiene alguno de los títulos equivalentes, con todo su subárbol."""
        buscados = [nombre_normalizado(t) for t in titulos]
        encontradas = []
        for relativa, documento in self.documentos:
            secciones = documento.secciones
            for indice, seccion in enumerate(secciones):
                if seccion.nivel == 0 or not any(b and b in nombre_normalizado(seccion.titulo) for b in buscados):
                    continue
                encontrada = SeccionEncontrada(documento=relativa, titulo=seccion.titulo)
                for siguiente in secciones[indice:]:
                    if siguiente is not seccion and 0 < siguiente.nivel <= seccion.nivel:
                        break
                    encontrada.parrafos.extend(siguiente.parrafos)
                    encontrada.tablas.extend(t.filas for t in siguiente.tablas)
                encontradas.append(encontrada)
        return encontradas

    def _evidencia_seccion(self, seccion: SeccionEncontrada, descripcion: str) -> Evidencia:
        primera = next((p for p in seccion.parrafos if p.strip()), "")
        return Evidencia(
            tipo=TipoEvidencia.ARCHIVO, fuente=seccion.documento, ubicacion=f"sección «{seccion.titulo}»",
            cita=primera[:160] or None, descripcion=descripcion,
        )

    def _evidencia_ausencia(self) -> list[Evidencia]:
        return [
            Evidencia(
                tipo=TipoEvidencia.ARCHIVO, fuente=relativa, ubicacion="documento completo",
                descripcion="Secciones del documento: " + "; ".join(s.titulo for s in documento.secciones if s.nivel > 0)[:400],
            )
            for relativa, documento in self.documentos
        ]

    # --- reglas -----------------------------------------------------------------------------------------
    def _presencia_seccion(self, control: Control) -> ResultadoControl:
        titulos = list(self._criterio(control, "titulos", []))
        minimo = int(self._criterio(control, "minimo_caracteres", 40))
        encontradas = self._buscar(titulos)
        if not encontradas:
            return self._resultado(
                control, VeredictoControl.NO_CUMPLE,
                f"Ningún documento tiene una sección equivalente a: {', '.join(titulos)}.", self._evidencia_ausencia(),
            )
        mejor = max(encontradas, key=lambda s: len(_normalizar_texto(s.texto)))
        caracteres = len(_normalizar_texto(mejor.texto))
        if caracteres < minimo:
            return self._resultado(
                control, VeredictoControl.NO_CUMPLE,
                f"La sección «{mejor.titulo}» de {mejor.documento} existe pero tiene {caracteres} caracteres de contenido (mínimo {minimo}).",
                [self._evidencia_seccion(mejor, "Sección sin contenido suficiente")],
            )
        return self._resultado(
            control, VeredictoControl.CUMPLE,
            f"La sección «{mejor.titulo}» de {mejor.documento} existe y tiene contenido.",
            [self._evidencia_seccion(mejor, f"{caracteres} caracteres de contenido")],
        )

    def _presencia_tabla(self, control: Control) -> ResultadoControl:
        titulos = list(self._criterio(control, "titulos", []))
        columnas = [nombre_normalizado(c) for c in self._criterio(control, "columnas", [])]
        filas_minimas = int(self._criterio(control, "filas_minimas", 1))
        encontradas = self._buscar(titulos)
        if not encontradas:
            return self._resultado(
                control, VeredictoControl.NO_CUMPLE,
                f"Ningún documento tiene una sección equivalente a: {', '.join(titulos)}.", self._evidencia_ausencia(),
            )
        vistas = []
        for seccion in encontradas:
            for tabla in seccion.tablas:
                encabezado = [nombre_normalizado(c) for c in tabla[0]] if tabla else []
                vistas.append(", ".join(tabla[0]) if tabla else "")
                tiene_columnas = all(any(col in h for h in encabezado) for col in columnas)
                if tiene_columnas and len(tabla) - 1 >= filas_minimas:
                    return self._resultado(
                        control, VeredictoControl.CUMPLE,
                        f"La sección «{seccion.titulo}» de {seccion.documento} tiene una tabla con las columnas requeridas "
                        f"y {len(tabla) - 1} filas.",
                        [Evidencia(tipo=TipoEvidencia.ARCHIVO, fuente=seccion.documento, ubicacion=f"sección «{seccion.titulo}»",
                                   descripcion=f"Tabla con columnas: {', '.join(tabla[0])}")],
                    )
        detalle = f" Tablas encontradas: {' / '.join(vistas)}." if vistas else " La sección no tiene tablas."
        return self._resultado(
            control, VeredictoControl.NO_CUMPLE,
            f"No hay una tabla con las columnas {', '.join(self._criterio(control, 'columnas', []))} "
            f"y al menos {filas_minimas} fila(s).{detalle}",
            [self._evidencia_seccion(encontradas[0], "Sección revisada")],
        )

    def _suficiencia_contenido(self, control: Control) -> ResultadoControl:
        titulos = list(self._criterio(control, "titulos", []))
        encontradas = self._buscar(titulos)
        if not encontradas:
            # Determinístico: si no hay sección, el documento no lo declara; no hace falta gastar una llamada al LLM.
            return self._resultado(
                control, VeredictoControl.NO_CUMPLE,
                f"El documento no tiene una sección equivalente a: {', '.join(titulos)}; no declara lo exigido.",
                self._evidencia_ausencia(),
            )
        juez = self.contexto.juez
        if juez is None:
            return self._resultado(control, VeredictoControl.NO_CONCLUYENTE,
                                   "No hay juez configurado para controles de juicio; requiere revisión humana.", [])
        practicas = []
        try:
            practicas = self.contexto.herramienta("consultar_conocimiento")(
                {"consulta": self._criterio(control, "consulta", control.nombre), "k": 4}
            ).practicas
        except ErrorHerramienta:
            pass  # el juez puede dictaminar con la rúbrica; la limitación queda registrada abajo
        maximo = int(self.contexto.configuracion.parametros.get("max_caracteres_juez", 4000))
        elementos = self._criterio(control, "elementos", [])
        rubrica = str(self._criterio(control, "rubrica", ""))
        if elementos:
            rubrica = f"{rubrica} Elementos que deben declararse de forma explícita: {', '.join(elementos)}.".strip()
        solicitud = SolicitudJuicio(
            control_id=control.id, enunciado_ears=control.enunciado_ears, evidencia_requerida=control.evidencia_requerida,
            rubrica=rubrica,
            documento=[FragmentoDocumento(documento=s.documento, seccion=s.titulo, texto=s.texto[:maximo]) for s in encontradas],
            practicas=[PracticaContexto(nota=p.nota, seccion=p.seccion, cita=p.cita) for p in practicas],
        )
        self.llamadas_juez += 1
        try:
            veredicto_juez = juez.juzgar(solicitud)
        except Exception as error:  # noqa: BLE001 - un fallo del LLM escala; nunca tumba la dimensión
            return self._resultado(control, VeredictoControl.NO_CONCLUYENTE, "El juez no pudo emitir un veredicto.", [],
                                   limitaciones=[f"{type(error).__name__}: {error}"])

        limitaciones = [f"Veredicto de juicio emitido por {getattr(juez, 'nombre', 'juez')}"]
        if not practicas:
            limitaciones.append("Sin prácticas recuperadas del grafo: el juez dictaminó solo con la rúbrica")
        por_titulo = {(s.documento, s.titulo): _normalizar_texto(s.texto) for s in encontradas}
        no_verificables = [
            c for c in veredicto_juez.citas_documento
            if _normalizar_texto(c.cita) not in por_titulo.get((c.documento, c.seccion), "") or not c.cita.strip()
        ]
        evidencia = [
            Evidencia(tipo=TipoEvidencia.ARCHIVO, fuente=c.documento, ubicacion=f"sección «{c.seccion}»", cita=c.cita,
                      descripcion="Citada por el juez (verificada contra la sección)")
            for c in veredicto_juez.citas_documento if c not in no_verificables
        ] + [
            Evidencia(tipo=TipoEvidencia.NOTA_CONOCIMIENTO, fuente=c.nota, ubicacion="nota", cita=c.cita,
                      descripcion="Práctica citada por el juez")
            for c in veredicto_juez.citas_practicas
        ]
        veredicto = VeredictoControl(veredicto_juez.veredicto)
        justificacion = veredicto_juez.justificacion
        if no_verificables:
            limitaciones.extend(f"Cita de documento no verificable en «{c.seccion}»: {c.cita[:80]}" for c in no_verificables)
            justificacion = f"[Veredicto original '{veredicto.value}' anulado: el juez citó texto que no está en el documento] {justificacion}"
            veredicto = VeredictoControl.NO_CONCLUYENTE
        if veredicto is VeredictoControl.CUMPLE and not evidencia:
            veredicto = VeredictoControl.NO_CONCLUYENTE
            limitaciones.append("El juez concluyó 'cumple' sin citar evidencia")
        return self._resultado(control, veredicto, justificacion, evidencia, limitaciones)
