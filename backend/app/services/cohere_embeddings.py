"""
Cohere embedding helper for ChromaDB.

ChromaDB 0.5.x's built-in CohereEmbeddingFunction is incompatible with
cohere SDK v5 — the response shape changed from a plain list to a typed
object, so ChromaDB gets back tuples instead of float lists and crashes.

This module provides a thin wrapper that calls the Cohere embed API
directly and returns the format ChromaDB expects.
"""

from __future__ import annotations

import cohere
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings


class CohereEmbedder(EmbeddingFunction[Documents]):
    """Calls Cohere's embed API and returns embeddings in the format
    ChromaDB expects: a plain list of float lists."""

    def __init__(self, api_key: str, model_name: str = "embed-english-v3.0"):
        self._client = cohere.Client(api_key)
        self._model = model_name

    def __call__(self, input: Documents) -> Embeddings:
        response = self._client.embed(
            texts=list(input),
            model=self._model,
            input_type="search_document",
        )
        return [list(e) for e in response.embeddings]


class CohereQueryEmbedder:
    """Same as CohereEmbedder but uses input_type='search_query' for
    query-time embedding (Cohere v3 models distinguish between document
    and query embeddings)."""

    def __init__(self, api_key: str, model_name: str = "embed-english-v3.0"):
        self._client = cohere.Client(api_key)
        self._model = model_name

    def embed_query(self, text: str) -> list[float]:
        response = self._client.embed(
            texts=[text],
            model=self._model,
            input_type="search_query",
        )
        return list(response.embeddings[0])
