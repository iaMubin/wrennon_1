"""
Vector store access: ChromaDB for retrieval, Cohere for reranking the
candidates before they're handed to the LLM.
"""

from __future__ import annotations

import chromadb
import cohere
from sentence_transformers import SentenceTransformer

from app.config import settings

_chroma_client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
_collection = _chroma_client.get_or_create_collection(settings.chroma_collection_name)
_embedder = SentenceTransformer(settings.embedding_model)
_cohere_client = cohere.Client(settings.cohere_api_key)


def retrieve_and_rerank(query: str, top_k: int = 3) -> list[dict]:
    """Retrieve candidate chunks from ChromaDB, then rerank with Cohere.

    Returns:
        list of dicts, ordered by relevance, each shaped like:
        {"text": str, "relevance_score": float}
        Empty list if the collection has no documents yet.
    """
    query_embedding = _embedder.encode(query).tolist()

    results = _collection.query(
        query_embeddings=[query_embedding],
        n_results=max(top_k * 3, 5),  # over-fetch so reranking has real choices
    )

    candidates = results.get("documents", [[]])[0]
    if not candidates:
        return []

    reranked = _cohere_client.rerank(
        query=query,
        documents=candidates,
        top_n=top_k,
        model="rerank-english-v3.0",
    )

    return [
        {"text": candidates[result.index], "relevance_score": result.relevance_score}
        for result in reranked.results
    ]
