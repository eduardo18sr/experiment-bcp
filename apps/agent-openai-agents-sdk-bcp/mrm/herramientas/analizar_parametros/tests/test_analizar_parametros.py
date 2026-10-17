from mrm.herramientas.analizar_parametros.herramienta import AnalizarParametros
from mrm.herramientas.indexar_repositorio.herramienta import IndexarRepositorio

TOLERANCIA = {"absoluta": 1e-8, "relativa": 0.0}


def _analizar(libro, raiz, tablas):
    referencias = IndexarRepositorio()({"raiz": str(raiz)}).referencias
    return AnalizarParametros()(
        {"libro": libro, "tablas": tablas, "raiz_proyecto": str(raiz), "referencias": referencias, "tolerancia": TOLERANCIA}
    )


def test_caso_a_uso_por_coincidencia_tabla_ancha_por_filas(casos, libro_caso_a):
    salida = _analizar(libro_caso_a, casos / "CASO_A_PD_CURVA" / "implementacion", [
        {"id": "theta", "hoja": "Calculadora", "rango": "H20:BZ26", "orientacion": "filas", "clave": "periodo", "archivos": "params/*.csv"},
        {"id": "calibracion", "hoja": "Calculadora", "rango": "K8:M11", "orientacion": "columnas", "clave": "plazo_max", "archivos": "params/*.csv"},
    ])
    theta, calibracion = salida.tablas
    archivos = {a.ruta: a for a in theta.archivos}
    assert archivos["params/theta_Tt_VERSION_ACTIVA.csv"].clasificacion == "SE_USA_SIN_COINCIDENCIA"
    assert archivos["params/theta_Tt_VERSION_EXCEL.csv"].clasificacion == "COINCIDE_PERO_NO_SE_USA"
    assert archivos["params/theta_Tt_VERSION_EXCEL.csv"].uso == "COMENTADO"
    assert archivos["params/theta_Tt_VERSION_EXCEL.csv"].comparados == 420
    assert archivos["params/calibracion_plazo.csv"].coincidencia == "NO_COMPARABLE"
    calibrado = {a.ruta: a for a in calibracion.archivos}["params/calibracion_plazo.csv"]
    assert calibrado.clasificacion == "SE_USA_Y_COINCIDE"


def test_caso_b_un_valor_divergente_en_tabla_por_columnas(casos, libro_caso_b):
    salida = _analizar(libro_caso_b, casos / "CASO_B_PRICING" / "implementacion", [
        {"id": "tarifario", "hoja": "Tarifario", "rango": "A1:D5", "orientacion": "columnas", "clave": "segmento", "archivos": "params/*.csv"},
    ])
    archivos = {a.ruta: a for a in salida.tablas[0].archivos}
    vigente = archivos["params/tarifario_2026.csv"]
    assert vigente.clasificacion == "SE_USA_SIN_COINCIDENCIA"
    assert (vigente.comparados, vigente.coincidencias) == (12, 11)
    assert vigente.diferencias[0].clave == "pyme" and vigente.diferencias[0].nombre == "spread"
    assert archivos["params/tarifario_2025.csv"].clasificacion == "NO_SE_USA_NI_COINCIDE"
    assert archivos["params/tarifario_2025.csv"].uso == "NO_REFERENCIADO"
