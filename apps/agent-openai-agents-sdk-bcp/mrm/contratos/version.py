"""Versionado semántico con la regla de compatibilidad del framework (Anexo C.2).

- Un cambio aditivo sube la versión menor y no rompe a quien depende.
- Un cambio que rompe el contrato sube la mayor: quien dependía de la anterior migra de forma explícita.
"""

from __future__ import annotations

import re

_PATRON = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parsear(version: str) -> tuple[int, int, int]:
    coincidencia = _PATRON.match(version.strip())
    if not coincidencia:
        raise ValueError(f"Versión semántica inválida: {version!r} (se espera MAYOR.MENOR.PARCHE)")
    return tuple(int(parte) for parte in coincidencia.groups())  # type: ignore[return-value]


def es_compatible(disponible: str, minima: str) -> bool:
    """True si `disponible` satisface `>= minima` sin cruzar una versión mayor."""
    mayor_d, menor_d, parche_d = parsear(disponible)
    mayor_m, menor_m, parche_m = parsear(minima)
    return mayor_d == mayor_m and (menor_d, parche_d) >= (menor_m, parche_m)
