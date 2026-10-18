"""Política de tiering y de human-in-the-loop (constitución del área) y selector de tier."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from mrm.chasis.registro import RAIZ_MRM
from mrm.contratos.control import CatalogoControles, Control


class PoliticaHITL(BaseModel):
    severidades_que_escalan: list[str] = Field(default_factory=lambda: ["Alta"])
    tiers_con_revision_completa: list[int] = Field(default_factory=lambda: [1])
    no_concluyente_escala: bool = True
    juicio_escala_en_etapa: list[str] = Field(default_factory=lambda: ["sombra", "copiloto"])


class PoliticaTiering(BaseModel):
    version: str
    estado: str
    dimensiones_obligatorias: dict[int, list[str]]
    hitl: PoliticaHITL = Field(default_factory=PoliticaHITL)

    @classmethod
    def cargar(cls, ruta: Path = RAIZ_MRM / "constitucion" / "politica_tiering.yaml") -> "PoliticaTiering":
        with open(ruta, encoding="utf-8") as archivo:
            return cls.model_validate(yaml.safe_load(archivo))

    def dimensiones_para(self, tier: int) -> list[str]:
        return list(self.dimensiones_obligatorias.get(tier, []))


class ControlExcluido(BaseModel):
    control_id: str
    version: str
    motivo: str


def filtrar_por_tier(catalogo: CatalogoControles, tier: int, politica: PoliticaTiering) -> tuple[list[Control], list[ControlExcluido]]:
    """El filtro es código, no prompt: un control aplica si tier <= tier_minimo (Anexo B.4)."""
    aplicables, excluidos = [], []
    for control in catalogo.controles:
        if control.aplica_a_tier(tier):
            aplicables.append(control)
        else:
            excluidos.append(
                ControlExcluido(
                    control_id=control.id,
                    version=control.version,
                    motivo=f"Tier del modelo {tier} > tier mínimo del control {control.tier_minimo} (política de tiering {politica.version})",
                )
            )
    return aplicables, excluidos
