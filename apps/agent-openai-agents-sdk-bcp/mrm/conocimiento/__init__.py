"""Grafo de conocimiento de buenas prácticas (GraphRAG).

Ingesta: una bóveda Obsidian (notas Markdown enlazadas con [[wikilinks]]) se convierte en nodos,
aristas tipadas y fragmentos. En Databricks se persiste en tablas Delta y en `grafo.json` en un Volume;
la app consulta el JSON y, si existe, un índice de Vector Search para las semillas semánticas.
"""
