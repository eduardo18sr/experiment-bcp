"""Modelo del grafo de conocimiento: nodos (notas), aristas tipadas y fragmentos (secciones)."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

# Peso de cada tipo de arista al propagar relevancia desde una semilla.
PESOS_ARISTA = {
    "relacionado": 0.5,
    "pertenece_a_mapa": 0.3,
    "contiene": 0.2,
    "menciona": 0.25,
}


class Nodo(BaseModel):
    id: str = Field(description="Título de la nota (nombre del archivo sin extensión)")
    tipo: str = "nota"
    dominios: list[str] = Field(default_factory=list)
    temas: list[str] = Field(default_factory=list)
    ruta: str = ""


class Arista(BaseModel):
    origen: str
    destino: str
    tipo: str


class Fragmento(BaseModel):
    id: str
    nodo: str
    seccion: str
    texto: str


class Grafo(BaseModel):
    version: str = "1"
    nodos: dict[str, Nodo] = Field(default_factory=dict)
    aristas: list[Arista] = Field(default_factory=list)
    fragmentos: list[Fragmento] = Field(default_factory=list)

    def vecinos(self, nodo: str) -> list[tuple[str, str]]:
        """(vecino, tipo) en ambas direcciones; la dirección inversa de 'pertenece_a_mapa' es 'contiene'."""
        resultado = []
        for arista in self.aristas:
            if arista.origen == nodo:
                resultado.append((arista.destino, arista.tipo))
            elif arista.destino == nodo:
                inverso = {"pertenece_a_mapa": "contiene", "contiene": "pertenece_a_mapa"}.get(arista.tipo, arista.tipo)
                resultado.append((arista.origen, inverso))
        return resultado

    def mapas_de(self, nodo: str) -> list[str]:
        return sorted(
            {d for d, t in self.vecinos(nodo) if t == "pertenece_a_mapa" and self.nodos.get(d, Nodo(id=d)).tipo == "mapa"}
        )

    def fragmentos_de(self, nodo: str) -> list[Fragmento]:
        return [f for f in self.fragmentos if f.nodo == nodo]

    def guardar(self, ruta: Path) -> None:
        ruta.write_text(self.model_dump_json(), encoding="utf-8")

    @classmethod
    def cargar(cls, ruta: Path) -> "Grafo":
        return cls.model_validate(json.loads(ruta.read_text(encoding="utf-8")))
