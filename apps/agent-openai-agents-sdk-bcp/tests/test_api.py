"""API REST y página /validador sobre la plataforma local (sin Databricks).

La app de prueba lleva el mismo filtro que el proxy del chat de MLflow (AgentServer con enable_chat_proxy):
solo pasan las rutas que aparecen en `app.routes` con `path_regex`; el resto recibe "Not found".
"""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import Response  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _app_como_agent_server() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def proxy_del_chat(request: Request, call_next):
        for ruta in app.routes:
            if hasattr(ruta, "path_regex") and ruta.path_regex.match(request.url.path):
                return await call_next(request)
        return Response("Not found", status_code=404, media_type="text/plain")

    return app


@pytest.fixture
def cliente(crear_plataforma, monkeypatch):
    from mrm.api import rutas

    plataforma = crear_plataforma()
    monkeypatch.setattr(rutas, "obtener_plataforma", lambda: plataforma)
    app = _app_como_agent_server()
    rutas.registrar_rutas(app)
    return TestClient(app)


def test_el_proxy_del_chat_ve_todas_las_rutas_mrm():
    from mrm.api import rutas

    app = _app_como_agent_server()
    rutas.registrar_rutas(app)
    for ruta in rutas.router.routes:
        ejemplo = ruta.path.replace("{id_validacion}", "X")
        assert any(hasattr(r, "path_regex") and r.path_regex.match(ejemplo) for r in app.routes), ruta.path


def test_flujo_validar_desde_la_pagina(cliente):
    assert "Validador de implementación" in cliente.get("/validador").text
    expedientes = cliente.get("/mrm/api/expedientes").json()
    assert {e["id"] for e in expedientes} == {"CASO_A_PD_CURVA", "CASO_B_PRICING", "CASO_C_SCORING"}

    respuesta = cliente.post("/mrm/api/validaciones", json={"expediente_id": "CASO_B_PRICING"},
                             headers={"x-forwarded-email": "validador@example.com"})
    assert respuesta.status_code == 200
    validacion = respuesta.json()
    assert validacion["solicitante"] == "validador@example.com"
    assert validacion["veredicto_integral"] == "no_cumple"

    identificador = validacion["id_validacion"]
    assert cliente.get(f"/mrm/api/validaciones/{identificador}").json()["expediente_id"] == "CASO_B_PRICING"
    assert "IMP-PRC-003" in cliente.get(f"/mrm/api/validaciones/{identificador}/informe").text
    assert cliente.get("/mrm/api/validaciones").json()[0]["id_validacion"] == identificador


def test_errores_y_capacidades(cliente):
    assert cliente.post("/mrm/api/validaciones", json={"expediente_id": "NO_EXISTE"}).status_code == 404
    assert cliente.post("/mrm/api/validaciones", json={"expediente_id": "../fuera"}).status_code == 404
    assert cliente.get("/mrm/api/validaciones/no-existe").status_code == 404
    capacidades = cliente.get("/mrm/api/capacidades").json()
    assert {s["nombre"] for s in capacidades["skills"]} == {"validar-implementacion-calculo", "revisar-documentacion"}
    assert len(capacidades["herramientas"]) == 9
    practicas = cliente.get("/mrm/api/conocimiento", params={"q": "versión de parámetros en el código"}).json()
    assert practicas and practicas[0]["cita"]
