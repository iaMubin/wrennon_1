"""
Cohere embedding helper for Pinecone.

This module provides a thin wrapper that calls the Cohere embed API
directly and returns raw lists of floats.
"""

from __future__ import annotations

import cohere


class CohereEmbedder:
    """Calls Cohere's embed API and returns embeddings as float lists."""

    def __init__(self, api_key: str, model_name: str = "embed-english-v3.0"):
        self._client = cohere.Client(api_key)
        self._model = model_name

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embed(
            texts=texts,
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
