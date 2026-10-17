"""Puntos obligatorios de human-in-the-loop. Se definen por severidad, tier y etapa, no caso por caso."""

from __future__ import annotations

from mrm.chasis.politica import PoliticaHITL
from mrm.contratos.control import TipoControl
from mrm.contratos.resultado import Aplicabilidad, ResultadoControl, VeredictoControl


def marcar_escalamiento(resultado: ResultadoControl, tier: int, etapa: str, politica: PoliticaHITL) -> ResultadoControl:
    if resultado.aplicabilidad is Aplicabilidad.NO_APLICA:
        return resultado
    motivos = []
    if resultado.veredicto is VeredictoControl.NO_CUMPLE and resultado.severidad.value in politica.severidades_que_escalan:
        motivos.append(f"Hallazgo de severidad {resultado.severidad.value}")
    if resultado.veredicto is VeredictoControl.NO_CONCLUYENTE and politica.no_concluyente_escala:
        motivos.append("Resultado no concluyente: escala obligatoriamente")
    if tier in politica.tiers_con_revision_completa:
        motivos.append(f"Modelo tier {tier}: revisión humana completa")
    if resultado.tipo is TipoControl.JUICIO and etapa in politica.juicio_escala_en_etapa:
        motivos.append(f"Control de juicio en etapa {etapa}")
    return resultado.model_copy(update={"requiere_revision_humana": bool(motivos), "motivos_escalamiento": motivos})
