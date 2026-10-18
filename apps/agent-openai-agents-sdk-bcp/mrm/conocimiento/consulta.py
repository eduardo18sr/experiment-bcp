"""Consulta GraphRAG local: semillas por relevancia de texto y expansión por las aristas del grafo.

1. Semillas: fragmentos más relevantes por BM25 (y, si hay índice vectorial, por similitud semántica).
2. Expansión: la relevancia de cada nota semilla se propaga a sus vecinas según el tipo de arista,
   lo que trae prácticas relacionadas que no comparten palabras con la consulta.
3. Resultado: notas con su mejor fragmento, el mapa al que pertenecen y el camino que las trajo.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Protocol

from pydantic import BaseModel, Field

from mrm.conocimiento.modelo import PESOS_ARISTA, Fragmento, Grafo

TIPOS_NO_RECUPERABLES = ("mapa", "dominio", "referencia", "fuente")
_PALABRAS_VACIAS = set(
    "a al algo ante antes como con contra cual cuando de del desde donde dos el ella ellas ellos en entre era es esa ese "
    "eso esta este esto estos fue ha hay la las le les lo los mas me mi muy no nos o otra otro para pero por que se "
    "sea segun ser si sin sobre son su sus tambien te tiene todo tu un una uno unos y ya the of and to in is for".split()
)


def terminos(texto: str) -> list[str]:
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    palabras = re.findall(r"[a-z0-9]+", texto)
    # Truncar a 6 caracteres funciona como un stemmer tosco para el español (parametro/parametros).
    return [p[:6] for p in palabras if len(p) > 2 and p not in _PALABRAS_VACIAS]


class BuscadorSemantico(Protocol):
    """Puerto para semillas semánticas (p. ej. Mosaic AI Vector Search)."""

    def buscar(self, consulta: str, k: int) -> list[tuple[str, float]]:
        """Devuelve (id_fragmento, puntaje en [0, 1])."""
        ...


class PracticaRecuperada(BaseModel):
    nota: str
    seccion: str
    cita: str = Field(description="Texto literal del fragmento")
    puntaje: float
    mapas: list[str] = Field(default_factory=list)
    camino: str = Field(description="'semilla' o cómo se llegó por el grafo")


class IndiceBM25:
    def __init__(self, fragmentos: list[Fragmento], k1: float = 1.5, b: float = 0.75):
        self.fragmentos = fragmentos
        self.k1, self.b = k1, b
        self.documentos = [Counter(terminos(f"{f.nodo} {f.seccion} {f.texto}")) for f in fragmentos]
        self.longitudes = [sum(d.values()) for d in self.documentos]
        self.promedio = (sum(self.longitudes) / len(self.longitudes)) if self.longitudes else 0.0
        frecuencia_doc: Counter = Counter()
        for documento in self.documentos:
            frecuencia_doc.update(documento.keys())
        n = len(fragmentos)
        self.idf = {t: math.log(1 + (n - df + 0.5) / (df + 0.5)) for t, df in frecuencia_doc.items()}

    def puntajes(self, consulta: str) -> list[float]:
        terminos_consulta = terminos(consulta)
        resultado = []
        for documento, longitud in zip(self.documentos, self.longitudes):
            puntaje = 0.0
            for termino in terminos_consulta:
                frecuencia = documento.get(termino, 0)
                if frecuencia:
                    normalizador = self.k1 * (1 - self.b + self.b * longitud / (self.promedio or 1))
                    puntaje += self.idf[termino] * frecuencia * (self.k1 + 1) / (frecuencia + normalizador)
            resultado.append(puntaje)
        return resultado


SECCIONES_ESTRUCTURALES = ("relacionado", "relacionadas", "relacionados", "fuentes", "notas por subtema")
MAX_NOTAS_MAPA_EXPANSION = 25


class ConsultorGrafo:
    def __init__(self, grafo: Grafo, semantico: BuscadorSemantico | None = None, semillas: int = 5):
        self.grafo = grafo
        self.semantico = semantico
        self.semillas = semillas
        # Las secciones de enlaces son estructura del grafo (aristas), no contenido: no se recuperan como texto.
        self.recuperables = [
            f for f in grafo.fragmentos
            if grafo.nodos.get(f.nodo)
            and grafo.nodos[f.nodo].tipo not in TIPOS_NO_RECUPERABLES
            and f.seccion.strip().lower() not in SECCIONES_ESTRUCTURALES
        ]
        self.indice = IndiceBM25(self.recuperables)
        self._por_id = {f.id: f for f in self.recuperables}

    def _relevancia_fragmentos(self, consulta: str) -> dict[str, float]:
        lexica = self.indice.puntajes(consulta)
        maximo = max(lexica) if lexica else 0.0
        relevancia = {f.id: (p / maximo if maximo else 0.0) for f, p in zip(self.recuperables, lexica)}
        if self.semantico is not None:
            for id_fragmento, puntaje in self.semantico.buscar(consulta, self.semillas * 3):
                if id_fragmento in relevancia:
                    relevancia[id_fragmento] = 0.5 * relevancia[id_fragmento] + 0.5 * puntaje
        return relevancia

    def buscar(self, consulta: str, k: int = 5) -> list[PracticaRecuperada]:
        relevancia = self._relevancia_fragmentos(consulta)
        mejor_fragmento: dict[str, tuple[float, Fragmento]] = {}
        for fragmento in self.recuperables:
            puntaje = relevancia.get(fragmento.id, 0.0)
            if puntaje > mejor_fragmento.get(fragmento.nodo, (-1.0, None))[0]:
                mejor_fragmento[fragmento.nodo] = (puntaje, fragmento)

        # Relevancia propia de cada nota: su mejor fragmento.
        propio = {n: p for n, (p, _) in mejor_fragmento.items() if p > 0}
        semillas = sorted(((p, n) for n, p in propio.items()), reverse=True)[: self.semillas]
        camino: dict[str, str] = {n: "semilla" for _, n in semillas}

        # Expansión: cada vecina recibe el MÁXIMO aporte de sus semillas (no la suma), para que una nota
        # conectada a muchas semillas débiles no supere a una semilla fuerte.
        aporte: dict[str, float] = {}
        for puntaje_semilla, semilla in semillas:
            for vecino, tipo in self.grafo.vecinos(semilla):
                nodo = self.grafo.nodos.get(vecino)
                if nodo is None:
                    continue
                if nodo.tipo == "mapa":
                    hermanas = [h for h, t in self.grafo.vecinos(vecino) if t == "contiene" and h != semilla]
                    if len(hermanas) <= MAX_NOTAS_MAPA_EXPANSION:
                        for hermana in hermanas:
                            self._propagar(aporte, camino, hermana, puntaje_semilla * 0.1, f"mismo mapa que [[{semilla}]] ([[{vecino}]])")
                    continue
                self._propagar(aporte, camino, vecino, puntaje_semilla * PESOS_ARISTA.get(tipo, 0.1), f"[[{semilla}]] → {tipo}")

        puntaje_nota = {n: propio.get(n, 0.0) + aporte.get(n, 0.0) for n in set(propio) | set(aporte)}
        for nota in puntaje_nota:
            camino.setdefault(nota, "relevancia propia")

        resultado = []
        for nota, puntaje in sorted(puntaje_nota.items(), key=lambda x: -x[1]):
            nodo = self.grafo.nodos.get(nota)
            if nodo is None or nodo.tipo in TIPOS_NO_RECUPERABLES or nota not in mejor_fragmento:
                continue
            fragmento = mejor_fragmento[nota][1]
            resultado.append(
                PracticaRecuperada(
                    nota=nota,
                    seccion=fragmento.seccion,
                    cita=fragmento.texto,
                    puntaje=round(puntaje, 4),
                    mapas=self.grafo.mapas_de(nota),
                    camino=camino[nota],
                )
            )
            if len(resultado) == k:
                break
        return resultado

    @staticmethod
    def _propagar(aportes, camino, nota, valor, descripcion) -> None:
        if valor > aportes.get(nota, 0.0):
            aportes[nota] = valor
            if camino.get(nota) != "semilla":
                camino[nota] = descripcion

    def cita_existe(self, nota: str, cita: str) -> bool:
        """Guardrail de fidelidad: la cita debe aparecer literalmente en algún fragmento de la nota."""
        objetivo = " ".join(cita.split())
        return any(objetivo in " ".join(f.texto.split()) for f in self.grafo.fragmentos_de(nota)) if objetivo else False
