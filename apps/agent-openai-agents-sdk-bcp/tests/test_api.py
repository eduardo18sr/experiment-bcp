"""API REST y página /validador sobre la plataforma local (sin Databricks)."""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def cliente(crear_plataforma, monkeypatch):
    from mrm.api import rutas

    plataforma = crear_plataforma()
    monkeypatch.setattr(rutas, "obtener_plataforma", lambda: plataforma)
    app = FastAPI()
    app.include_router(rutas.router)
    return TestClient(app)


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
