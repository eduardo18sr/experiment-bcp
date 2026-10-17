"""Reglas de evaluación: traducen hechos de herramientas a veredictos por control.

Cada regla recibe el control (con su criterio de negocio) y los hechos ya recogidos. Ninguna regla llama
al LLM salvo `buenas_practicas_codigo`, que es el único control de juicio, y lo hace a través del puerto del
juez con contexto limpio. Las justificaciones nunca incluyen valores numéricos de parámetros: esos van en
`Evidencia.valor`, que no se envía al LLM.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from mrm.contratos.control import Control
from mrm.contratos.herramienta import ErrorHerramienta
from mrm.contratos.resultado import (
    Aplicabilidad,
    EstadoEjecucion,
    Evidencia,
    ResultadoComponente,
    ResultadoControl,
    TipoEvidencia,
    VeredictoComponente,
    VeredictoControl,
)
from mrm.contratos.skill import ContextoSkill
from mrm.juicio.puerto import FragmentoCodigo, PracticaContexto, SolicitudJuicio
from mrm.skills.validar_implementacion_calculo.hechos import (
    VARIANTE_ACTIVA,
    VARIANTE_ALINEADA,
    Hechos,
    Serie,
)

DIVERGENTES = (VeredictoComponente.DIVERGE, VeredictoComponente.PARCIAL)


def _fmt(valor: Any) -> str:
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)


def _tramos(tramos: list[list[Any]]) -> str:
    return ", ".join(_fmt(a) if a == b else f"{_fmt(a)}–{_fmt(b)}" for a, b in tramos) or "ninguno"


class EvaluadorReglas:
    def __init__(self, contexto: ContextoSkill, hechos: Hechos):
        self.contexto = contexto
        self.hechos = hechos
        self.solicitud = hechos.solicitud
        self.raiz = self.solicitud.implementacion.raiz.rstrip("/")
        self.resultados_componentes: list[ResultadoComponente] = []
        self._funciones = {f"{f.modulo}:{f.nombre}": f for f in hechos.indice.funciones}
        self._reglas: dict[str, Callable[[Control], ResultadoControl]] = {
            "reproduccion_salida_principal": self._reproduccion_salida_principal,
            "equivalencia_logica": self._equivalencia_logica,
            "precision_parametros": self._precision_parametros,
            "version_parametros": self._version_parametros,
            "reglas_derivadas": self._reglas_derivadas,
            "fronteras_rango": self._fronteras_rango,
            "buenas_practicas_codigo": self._buenas_practicas_codigo,
        }

    # --- entrada pública --------------------------------------------------------------------------------
    def evaluar(self, control: Control) -> ResultadoControl:
        regla = self._reglas.get(control.regla)
        if regla is None:
            return self._resultado(control, VeredictoControl.NO_CONCLUYENTE, f"La skill no implementa la regla {control.regla}", [])
        try:
            return regla(control)
        except ErrorHerramienta as error:
            return self._resultado(
                control, VeredictoControl.NO_CONCLUYENTE, "Una herramienta falló durante la evaluación", [], limitaciones=[str(error)]
            )

    def resumen_hechos(self) -> dict[str, Any]:
        h = self.hechos
        parches = [p.model_dump() for e in h.ejecuciones.get(VARIANTE_ALINEADA, []) for p in e.parche]
        return {
            "oraculo_valido": h.oraculo.oraculo_valido,
            "celdas_validadas_contra_cache": h.oraculo.celdas_validadas,
            "variantes": h.variantes,
            "parche_variante_alineada": list({(p["archivo"], p["linea"]): p for p in parches}.values()),
            "original_intacto": all(e.original_intacto for ejec in h.ejecuciones.values() for e in ejec),
            "condiciones_de_rango": len(h.fronteras.condiciones) if h.fronteras else 0,
            "casos_frontera": len(h.casos_frontera),
            "variante_fronteras": h.variante_fronteras,
            "llamadas_juez": h.llamadas_juez,
            "parametros": [
                {
                    "tabla": t.id,
                    "archivos": [
                        {"ruta": a.ruta, "uso": a.uso, "coincidencia": a.coincidencia, "clasificacion": a.clasificacion,
                         "comparados": a.comparados, "coincidencias": a.coincidencias}
                        for a in t.archivos
                    ],
                }
                for t in (h.parametros.tablas if h.parametros else [])
            ],
        }

    # --- utilidades -------------------------------------------------------------------------------------
    def _resultado(self, control, veredicto, justificacion, evidencia, componentes=None, limitaciones=None) -> ResultadoControl:
        return ResultadoControl(
            control_id=control.id,
            nombre=control.nombre,
            tipo=control.tipo,
            veredicto=veredicto,
            severidad=control.severidad,
            justificacion=justificacion,
            evidencia=evidencia,
            componentes=componentes or [],
            limitaciones=limitaciones or [],
        )

    def _no_aplica(self, control: Control, motivo: str) -> ResultadoControl:
        return ResultadoControl(
            control_id=control.id,
            nombre=control.nombre,
            tipo=control.tipo,
            aplicabilidad=Aplicabilidad.NO_APLICA,
            severidad=control.severidad,
            justificacion=motivo,
        )

    def _tolerancia(self, control: Control, serie: Serie | None = None) -> dict[str, float]:
        if serie is not None and serie.componente.tolerancia is not None:
            return {"absoluta": serie.componente.tolerancia.absoluta, "relativa": serie.componente.tolerancia.relativa}
        catalogo = self.contexto.catalogo
        return {
            "absoluta": float(catalogo.criterio(control, "tolerancia_absoluta", 1e-8)),
            "relativa": float(catalogo.criterio(control, "tolerancia_relativa", 0.0)),
        }

    def _evidencia_funcion(self, funcion: str) -> Evidencia | None:
        indexada = self._funciones.get(funcion)
        if indexada is None:
            return None
        return Evidencia(
            tipo=TipoEvidencia.LINEA_CODIGO,
            fuente=f"{self.raiz}/{indexada.ruta}",
            ubicacion=str(indexada.linea),
            cita=f"def {indexada.nombre}",
            descripcion="Función productiva ejecutada",
        )

    def _evidencia_celda(self, referencia_completa: str, descripcion: str) -> Evidencia:
        return Evidencia(
            tipo=TipoEvidencia.CELDA, fuente=self.solicitud.referencia.excel, ubicacion=referencia_completa, descripcion=descripcion
        )

    def _comparar(self, control: Control, serie: Serie, estrategia: str = "ejecucion_productiva") -> ResultadoComponente:
        tolerancia = self._tolerancia(control, serie)
        componente = serie.componente
        evidencia = [self._evidencia_celda(componente.referencia.completa(), f"Referencia de {componente.id}")]
        limitaciones = []
        if componente.tolerancia is not None:
            limitaciones.append(f"Tolerancia declarada en el expediente: {componente.tolerancia.justificacion}")
        evidencia_funcion = self._evidencia_funcion(componente.implementacion.funcion)
        if evidencia_funcion:
            evidencia.append(evidencia_funcion)
        else:
            limitaciones.append(f"La función {componente.implementacion.funcion} no aparece en el índice del proyecto")

        if serie.estado is not EstadoEjecucion.COMPLETADA:
            resultado = ResultadoComponente(
                componente_id=componente.id, control_id=control.id, estrategia=estrategia, variante=serie.variante,
                estado_ejecucion=serie.estado, veredicto=VeredictoComponente.NO_CONCLUYENTE, tolerancia=tolerancia,
                evidencia=evidencia, limitaciones=limitaciones + [serie.error or "Sin ejecución"],
            )
            self.resultados_componentes.append(resultado)
            return resultado

        comparacion = self.contexto.herramienta("comparar_series")(
            {"referencia": serie.referencia, "implementacion": serie.implementacion or [],
             "etiquetas": serie.etiquetas, "tolerancia": tolerancia}
        )
        if comparacion.comparados == 0:
            veredicto = VeredictoComponente.NO_CONCLUYENTE
            limitaciones.append("No hubo puntos comparables")
        elif comparacion.coincidencias == comparacion.comparados and comparacion.no_comparables == 0:
            veredicto = VeredictoComponente.COINCIDE
        elif comparacion.coincidencias == 0:
            veredicto = VeredictoComponente.DIVERGE
        else:
            veredicto = VeredictoComponente.PARCIAL
        evidencia.append(
            Evidencia(
                tipo=TipoEvidencia.HECHO,
                fuente=componente.id,
                ubicacion=f"variante {serie.variante}",
                descripcion=f"{comparacion.coincidencias}/{comparacion.comparados} puntos dentro de tolerancia",
                valor={"max_dif_abs": comparacion.max_dif_abs, "max_dif_rel": comparacion.max_dif_rel},
            )
        )
        resultado = ResultadoComponente(
            componente_id=componente.id, control_id=control.id, estrategia=estrategia, variante=serie.variante,
            estado_ejecucion=EstadoEjecucion.COMPLETADA, veredicto=veredicto,
            comparados=comparacion.comparados, coincidencias=comparacion.coincidencias,
            max_dif_abs=comparacion.max_dif_abs, tolerancia=tolerancia, evidencia=evidencia, limitaciones=limitaciones,
            detalle={
                "primera_divergencia": comparacion.primera_divergencia,
                "tramos_coincidentes": comparacion.tramos_coincidentes,
                "tramos_divergentes": comparacion.tramos_divergentes,
                "no_comparables": comparacion.no_comparables,
                "longitudes": [comparacion.longitud_referencia, comparacion.longitud_implementacion],
            },
        )
        self.resultados_componentes.append(resultado)
        return resultado

    @staticmethod
    def _describir(resultados: list[ResultadoComponente]) -> str:
        return "; ".join(f"{r.componente_id} ({r.coincidencias}/{r.comparados})" for r in resultados)

    def _veredicto_de(self, resultados: list[ResultadoComponente]) -> VeredictoControl:
        if any(r.veredicto in DIVERGENTES for r in resultados):
            return VeredictoControl.NO_CUMPLE
        if resultados and all(r.veredicto is VeredictoComponente.COINCIDE for r in resultados):
            return VeredictoControl.CUMPLE
        return VeredictoControl.NO_CONCLUYENTE

    @staticmethod
    def _evidencias(resultados: list[ResultadoComponente]) -> list[Evidencia]:
        vistas, evidencias = set(), []
        for resultado in resultados:
            for evidencia in resultado.evidencia:
                clave = (evidencia.tipo, evidencia.fuente, evidencia.ubicacion, evidencia.descripcion)
                if clave not in vistas:
                    vistas.add(clave)
                    evidencias.append(evidencia)
        return evidencias

    # --- reglas -----------------------------------------------------------------------------------------
    def _reproduccion_salida_principal(self, control: Control) -> ResultadoControl:
        series = self.hechos.series_de("salida", VARIANTE_ACTIVA)
        if not series:
            return self._no_aplica(control, "El expediente no declara componentes de salida")
        resultados = [self._comparar(control, s) for s in series]
        veredicto = self._veredicto_de(resultados)
        divergentes = [r for r in resultados if r.veredicto in DIVERGENTES]
        coinciden = [r for r in resultados if r.veredicto is VeredictoComponente.COINCIDE]
        if veredicto is VeredictoControl.NO_CUMPLE:
            texto = f"Con los parámetros que carga, la implementación no reproduce: {self._describir(divergentes)}."
            if coinciden:
                texto += f" Sí reproduce: {self._describir(coinciden)}."
        elif veredicto is VeredictoControl.CUMPLE:
            texto = f"La implementación reproduce todas las salidas principales: {self._describir(coinciden)}."
        else:
            texto = "No se pudo ejecutar o comparar alguna salida principal."
        return self._resultado(
            control, veredicto, texto, self._evidencias(resultados), [r.componente_id for r in resultados],
            [l for r in resultados for l in r.limitaciones],
        )

    def _equivalencia_logica(self, control: Control) -> ResultadoControl:
        series = self.hechos.series_de("salida", VARIANTE_ACTIVA)
        if not series:
            return self._no_aplica(control, "El expediente no declara componentes de salida")
        activos = [self._comparar(control, s) for s in series]
        if all(r.veredicto is VeredictoComponente.COINCIDE for r in activos):
            return self._resultado(
                control, VeredictoControl.CUMPLE,
                "La implementación reproduce la referencia con los parámetros que carga: la lógica es equivalente en el punto evaluado.",
                self._evidencias(activos), [r.componente_id for r in activos],
            )
        if not any(r.veredicto in DIVERGENTES for r in activos):
            return self._resultado(control, VeredictoControl.NO_CONCLUYENTE, "No se pudo ejecutar o comparar alguna salida principal.",
                                   self._evidencias(activos), limitaciones=[l for r in activos for l in r.limitaciones])
        if not self.hechos.tiene_alineada:
            return self._resultado(
                control, VeredictoControl.NO_CONCLUYENTE,
                "La implementación diverge y el proyecto no contiene una versión de parámetros que coincida con la referencia: "
                "no se puede separar la lógica de los parámetros. Requiere decisión del validador.",
                self._evidencias(activos), [r.componente_id for r in activos],
            )
        alineados = [self._comparar(control, s) for s in self.hechos.series_de("salida", VARIANTE_ALINEADA)]
        evidencia = self._evidencias(alineados) + self._evidencia_parche()
        veredicto = self._veredicto_de(alineados)
        if veredicto is VeredictoControl.CUMPLE:
            texto = (
                f"Con parámetros alineados a la referencia la implementación reproduce {self._describir(alineados)}: "
                "la divergencia de la variante activa se explica por la versión de parámetros, no por la lógica."
            )
        elif veredicto is VeredictoControl.NO_CUMPLE:
            texto = f"Incluso con parámetros alineados la implementación no reproduce: {self._describir([r for r in alineados if r.veredicto in DIVERGENTES])}."
        else:
            texto = "La variante con parámetros alineados no pudo ejecutarse o compararse."
        return self._resultado(control, veredicto, texto, evidencia, [r.componente_id for r in alineados],
                               [l for r in alineados for l in r.limitaciones])

    def _evidencia_parche(self) -> list[Evidencia]:
        evidencias, vistos = [], set()
        for ejecucion in self.hechos.ejecuciones.get(VARIANTE_ALINEADA, []):
            for parche in ejecucion.parche:
                if (parche.archivo, parche.linea) in vistos:
                    continue
                vistos.add((parche.archivo, parche.linea))
                evidencias.append(
                    Evidencia(
                        tipo=TipoEvidencia.LINEA_CODIGO,
                        fuente=f"{self.raiz}/{parche.archivo}",
                        ubicacion=str(parche.linea),
                        cita=parche.antes,
                        descripcion=f"Sustituida solo en la copia aislada por: {parche.despues}",
                    )
                )
        return evidencias

    def _tablas(self):
        return self.hechos.parametros.tablas if self.hechos.parametros else []

    def _evidencia_archivo(self, archivo, descripcion: str) -> list[Evidencia]:
        evidencias = [Evidencia(tipo=TipoEvidencia.ARCHIVO, fuente=f"{self.raiz}/{archivo.ruta}", ubicacion="archivo", descripcion=descripcion)]
        for referencia in archivo.referencias:
            evidencias.append(
                Evidencia(
                    tipo=TipoEvidencia.LINEA_CODIGO,
                    fuente=f"{self.raiz}/{referencia.ruta}",
                    ubicacion=str(referencia.linea),
                    cita=referencia.texto,
                    descripcion=f"Referencia {referencia.estado.value.lower()} a {archivo.ruta.rsplit('/', 1)[-1]}",
                )
            )
        return evidencias

    def _precision_parametros(self, control: Control) -> ResultadoControl:
        if not self.solicitud.tablas_parametros:
            return self._no_aplica(control, "El expediente no declara tablas de parámetros")
        divergentes, indeterminadas, evidencia, textos = [], [], [], []
        for tabla in self._tablas():
            comparables = [a for a in tabla.archivos if a.coincidencia != "NO_COMPARABLE"]
            activos = [a for a in comparables if a.uso == "ACTIVO"]
            evidencia.append(self._evidencia_celda(f"{self._ref_tabla(tabla.id)}", f"Tabla de referencia {tabla.id}"))
            if not activos:
                indeterminadas.append(tabla.id)
                textos.append(f"{tabla.id}: no se identificó un archivo que el código cargue de forma literal")
                continue
            for archivo in activos:
                descripcion = f"{tabla.id}: {archivo.coincidencias}/{archivo.comparados} valores coinciden"
                evidencia.extend(self._evidencia_archivo(archivo, descripcion))
                evidencia.append(
                    Evidencia(tipo=TipoEvidencia.HECHO, fuente=tabla.id, ubicacion=archivo.ruta, descripcion=descripcion,
                              valor={"max_dif_abs": archivo.max_dif_abs, "diferencias": [d.model_dump() for d in archivo.diferencias]})
                )
                self.resultados_componentes.append(
                    ResultadoComponente(
                        componente_id=f"{tabla.id}:{archivo.ruta}", control_id=control.id, estrategia="parametros",
                        estado_ejecucion=EstadoEjecucion.COMPLETADA,
                        veredicto=VeredictoComponente.COINCIDE if archivo.coincidencia == "COINCIDE"
                        else (VeredictoComponente.DIVERGE if archivo.coincidencias == 0 else VeredictoComponente.PARCIAL),
                        comparados=archivo.comparados, coincidencias=archivo.coincidencias, max_dif_abs=archivo.max_dif_abs,
                        tolerancia=self._tolerancia(control), detalle={"faltantes": archivo.faltantes, "clasificacion": archivo.clasificacion},
                    )
                )
                if archivo.coincidencia == "NO_COINCIDE":
                    divergentes.append(archivo)
                    textos.append(f"{tabla.id}: el código carga {archivo.ruta} y {archivo.comparados - archivo.coincidencias} de {archivo.comparados} valores difieren de la referencia")
                else:
                    textos.append(f"{tabla.id}: el código carga {archivo.ruta}, que coincide con la referencia ({archivo.coincidencias}/{archivo.comparados})")
        if divergentes:
            veredicto = VeredictoControl.NO_CUMPLE
        elif indeterminadas:
            veredicto = VeredictoControl.NO_CONCLUYENTE
        else:
            veredicto = VeredictoControl.CUMPLE
        return self._resultado(control, veredicto, "; ".join(textos) + ".", evidencia)

    def _ref_tabla(self, tabla_id: str) -> str:
        tabla = next(t for t in self.solicitud.tablas_parametros if t.id == tabla_id)
        return tabla.referencia.completa()

    def _version_parametros(self, control: Control) -> ResultadoControl:
        if not self.solicitud.tablas_parametros:
            return self._no_aplica(control, "El expediente no declara tablas de parámetros")
        hallazgos, dinamicas, sin_activo, evidencia, textos = [], [], [], [], []
        for tabla in self._tablas():
            comparables = [a for a in tabla.archivos if a.coincidencia != "NO_COMPARABLE"]
            activos = [a for a in comparables if a.uso == "ACTIVO"]
            usados = f"se usa {len(activos)} de {len(comparables)} archivos candidatos"
            activos_sin = [a for a in activos if a.coincidencia == "NO_COINCIDE"]
            alternativos = [a for a in comparables if a.uso in ("COMENTADO", "NO_REFERENCIADO") and a.coincidencia == "COINCIDE"]
            for archivo in comparables:
                evidencia.extend(self._evidencia_archivo(archivo, f"{tabla.id}: {archivo.clasificacion}"))
            if activos_sin and alternativos:
                hallazgos.append(tabla.id)
                textos.append(
                    f"{tabla.id}: {usados}; se carga {', '.join(a.ruta for a in activos_sin)} (SE_USA_SIN_COINCIDENCIA) "
                    f"mientras {', '.join(a.ruta for a in alternativos)} coincide con la referencia y no se usa "
                    f"({', '.join(a.clasificacion + ', ' + a.uso.lower() for a in alternativos)})"
                )
            elif any(a.uso == "DINAMICO" for a in comparables):
                dinamicas.append(tabla.id)
                textos.append(f"{tabla.id}: la ruta del archivo se construye dinámicamente; no se puede determinar qué versión se carga")
            elif not activos:
                sin_activo.append(tabla.id)
                textos.append(f"{tabla.id}: ningún archivo candidato se carga de forma literal")
            else:
                textos.append(f"{tabla.id}: {usados}; no hay otra versión del proyecto que coincida mejor con la referencia")
        if hallazgos:
            veredicto = VeredictoControl.NO_CUMPLE
        elif dinamicas or sin_activo:
            veredicto = VeredictoControl.NO_CONCLUYENTE
        else:
            veredicto = VeredictoControl.CUMPLE
        return self._resultado(control, veredicto, "; ".join(textos) + ".", evidencia)

    def _reglas_derivadas(self, control: Control) -> ResultadoControl:
        if not any(c.tipo == "derivado" for c in self.solicitud.componentes):
            return self._no_aplica(control, "El expediente no declara salidas derivadas por reglas de negocio")
        variante = VARIANTE_ALINEADA if self.hechos.tiene_alineada else VARIANTE_ACTIVA
        resultados = [self._comparar(control, s, "regla_derivada") for s in self.hechos.series_de("derivado", variante)]
        veredicto = self._veredicto_de(resultados)
        limitaciones = [l for r in resultados for l in r.limitaciones]
        if variante == VARIANTE_ACTIVA:
            salidas = [self._comparar(control, s) for s in self.hechos.series_de("salida", VARIANTE_ACTIVA)]
            if veredicto is VeredictoControl.NO_CUMPLE and any(r.veredicto is not VeredictoComponente.COINCIDE for r in salidas):
                return self._resultado(
                    control, VeredictoControl.NO_CONCLUYENTE,
                    "La salida derivada diverge, pero también la salida principal y no hay variante con parámetros alineados: "
                    "no se puede atribuir la divergencia a la regla de negocio.",
                    self._evidencias(resultados), [r.componente_id for r in resultados], limitaciones,
                )
        partes = [
            f"{r.componente_id} (variante {variante}): {r.coincidencias}/{r.comparados} coinciden; "
            f"tramos que coinciden: {_tramos(r.detalle.get('tramos_coincidentes', []))}; "
            f"tramos que divergen: {_tramos(r.detalle.get('tramos_divergentes', []))}"
            for r in resultados if r.estado_ejecucion is EstadoEjecucion.COMPLETADA
        ]
        texto = "; ".join(partes) + "." if partes else "No se pudo ejecutar la implementación."
        return self._resultado(control, veredicto, texto, self._evidencias(resultados), [r.componente_id for r in resultados], limitaciones)

    def _fronteras_rango(self, control: Control) -> ResultadoControl:
        h = self.hechos
        if not self.solicitud.implementacion.permitir_ejecucion:
            return self._resultado(control, VeredictoControl.NO_CONCLUYENTE, "El expediente no autoriza ejecutar el código evaluado.", [])
        if h.fronteras is None or not h.fronteras.condiciones:
            return self._no_aplica(control, "La referencia no tiene condiciones de rango sobre las entradas declaradas")
        if h.oraculo.oraculo_valido is False:
            return self._resultado(control, VeredictoControl.NO_CONCLUYENTE,
                                   "El oráculo no reproduce la caché de la referencia: no se puede confiar en los valores frontera.", [])

        tolerancia = self._tolerancia(control)
        por_condicion: dict[tuple[str, str, float], list] = defaultdict(list)
        for caso in h.casos_frontera:
            coincide = None
            if caso.error is None and caso.referencia and caso.implementacion:
                coincide = True
                for componente_id, referencia in caso.referencia.items():
                    comparacion = self.contexto.herramienta("comparar_series")(
                        {"referencia": referencia, "implementacion": caso.implementacion.get(componente_id, []), "tolerancia": tolerancia}
                    )
                    if comparacion.comparados == 0 or comparacion.coincidencias < comparacion.comparados:
                        coincide = False
            por_condicion[(caso.entrada, caso.operador, caso.umbral)].append((caso, coincide))

        celdas = {(c.entrada, c.operador, c.umbral): c.celda for c in h.fronteras.condiciones}
        divergentes, inconclusas, evidencia, textos, componentes = [], [], [], [], []
        for (entrada, operador, umbral), casos in por_condicion.items():
            etiqueta = f"{entrada} {operador} {_fmt(umbral)}"
            estados = [c for _, c in casos]
            difieren = [_fmt(caso.valor) for caso, c in casos if c is False]
            coinciden = [_fmt(caso.valor) for caso, c in casos if c is True]
            if None in estados:
                veredicto_c = VeredictoComponente.NO_CONCLUYENTE
                inconclusas.append(etiqueta)
            elif all(c is False for c in estados):
                # Si diverge en todos los puntos, la causa no es la frontera sino el punto base.
                veredicto_c = VeredictoComponente.NO_CONCLUYENTE
                inconclusas.append(etiqueta)
                textos.append(f"{etiqueta}: diverge en todos los puntos (divergencia de base, no de frontera)")
            elif difieren:
                veredicto_c = VeredictoComponente.PARCIAL
                divergentes.append(etiqueta)
                textos.append(f"{etiqueta}: diverge en {entrada}={', '.join(difieren)}; coincide en {', '.join(coinciden)}")
            else:
                veredicto_c = VeredictoComponente.COINCIDE
                textos.append(f"{etiqueta}: coincide en {', '.join(coinciden)}")
            componente_id = f"frontera:{etiqueta}"
            componentes.append(componente_id)
            evidencia.append(self._evidencia_celda(celdas[(entrada, operador, umbral)], f"Condición {etiqueta} en la referencia"))
            self.resultados_componentes.append(
                ResultadoComponente(
                    componente_id=componente_id, control_id=control.id, estrategia="fronteras", variante=h.variante_fronteras,
                    estado_ejecucion=EstadoEjecucion.COMPLETADA if None not in estados else EstadoEjecucion.ERROR,
                    veredicto=veredicto_c, comparados=sum(1 for c in estados if c is not None),
                    coincidencias=sum(1 for c in estados if c is True), tolerancia=tolerancia,
                    detalle={"valores_divergentes": difieren, "valores_coincidentes": coinciden},
                    limitaciones=[caso.error for caso, _ in casos if caso.error],
                )
            )
        evidencia.append(Evidencia(tipo=TipoEvidencia.HECHO, fuente="generar_casos_frontera", ubicacion=f"variante {h.variante_fronteras}",
                                   descripcion=f"{len(h.casos_frontera)} casos frontera evaluados en oráculo e implementación"))
        if divergentes:
            veredicto = VeredictoControl.NO_CUMPLE
        elif inconclusas:
            veredicto = VeredictoControl.NO_CONCLUYENTE
        else:
            veredicto = VeredictoControl.CUMPLE
        texto = "; ".join(textos) + f". Casos ejecutados con la variante {h.variante_fronteras}."
        return self._resultado(control, veredicto, texto, evidencia, componentes)

    def _buenas_practicas_codigo(self, control: Control) -> ResultadoControl:
        juez = self.contexto.juez
        if juez is None:
            return self._resultado(control, VeredictoControl.NO_CONCLUYENTE,
                                   "No hay juez configurado para controles de juicio; requiere revisión humana.", [])
        catalogo = self.contexto.catalogo
        try:
            practicas = self.contexto.herramienta("consultar_conocimiento")(
                {"consulta": catalogo.criterio(control, "consulta", control.nombre), "k": 5}
            ).practicas
        except ErrorHerramienta as error:
            return self._resultado(control, VeredictoControl.NO_CONCLUYENTE, "El grafo de conocimiento no está disponible.", [],
                                   limitaciones=[str(error)])
        if not practicas:
            return self._resultado(control, VeredictoControl.NO_CONCLUYENTE, "No se recuperaron prácticas aplicables del grafo.", [])

        fragmentos = self._fragmentos_codigo()
        solicitud = SolicitudJuicio(
            control_id=control.id,
            enunciado_ears=control.enunciado_ears,
            evidencia_requerida=control.evidencia_requerida,
            rubrica=str(catalogo.criterio(control, "rubrica", "")),
            codigo=fragmentos,
            practicas=[PracticaContexto(nota=p.nota, seccion=p.seccion, cita=p.cita) for p in practicas],
        )
        self.hechos.llamadas_juez += 1
        try:
            veredicto_juez = juez.juzgar(solicitud)
        except Exception as error:  # noqa: BLE001 - un fallo del LLM escala; nunca tumba la dimensión
            return self._resultado(control, VeredictoControl.NO_CONCLUYENTE, "El juez no pudo emitir un veredicto.", [],
                                   limitaciones=[f"{type(error).__name__}: {error}"])
        evidencia = [
            Evidencia(tipo=TipoEvidencia.LINEA_CODIGO, fuente=f"{self.raiz}/{c.ruta}", ubicacion=str(c.linea), cita=c.cita,
                      descripcion="Citada por el juez")
            for c in veredicto_juez.citas_codigo
        ] + [
            Evidencia(tipo=TipoEvidencia.NOTA_CONOCIMIENTO, fuente=c.nota, ubicacion="nota", cita=c.cita, descripcion="Práctica citada por el juez")
            for c in veredicto_juez.citas_practicas
        ]
        veredicto = VeredictoControl(veredicto_juez.veredicto)
        limitaciones = [f"Veredicto de juicio emitido por {getattr(juez, 'nombre', 'juez')}"]
        if veredicto is VeredictoControl.CUMPLE and not evidencia:
            veredicto = VeredictoControl.NO_CONCLUYENTE
            limitaciones.append("El juez concluyó 'cumple' sin citar evidencia")
        return self._resultado(control, veredicto, veredicto_juez.justificacion, evidencia, limitaciones=limitaciones)

    def _fragmentos_codigo(self) -> list[FragmentoCodigo]:
        maximo = int(self.contexto.configuracion.parametros.get("max_lineas_codigo_juez", 150))
        rutas: list[str] = []
        for componente in self.solicitud.componentes:
            funcion = self._funciones.get(componente.implementacion.funcion)
            if funcion and funcion.ruta not in rutas:
                rutas.append(funcion.ruta)
        for referencia in self.hechos.indice.referencias:
            if referencia.ruta not in rutas:
                rutas.append(referencia.ruta)
        fragmentos = []
        raiz = self.contexto.ruta(self.solicitud.implementacion.raiz)
        for ruta in rutas[:4]:
            lineas = (raiz / ruta).read_text(encoding="utf-8", errors="replace").splitlines()[:maximo]
            fragmentos.append(FragmentoCodigo(ruta=ruta, linea_inicio=1, texto="\n".join(lineas)))
        return fragmentos
