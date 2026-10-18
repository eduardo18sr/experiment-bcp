"""Rutas HTTP de la plataforma MRM.

Se montan en la app de Databricks junto al agente con `registrar_rutas(app)`. La API devuelve el detalle
completo (con valores) porque la consume el validador humano; el agente conversacional usa `resumen_para_llm`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from mrm.chasis.almacen import ErrorAlmacen
from mrm.chasis.plataforma import obtener_plataforma

router = APIRouter()
PAGINA = Path(__file__).with_name("static") / "index.html"


def registrar_rutas(app: FastAPI) -> None:
    """Agrega cada ruta directamente a la app, en lugar de `app.include_router(router)`.

    El proxy del chat de MLflow (AgentServer con enable_chat_proxy) solo deja pasar las rutas que encuentra
    en `app.routes` con su `path_regex`, y responde "Not found" a todo lo demás. Desde FastAPI 0.14x,
    `include_router` registra un único objeto interno sin `path_regex`, así que el proxy no ve las rutas.
    """
    for ruta in router.routes:
        app.router.routes.append(ruta)


class SolicitudValidar(BaseModel):
    expediente_id: str


def _solicitante(request: Request) -> str:
    """Databricks Apps reenvía la identidad del usuario en cabeceras; se registra para auditoría."""
    return (
        request.headers.get("x-forwarded-email")
        or request.headers.get("x-forwarded-preferred-username")
        or "anonimo"
    )


@router.get("/validador", response_class=HTMLResponse, include_in_schema=False)
def pagina_validador() -> str:
    return PAGINA.read_text(encoding="utf-8")


@router.get("/mrm/api/expedientes")
def listar_expedientes() -> list[dict]:
    return obtener_plataforma().listar_expedientes()


@router.post("/mrm/api/validaciones")
def validar(solicitud: SolicitudValidar, request: Request) -> dict:
    try:
        expediente, _ = obtener_plataforma().validar(solicitud.expediente_id, _solicitante(request))
    except ErrorAlmacen as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return expediente.model_dump(mode="json")


@router.get("/mrm/api/validaciones")
def listar_validaciones() -> list[dict]:
    return obtener_plataforma().listar_validaciones()


@router.get("/mrm/api/validaciones/{id_validacion}")
def obtener_validacion(id_validacion: str) -> dict:
    try:
        expediente = obtener_plataforma().obtener_validacion(id_validacion)
    except ErrorAlmacen as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if expediente is None:
        raise HTTPException(status_code=404, detail="Validación no encontrada")
    return expediente.model_dump(mode="json")


@router.get("/mrm/api/validaciones/{id_validacion}/informe", response_class=PlainTextResponse)
def informe(id_validacion: str) -> str:
    try:
        texto = obtener_plataforma().informe(id_validacion)
    except ErrorAlmacen as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if texto is None:
        raise HTTPException(status_code=404, detail="Informe no encontrado")
    return texto


@router.get("/mrm/api/capacidades")
def capacidades() -> dict:
    return obtener_plataforma().capacidades()


@router.get("/mrm/api/conocimiento")
def conocimiento(q: str, k: int = 5) -> list[dict]:
    return obtener_plataforma().buscar_conocimiento(q, max(1, min(k, 20)))
