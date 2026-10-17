"""Generador del informe de validación: resumen ejecutivo para no técnicos y detalle técnico separado."""

from __future__ import annotations

from mrm.chasis.expediente import ExpedienteAuditable
from mrm.contratos.resultado import Aplicabilidad, VeredictoControl

_ETIQUETA = {
    VeredictoControl.CUMPLE: "✅ Cumple",
    VeredictoControl.NO_CUMPLE: "❌ No cumple",
    VeredictoControl.NO_CONCLUYENTE: "⚠️ No concluyente",
    None: "— No aplica",
}


def _celda(texto: str) -> str:
    return texto.replace("|", "\\|").replace("\n", " ")


def generar_informe(expediente: ExpedienteAuditable) -> str:
    conteos = expediente.conteos()
    lineas = [
        f"# Informe de validación de implementación · {expediente.expediente_id}",
        "",
        f"> {expediente.aviso}",
        "",
        "## Resumen ejecutivo",
        "",
        f"- **Modelo:** {expediente.modelo.nombre} (`{expediente.modelo.id}`), tipo {expediente.modelo.tipo_modelo}, tier {expediente.modelo.tier}",
        f"- **Resultado preliminar:** {_ETIQUETA[expediente.veredicto_integral]}",
        f"- **Controles:** {conteos['cumple']} cumplen, {conteos['no_cumple']} no cumplen, "
        f"{conteos['no_concluyente']} no concluyentes, {conteos['no_aplica']} no aplican, "
        f"{conteos['excluidos_por_tier']} excluidos por tier",
        f"- **Revisión humana:** {'obligatoria' if expediente.requiere_revision_humana else 'no requerida'}"
        + (f" ({'; '.join(expediente.motivos_revision)})" if expediente.motivos_revision else ""),
        f"- **Etapa de autonomía del agente:** {expediente.etapa_autonomia}",
        "",
    ]
    hallazgos = [r for r in expediente.resultados() if r.veredicto is VeredictoControl.NO_CUMPLE]
    if hallazgos:
        lineas += ["### Hallazgos", ""]
        for r in sorted(hallazgos, key=lambda x: ["Alta", "Media", "Baja"].index(x.severidad.value)):
            lineas.append(f"- **{r.control_id} · {r.nombre}** (severidad {r.severidad.value}): {r.justificacion}")
        lineas.append("")
    if expediente.huecos_cobertura:
        lineas += ["### Dimensiones sin cobertura automática (revisión manual completa)", ""]
        lineas += [f"- **{h.dimension}**: {h.motivo}" for h in expediente.huecos_cobertura]
        lineas.append("")

    lineas += ["## Detalle técnico", ""]
    for dimension in expediente.dimensiones:
        resolucion = dimension.resolucion
        lineas += [
            f"### Dimensión: {dimension.dimension}",
            "",
            f"Skill `{resolucion.get('skill')}@{resolucion.get('version_skill')}` · catálogo "
            f"`{resolucion.get('catalogo')}@{resolucion.get('version_catalogo')}`",
            "",
            "| Control | Veredicto | Severidad | Revisión humana | Justificación |",
            "|---|---|---|---|---|",
        ]
        for r in dimension.resultados_control:
            etiqueta = _ETIQUETA[r.veredicto] if r.aplicabilidad is Aplicabilidad.APLICA else _ETIQUETA[None]
            lineas.append(
                f"| {r.control_id} · {_celda(r.nombre)} | {etiqueta} | {r.severidad.value} | "
                f"{'sí' if r.requiere_revision_humana else 'no'} | {_celda(r.justificacion)} |"
            )
        lineas.append("")
        for r in dimension.resultados_control:
            if not r.evidencia and not r.limitaciones:
                continue
            lineas.append(f"**{r.control_id} · evidencia**")
            lineas.append("")
            for e in r.evidencia:
                cita = f" — «{e.cita}»" if e.cita else ""
                lineas.append(f"- [{e.tipo.value}] `{e.fuente}` @ {e.ubicacion}: {e.descripcion}{cita}")
            for limitacion in r.limitaciones:
                lineas.append(f"- *Limitación:* {limitacion}")
            lineas.append("")
        if dimension.controles_excluidos:
            lineas += ["**Controles excluidos por tier**", ""]
            lineas += [f"- {c.control_id}@{c.version}: {c.motivo}" for c in dimension.controles_excluidos]
            lineas.append("")
        if dimension.limitaciones:
            lineas += ["**Limitaciones de la corrida**", ""]
            lineas += [f"- {l}" for l in dimension.limitaciones]
            lineas.append("")

    lineas += [
        "## Trazabilidad",
        "",
        f"- Validación `{expediente.id_validacion}` · {expediente.fecha_utc} · solicitante `{expediente.solicitante}`",
        f"- Agente `{expediente.agente.get('id')}@{expediente.agente.get('version')}` · política de tiering {expediente.politica_tiering}",
        f"- {len(expediente.invocaciones)} invocaciones de herramientas · {expediente.llamadas_llm} llamadas al LLM · {expediente.duracion_s} s",
        "- Huellas SHA-256 de las entradas:",
    ]
    lineas += [f"  - `{ruta}`: `{huella[:16]}…`" for ruta, huella in sorted(expediente.huellas_entradas.items())]
    return "\n".join(lineas) + "\n"
