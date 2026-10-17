import textwrap

import pytest

from mrm.contratos.herramienta import ErrorHerramienta
from mrm.contratos.repositorio import EstadoReferencia
from mrm.herramientas.indexar_repositorio.herramienta import IndexarRepositorio


def test_caso_a_activo_y_comentado(casos):
    salida = IndexarRepositorio()({"raiz": str(casos / "CASO_A_PD_CURVA" / "implementacion")})
    por_objetivo = {(r.objetivo, r.estado) for r in salida.referencias}
    assert ("theta_Tt_VERSION_ACTIVA.csv", EstadoReferencia.ACTIVO) in por_objetivo
    assert ("theta_Tt_VERSION_EXCEL.csv", EstadoReferencia.COMENTADO) in por_objetivo
    assert ("theta_Tt_VERSION_EXCEL.csv", EstadoReferencia.ACTIVO) not in por_objetivo
    funciones = {f"{f.modulo}:{f.nombre}" for f in salida.funciones}
    assert "motor.curva:calcular_pd_temporal" in funciones
    assert "params/theta_Tt_VERSION_EXCEL.csv" in salida.archivos_datos


def test_rutas_dinamicas_y_docstrings(tmp_path):
    (tmp_path / "paquete").mkdir()
    (tmp_path / "paquete" / "carga.py").write_text(textwrap.dedent('''
        """Carga parametros desde parametros_viejos.csv (esto es un docstring)."""
        VERSION = "202605"
        RUTA = f"datos/theta_{VERSION}.csv"
        OTRA = "tarifa_" + VERSION + ".csv"


        class Motor:
            def cargar(self, ruta):
                return open("fijo.json")
    '''))
    salida = IndexarRepositorio()({"raiz": str(tmp_path)})
    referencias = {(r.objetivo, r.estado) for r in salida.referencias}
    assert ("theta_*.csv", EstadoReferencia.DINAMICO) in referencias
    assert ("tarifa_*.csv", EstadoReferencia.DINAMICO) in referencias
    assert ("fijo.json", EstadoReferencia.ACTIVO) in referencias
    assert not any(r.objetivo == "parametros_viejos.csv" for r in salida.referencias)
    metodo = next(f for f in salida.funciones if f.nombre == "cargar")
    assert metodo.clase == "Motor" and metodo.argumentos == ["self", "ruta"]
    assert any(c.nombre == "VERSION" for c in salida.constantes)


def test_raiz_inexistente(tmp_path):
    with pytest.raises(ErrorHerramienta) as error:
        IndexarRepositorio()({"raiz": str(tmp_path / "no")})
    assert error.value.codigo == "raiz_no_encontrada"
