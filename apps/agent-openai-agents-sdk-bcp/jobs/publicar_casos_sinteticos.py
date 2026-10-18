"""Job de Databricks: publica los expedientes sintéticos en un Volume para probar la app sin datos reales.

Parámetros:
  --destino  /Volumes/<catalogo>/<esquema>/<volumen>/expedientes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.sintetico.generador import generar_casos  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--destino", required=True)
    argumentos = parser.parse_args()
    for caso, carpeta in generar_casos(Path(argumentos.destino)).items():
        print(f"{caso}: {carpeta}")
