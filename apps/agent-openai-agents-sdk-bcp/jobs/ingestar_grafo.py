"""Job de Databricks: ingesta de la bóveda Obsidian de buenas prácticas al grafo de conocimiento.

1. Lee la bóveda desde un Volume de Unity Catalog (los Volumes están montados en el cómputo serverless).
2. Construye nodos, aristas tipadas y fragmentos (mismo código que usa la app: `mrm.conocimiento`).
3. Escribe las tablas Delta `kg_nodos`, `kg_aristas` y `kg_fragmentos` (con Change Data Feed).
4. Exporta `grafo.json` al Volume: es lo que carga la app (variable MRM_GRAFO).
5. Opcional: crea o sincroniza un índice de Vector Search sobre `kg_fragmentos` (variable MRM_INDICE_VECTORIAL).

Parámetros:
  --boveda           /Volumes/<catalogo>/<esquema>/<volumen>/conocimiento/boveda
  --catalogo         catálogo de Unity Catalog
  --esquema          esquema de Unity Catalog
  --salida_json      /Volumes/.../conocimiento/grafo.json
  --endpoint_vs      (opcional) endpoint de Vector Search
  --modelo_embeddings (opcional) endpoint de embeddings, p. ej. databricks-gte-large-en
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mrm.conocimiento.ingesta_obsidian import ingerir_boveda  # noqa: E402


def _crear_o_sincronizar_indice(tabla: str, endpoint: str, modelo: str) -> str:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.vectorsearch import (
        DeltaSyncVectorIndexSpecRequest,
        EmbeddingSourceColumn,
        PipelineType,
        VectorIndexType,
    )

    cliente = WorkspaceClient()
    indice = f"{tabla}_indice"
    existentes = {i.name for i in cliente.vector_search_indexes.list_indexes(endpoint_name=endpoint)}
    if indice in existentes:
        cliente.vector_search_indexes.sync_index(index_name=indice)
    else:
        cliente.vector_search_indexes.create_index(
            name=indice,
            endpoint_name=endpoint,
            primary_key="id",
            index_type=VectorIndexType.DELTA_SYNC,
            delta_sync_index_spec=DeltaSyncVectorIndexSpecRequest(
                source_table=tabla,
                pipeline_type=PipelineType.TRIGGERED,
                embedding_source_columns=[EmbeddingSourceColumn(name="texto", embedding_model_endpoint_name=modelo)],
            ),
        )
    return indice


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--boveda", required=True)
    parser.add_argument("--catalogo", required=True)
    parser.add_argument("--esquema", required=True)
    parser.add_argument("--salida_json", required=True)
    parser.add_argument("--endpoint_vs", default="")
    parser.add_argument("--modelo_embeddings", default="databricks-gte-large-en")
    argumentos = parser.parse_args(argv)

    grafo = ingerir_boveda(Path(argumentos.boveda))
    print(f"Grafo: {len(grafo.nodos)} nodos, {len(grafo.aristas)} aristas, {len(grafo.fragmentos)} fragmentos")

    salida = Path(argumentos.salida_json)
    salida.parent.mkdir(parents=True, exist_ok=True)
    grafo.guardar(salida)
    print(f"grafo.json exportado a {salida}")

    from pyspark.sql import SparkSession

    spark = SparkSession.builder.getOrCreate()
    prefijo = f"{argumentos.catalogo}.{argumentos.esquema}"
    tablas = {
        "kg_nodos": [n.model_dump() for n in grafo.nodos.values()],
        "kg_aristas": [a.model_dump() for a in grafo.aristas],
        "kg_fragmentos": [f.model_dump() for f in grafo.fragmentos],
    }
    for nombre, filas in tablas.items():
        spark.createDataFrame(filas).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{prefijo}.{nombre}")
        print(f"Tabla {prefijo}.{nombre}: {len(filas)} filas")
    spark.sql(f"ALTER TABLE {prefijo}.kg_fragmentos SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")

    if argumentos.endpoint_vs:
        indice = _crear_o_sincronizar_indice(f"{prefijo}.kg_fragmentos", argumentos.endpoint_vs, argumentos.modelo_embeddings)
        print(f"Índice de Vector Search: {indice} (usar en MRM_INDICE_VECTORIAL)")


if __name__ == "__main__":
    main()
