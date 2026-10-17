"""Proceso hijo que ejecuta la función productiva. Solo usa la biblioteca estándar.

Uso: python -I runner.py <raiz_copia> <entrada.json> <salida.json>
La salida estándar de la función se redirige a stderr para no mezclarla con el resultado.
"""

import contextlib
import importlib
import json
import math
import sys


def convertir(valor):
    if hasattr(valor, "tolist"):
        valor = valor.tolist()
    elif hasattr(valor, "item") and not isinstance(valor, (list, dict, str)):
        try:
            valor = valor.item()
        except (TypeError, ValueError):
            pass
    if isinstance(valor, dict):
        return {str(k): convertir(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [convertir(v) for v in valor]
    if isinstance(valor, float) and (math.isnan(valor) or math.isinf(valor)):
        return None
    if isinstance(valor, (str, int, float, bool)) or valor is None:
        return valor
    return repr(valor)


def main():
    raiz, ruta_entrada, ruta_salida = sys.argv[1:4]
    sys.path.insert(0, raiz)
    with open(ruta_entrada, encoding="utf-8") as archivo:
        solicitud = json.load(archivo)
    modulo, nombre = solicitud["funcion"].split(":")
    resultados = []
    try:
        with contextlib.redirect_stdout(sys.stderr):
            funcion = getattr(importlib.import_module(modulo), nombre)
    except Exception as error:  # noqa: BLE001 - se informa al proceso padre
        mensaje = f"{type(error).__name__}: {error}"
        resultados = [{"indice": i, "ok": False, "error": mensaje} for i in range(len(solicitud["casos"]))]
        funcion = None
    if funcion is not None:
        for indice, argumentos in enumerate(solicitud["casos"]):
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    salida = funcion(**argumentos)
                resultados.append({"indice": indice, "ok": True, "salida": convertir(salida)})
            except Exception as error:  # noqa: BLE001
                resultados.append({"indice": indice, "ok": False, "error": f"{type(error).__name__}: {error}"})
    with open(ruta_salida, "w", encoding="utf-8") as archivo:
        json.dump({"resultados": resultados}, archivo)


if __name__ == "__main__":
    main()
