"""Job de Databricks: corre el arnés de evaluación y registra las métricas en MLflow.

Se corre en cada cambio de catálogo, skill, herramienta o modelo base (rutas A, D, S y B), sobre la suite
completa. Si algún umbral no se cumple, el job termina con error: así queda visible en el historial.

Parámetros (todos opcionales): los mismos de `python -m evals.harness`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.harness import main  # noqa: E402

if __name__ == "__main__":
    argumentos = sys.argv[1:]
    if "--mlflow" not in argumentos:
        argumentos.append("--mlflow")
    sys.exit(main(argumentos))
