"""
Vector store access: ChromaDB for retrieval, Cohere for both
embeddings and reranking.

Embeddings are generated via Cohere's API (embed-english-v3.0) instead
of a local sentence-transformers model. This keeps RAM usage under the
512 MB limit on Render's free tier — sentence-transformers + PyTorch
alone would consume ~500 MB before any application code even loads.
"""

from __future__ import annotations

import uuid
from pinecone import Pinecone
import cohere

from app.config import settings
from app.services.cohere_embeddings import CohereEmbedder, CohereQueryEmbedder

_doc_embedder = CohereEmbedder(
    api_key=settings.cohere_api_key,
    model_name="embed-english-v3.0",
)

_query_embedder = CohereQueryEmbedder(
    api_key=settings.cohere_api_key,
    model_name="embed-english-v3.0",
)

_pinecone = Pinecone(api_key=settings.pinecone_api_key)
_index = _pinecone.Index(host=settings.pinecone_host)

_cohere_client = cohere.Client(settings.cohere_api_key)


def retrieve_and_rerank(query: str, top_k: int = 3) -> list[dict]:
    """Retrieve candidate chunks from ChromaDB, then rerank with Cohere.

    Returns:
        list of dicts, ordered by relevance, each shaped like:
        {"text": str, "relevance_score": float}
        Empty list if the collection has no documents yet.
    """
    # Use search_query input_type for queries (Cohere v3 models
    # produce better results when document vs query is distinguished)
    query_embedding = _query_embedder.embed_query(query)

    # Pinecone fetch
    results = _index.query(
        vector=query_embedding,
        top_k=max(top_k * 3, 5),
        include_metadata=True
    )

    if not results.matches:
        return []

    candidates = [match.metadata["text"] for match in results.matches if "text" in match.metadata]
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
