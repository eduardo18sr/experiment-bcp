"""Trazas con MLflow cuando está disponible (en la app y en los jobs); no-op en local sin MLflow."""

from __future__ import annotations

import contextlib
from typing import Any, Iterator


@contextlib.contextmanager
def span(nombre: str, atributos: dict[str, Any] | None = None) -> Iterator[None]:
    try:
        import mlflow
    except ImportError:
        yield
        return
    try:
        contexto = mlflow.start_span(name=nombre, attributes=atributos or {})
    except Exception:  # noqa: BLE001 - la observabilidad nunca debe romper una validación
        yield
        return
    with contexto:
        yield
