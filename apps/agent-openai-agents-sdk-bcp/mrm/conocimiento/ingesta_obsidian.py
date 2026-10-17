"""Ingesta de una bóveda Obsidian al modelo de grafo.

Convenciones que reconoce (todas opcionales):
- frontmatter YAML con `tipo`, `dominio`, `temas`;
- notas de tipo `mapa` (o con prefijo "Mapa - ") que agrupan notas por tema;
- sección "Relacionado" con una línea "Mapa: [[...]]" y enlaces a notas afines.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from mrm.conocimiento.modelo import Arista, Fragmento, Grafo, Nodo

CARPETAS_EXCLUIDAS = (".obsidian", ".git", "plantillas", "tmp", "scripts", "00-inbox", "99-procesados", ".trash")
_ENLACE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
_ENCABEZADO = re.compile(r"^(#{1,6})\s+(.*)$")
MAX_CARACTERES_FRAGMENTO = 1500


def _frontmatter(texto: str) -> tuple[dict, str]:
    if not texto.startswith("---"):
        return {}, texto
    partes = texto.split("\n---", 1)
    if len(partes) < 2:
        return {}, texto
    try:
        datos = yaml.safe_load(partes[0][3:]) or {}
    except yaml.YAMLError:
        datos = {}
    cuerpo = partes[1].split("\n", 1)[1] if "\n" in partes[1] else ""
    return (datos if isinstance(datos, dict) else {}), cuerpo


def _lista(valor) -> list[str]:
    if valor is None:
        return []
    valores = valor if isinstance(valor, list) else [valor]
    resultado = []
    for v in valores:
        enlaces = _ENLACE.findall(str(v))
        resultado.extend(e.strip() for e in enlaces) if enlaces else resultado.append(str(v).strip())
    return resultado


def _secciones(cuerpo: str) -> list[tuple[str, str]]:
    secciones: list[tuple[str, list[str]]] = [("Introducción", [])]
    for linea in cuerpo.splitlines():
        coincidencia = _ENCABEZADO.match(linea)
        if coincidencia:
            secciones.append((coincidencia.group(2).strip(), []))
        else:
            secciones[-1][1].append(linea)
    return [(titulo, "\n".join(lineas).strip()) for titulo, lineas in secciones if "\n".join(lineas).strip()]


def _partir(texto: str) -> list[str]:
    if len(texto) <= MAX_CARACTERES_FRAGMENTO:
        return [texto]
    partes, actual = [], ""
    for parrafo in texto.split("\n\n"):
        if actual and len(actual) + len(parrafo) > MAX_CARACTERES_FRAGMENTO:
            partes.append(actual.strip())
            actual = ""
        actual += parrafo + "\n\n"
    if actual.strip():
        partes.append(actual.strip())
    return partes


def ingerir_boveda(raiz: Path, excluidas: tuple[str, ...] = CARPETAS_EXCLUIDAS) -> Grafo:
    grafo = Grafo()
    pendientes: list[tuple[str, str, str]] = []
    for ruta in sorted(raiz.rglob("*.md")):
        relativa = ruta.relative_to(raiz)
        if any(parte in excluidas for parte in relativa.parts) or relativa.name in ("README.md", "CLAUDE.md"):
            continue
        datos, cuerpo = _frontmatter(ruta.read_text(encoding="utf-8", errors="replace"))
        titulo = ruta.stem
        tipo = str(datos.get("tipo") or ("mapa" if titulo.startswith("Mapa - ") else "nota"))
        grafo.nodos[titulo] = Nodo(
            id=titulo, tipo=tipo, dominios=_lista(datos.get("dominio")), temas=_lista(datos.get("temas")), ruta=relativa.as_posix()
        )
        for dominio in _lista(datos.get("dominio")):
            pendientes.append((titulo, dominio, "dominio"))

        for indice, (seccion, texto) in enumerate(_secciones(cuerpo)):
            for parte, fragmento in enumerate(_partir(texto)):
                grafo.fragmentos.append(Fragmento(id=f"{titulo}::{indice}.{parte}", nodo=titulo, seccion=seccion, texto=fragmento))
            relacionado = seccion.lower().startswith("relacionad")
            for linea in texto.splitlines():
                for destino in _ENLACE.findall(linea):
                    destino = destino.strip()
                    if tipo == "mapa":
                        tipo_arista = "contiene"
                    elif relacionado and linea.lstrip("- ").lower().startswith("mapa"):
                        tipo_arista = "pertenece_a_mapa"
                    elif relacionado:
                        tipo_arista = "relacionado"
                    else:
                        tipo_arista = "menciona"
                    pendientes.append((titulo, destino, tipo_arista))

    vistas: set[tuple[str, str, str]] = set()
    for origen, destino, tipo_arista in pendientes:
        if destino == origen or (origen, destino, tipo_arista) in vistas:
            continue
        vistas.add((origen, destino, tipo_arista))
        if destino not in grafo.nodos:
            grafo.nodos[destino] = Nodo(id=destino, tipo="dominio" if tipo_arista == "dominio" else "referencia")
        grafo.aristas.append(Arista(origen=origen, destino=destino, tipo=tipo_arista))
    return grafo
