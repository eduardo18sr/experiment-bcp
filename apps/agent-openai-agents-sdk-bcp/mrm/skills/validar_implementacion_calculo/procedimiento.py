"""Skill `validar-implementacion-calculo`: recoge hechos con las herramientas y los traduce a veredictos.

La skill nunca importa herramientas: las pide al contexto por nombre (`contexto.herramienta(...)`), y el
chasis solo entrega las que la skill declaró en su `skill.yaml`.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from mrm.contratos.expediente import Componente, EntradaCalculo
from mrm.contratos.herramienta import ErrorHerramienta
from mrm.contratos.resultado import EstadoEjecucion
from mrm.contratos.skill import ContextoSkill, ResultadoSkill, Skill
from mrm.herramientas._comun.celdas import lista_rango
from mrm.skills.validar_implementacion_calculo.hechos import (
    VARIANTE_ACTIVA,
    VARIANTE_ALINEADA,
    CasoFronteraEjecutado,
    Hechos,
    Serie,
)
from mrm.skills.validar_implementacion_calculo.reglas import EvaluadorReglas


def _valor_entrada(entrada: EntradaCalculo, valor: Any) -> Any:
    if entrada.tipo == "entero" and valor is not None:
        return int(round(float(valor)))
    if entrada.tipo == "numero" and valor is not None:
        return float(valor)
    return valor


def _extraer_salida(salida: Any, clave: str | None) -> list[Any]:
    valor = salida.get(clave) if (clave and isinstance(salida, dict)) else salida
    return list(valor) if isinstance(valor, (list, tuple)) else [valor]


class ValidarImplementacionCalculo(Skill):
    nombre = "validar-implementacion-calculo"

    def ejecutar(self, contexto: ContextoSkill) -> ResultadoSkill:
        hechos = self._recoger_hechos(contexto)
        evaluador = EvaluadorReglas(contexto, hechos)
        resultados_control = [evaluador.evaluar(control) for control in contexto.controles]
        return ResultadoSkill(
            resultados_control=resultados_control,
            resultados_componentes=evaluador.resultados_componentes,
            limitaciones=hechos.limitaciones,
            hechos=evaluador.resumen_hechos(),
        )

    # --------------------------------------------------------------------------------------------------
    def _recoger_hechos(self, contexto: ContextoSkill) -> Hechos:
        solicitud = contexto.solicitud
        reglas = {control.regla for control in contexto.controles}

        libro = contexto.herramienta("extraer_excel")({"ruta": str(contexto.ruta(solicitud.referencia.excel))}).libro
        objetivos = list(dict.fromkeys(c.referencia.completa() for c in solicitud.componentes))
        oraculo = contexto.herramienta("evaluar_formulas")({"libro": libro, "objetivos": objetivos, "escenarios": [{}]})
        raiz = contexto.ruta(solicitud.implementacion.raiz)
        indice = contexto.herramienta("indexar_repositorio")({"raiz": str(raiz)})
        hechos = Hechos(solicitud=solicitud, libro=libro, oraculo=oraculo, indice=indice)
        hechos.limitaciones.extend(libro.advertencias)

        if oraculo.oraculo_valido is None:
            hechos.limitaciones.append("La referencia no tiene valores en caché: los valores esperados los calcula el oráculo")
        elif not oraculo.oraculo_valido:
            hechos.limitaciones.append(
                f"El oráculo no reproduce la caché del libro ({len(oraculo.discrepancias_cache)} discrepancias, "
                f"{len(oraculo.errores_oraculo)} errores): los casos frontera no son concluyentes"
            )

        if solicitud.tablas_parametros:
            hechos.parametros = self._analizar_parametros(contexto, hechos, raiz)

        self._ejecutar_variantes(contexto, hechos, raiz)
        if "fronteras_rango" in reglas and solicitud.implementacion.permitir_ejecucion:
            self._ejecutar_fronteras(contexto, hechos, raiz)
        return hechos

    def _analizar_parametros(self, contexto: ContextoSkill, hechos: Hechos, raiz) -> Any:
        control = next((c for c in contexto.controles if c.regla == "precision_parametros"), None)
        catalogo = contexto.catalogo
        tolerancia = {
            "absoluta": catalogo.criterio(control, "tolerancia_absoluta", 1e-8) if control else catalogo.criterios_comunes.get("tolerancia_absoluta", 1e-8),
            "relativa": catalogo.criterio(control, "tolerancia_relativa", 0.0) if control else catalogo.criterios_comunes.get("tolerancia_relativa", 0.0),
        }
        tablas = [
            {
                "id": t.id,
                "hoja": t.referencia.hoja,
                "rango": t.referencia.rango,
                "orientacion": t.orientacion,
                "clave": t.clave,
                "archivos": t.archivos,
                "clave_archivo": t.clave_archivo,
            }
            for t in hechos.solicitud.tablas_parametros
        ]
        return contexto.herramienta("analizar_parametros")(
            {
                "libro": hechos.libro,
                "tablas": tablas,
                "raiz_proyecto": str(raiz),
                "referencias": hechos.indice.referencias,
                "tolerancia": tolerancia,
            }
        )

    # --------------------------------------------------------------------------------------------------
    def _valores_referencia(self, hechos: Hechos, componente: Componente) -> tuple[list[Any], list[Any] | None]:
        refs = lista_rango(componente.referencia.hoja, componente.referencia.rango)
        if hechos.libro.tiene_cache:
            valores = [hechos.libro.celdas[r].valor if r in hechos.libro.celdas else None for r in refs]
        else:
            valores = hechos.oraculo.resultados[0].valores.get(componente.referencia.completa(), [])
        etiquetas = None
        if componente.referencia.etiquetas:
            refs_etiquetas = lista_rango(componente.referencia.hoja, componente.referencia.etiquetas)
            etiquetas = [hechos.libro.celdas[r].valor if r in hechos.libro.celdas else None for r in refs_etiquetas]
            if len(etiquetas) != len(valores):
                hechos.limitaciones.append(f"{componente.id}: las etiquetas no tienen la misma longitud que el rango")
                etiquetas = None
        return valores, etiquetas

    def _argumentos_base(self, hechos: Hechos) -> dict[str, Any]:
        return {
            entrada.nombre_argumento: _valor_entrada(entrada, hechos.libro.celdas[entrada.ref].valor if entrada.ref in hechos.libro.celdas else None)
            for entrada in hechos.solicitud.entradas
        }

    def _sustituciones_alineadas(self, hechos: Hechos) -> list[dict[str, Any]]:
        """Si un archivo cargado no coincide y otro del proyecto sí, se prueba la copia con el que coincide."""
        sustituciones = []
        for tabla in (hechos.parametros.tablas if hechos.parametros else []):
            activos_sin = [a for a in tabla.archivos if a.uso == "ACTIVO" and a.coincidencia == "NO_COINCIDE"]
            alternativos = [a for a in tabla.archivos if a.uso != "ACTIVO" and a.coincidencia == "COINCIDE"]
            if not activos_sin or not alternativos:
                continue
            reemplazo = alternativos[0].ruta.rsplit("/", 1)[-1]
            for activo in activos_sin:
                nombre = activo.ruta.rsplit("/", 1)[-1]
                for referencia in activo.referencias:
                    if referencia.estado.value == "ACTIVO":
                        sustituciones.append(
                            {"archivo": referencia.ruta, "linea": referencia.linea, "buscar": nombre, "reemplazar": reemplazo}
                        )
        return sustituciones

    def _ejecutar_variantes(self, contexto: ContextoSkill, hechos: Hechos, raiz) -> None:
        solicitud = hechos.solicitud
        variantes: dict[str, list[dict[str, Any]]] = {VARIANTE_ACTIVA: []}
        sustituciones = self._sustituciones_alineadas(hechos)
        if sustituciones:
            variantes[VARIANTE_ALINEADA] = sustituciones
        hechos.variantes = list(variantes)

        por_funcion: dict[str, list[Componente]] = defaultdict(list)
        for componente in solicitud.componentes:
            por_funcion[componente.implementacion.funcion].append(componente)
        argumentos = self._argumentos_base(hechos)
        timeout = float(contexto.configuracion.parametros.get("timeout_ejecucion_s", 120))

        for variante, sustituciones_variante in variantes.items():
            for funcion, componentes in por_funcion.items():
                referencias = {c.id: self._valores_referencia(hechos, c) for c in componentes}
                if not solicitud.implementacion.permitir_ejecucion:
                    for c in componentes:
                        hechos.series[(c.id, variante)] = Serie(
                            c, variante, *referencias[c.id], estado=EstadoEjecucion.NO_EJECUTADA,
                            error="El expediente no autoriza ejecutar el código evaluado",
                        )
                    continue
                try:
                    salida = contexto.herramienta("ejecutar_funcion")(
                        {
                            "raiz_proyecto": str(raiz),
                            "funcion": funcion,
                            "casos": [argumentos],
                            "sustituciones": sustituciones_variante,
                            "autorizado": True,
                            "variante": variante,
                            "timeout_s": timeout,
                        }
                    )
                except ErrorHerramienta as error:
                    for c in componentes:
                        hechos.series[(c.id, variante)] = Serie(
                            c, variante, *referencias[c.id], estado=EstadoEjecucion.ERROR, error=str(error)
                        )
                    continue
                hechos.ejecuciones.setdefault(variante, []).append(salida)
                caso = salida.resultados[0]
                for c in componentes:
                    if caso.ok:
                        hechos.series[(c.id, variante)] = Serie(
                            c, variante, *referencias[c.id], estado=EstadoEjecucion.COMPLETADA,
                            implementacion=_extraer_salida(caso.salida, c.implementacion.salida),
                        )
                    else:
                        hechos.series[(c.id, variante)] = Serie(
                            c, variante, *referencias[c.id], estado=EstadoEjecucion.ERROR, error=caso.error
                        )

    def _ejecutar_fronteras(self, contexto: ContextoSkill, hechos: Hechos, raiz) -> None:
        solicitud = hechos.solicitud
        salidas = [c for c in solicitud.componentes if c.tipo == "salida"]
        control = next(c for c in contexto.controles if c.regla == "fronteras_rango")
        max_casos = int(contexto.catalogo.criterio(control, "max_casos", 40))
        objetivos = list(dict.fromkeys(c.referencia.completa() for c in salidas))
        hechos.fronteras = contexto.herramienta("generar_casos_frontera")(
            {
                "libro": hechos.libro,
                "objetivos": objetivos,
                "entradas": [{"nombre": e.nombre, "ref": e.ref, "tipo": e.tipo, "paso": e.paso} for e in solicitud.entradas],
                "max_casos": max_casos,
            }
        )
        if hechos.fronteras.truncado:
            hechos.limitaciones.append(f"Se truncaron los casos frontera a {max_casos}")
        if not hechos.fronteras.casos:
            return

        evaluacion = contexto.herramienta("evaluar_formulas")(
            {
                "libro": hechos.libro,
                "objetivos": objetivos,
                "escenarios": [caso.sobrescrituras for caso in hechos.fronteras.casos],
                "validar_cache": False,
            }
        )
        # Con parámetros alineados, la frontera aísla la lógica de rangos de la versión de parámetros.
        variante = VARIANTE_ALINEADA if hechos.tiene_alineada else VARIANTE_ACTIVA
        hechos.variante_fronteras = variante
        sustituciones = self._sustituciones_alineadas(hechos) if variante == VARIANTE_ALINEADA else []
        por_nombre = {e.nombre: e for e in solicitud.entradas}
        base = self._argumentos_base(hechos)
        casos_argumentos = []
        for caso in hechos.fronteras.casos:
            entrada = por_nombre[caso.entrada]
            casos_argumentos.append({**base, entrada.nombre_argumento: _valor_entrada(entrada, caso.valor)})

        ejecutados = [
            CasoFronteraEjecutado(entrada=c.entrada, operador=c.operador, umbral=c.umbral, valor=c.valor, posicion=c.posicion)
            for c in hechos.fronteras.casos
        ]
        for indice, resultado in enumerate(evaluacion.resultados):
            if resultado.error:
                ejecutados[indice].error = f"Oráculo: {resultado.error}"
                continue
            for componente in salidas:
                ejecutados[indice].referencia[componente.id] = resultado.valores[componente.referencia.completa()]

        por_funcion: dict[str, list[Componente]] = defaultdict(list)
        for componente in salidas:
            por_funcion[componente.implementacion.funcion].append(componente)
        for funcion, componentes in por_funcion.items():
            try:
                salida = contexto.herramienta("ejecutar_funcion")(
                    {
                        "raiz_proyecto": str(raiz),
                        "funcion": funcion,
                        "casos": casos_argumentos,
                        "sustituciones": sustituciones,
                        "autorizado": True,
                        "variante": f"{variante}-fronteras",
                        "timeout_s": float(contexto.configuracion.parametros.get("timeout_ejecucion_s", 120)),
                    }
                )
            except ErrorHerramienta as error:
                for caso in ejecutados:
                    caso.error = caso.error or f"Implementación: {error}"
                continue
            for caso_resultado in salida.resultados:
                caso = ejecutados[caso_resultado.indice]
                if not caso_resultado.ok:
                    caso.error = caso.error or f"Implementación: {caso_resultado.error}"
                    continue
                for componente in componentes:
                    caso.implementacion[componente.id] = _extraer_salida(caso_resultado.salida, componente.implementacion.salida)
        hechos.casos_frontera = ejecutados
