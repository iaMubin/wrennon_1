"""
Vector store access: Pinecone for retrieval, Cohere for both
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
import time
from app.logger import logger

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

_pinecone = None
_index = None

def _get_index():
    global _pinecone, _index
    if _index is None:
        _pinecone = Pinecone(api_key=settings.pinecone_api_key)
        _index = _pinecone.Index(host=settings.pinecone_host)
    return _index

_cohere_client = None

def _get_cohere():
    global _cohere_client
    if _cohere_client is None:
        _cohere_client = cohere.AsyncClient(settings.cohere_api_key)
    return _cohere_client

import asyncio

async def retrieve_and_rerank(query: str, top_k: int = 3) -> list[dict]:
    """Retrieve candidate chunks from Pinecone, then rerank with Cohere.

    Returns:
        list of dicts, ordered by relevance, each shaped like:
        {"text": str, "relevance_score": float}
        Empty list if the collection has no documents yet.
    """
    # Use search_query input_type for queries (Cohere v3 models
    # produce better results when document vs query is distinguished)
    start_time = time.time()
    
    # Mock for local testing if API key is not configured
    if settings.pinecone_api_key == "YOUR_NEW_PINECONE_API_KEY":
        logger.info("Using mocked knowledge base (Pinecone API key not set).")
        query_lower = query.lower()
        if "refund" in query_lower or "cancel" in query_lower:
            return [{"text": "Orders can be self-cancelled within 24 hours of placement. Once an order has shipped, it cannot be self-cancelled. Customers must request a refund through a support agent, who will process it manually.", "relevance_score": 0.99}]
        return [{"text": "We offer a 30-day return policy for most items. For other inquiries, please escalate to a human agent.", "relevance_score": 0.8}]
    
    query_embedding = await asyncio.to_thread(_query_embedder.embed_query, query)
    logger.info(f"[TIMING] Cohere Embed Query took {time.time() - start_time:.3f}s")

    # Pinecone fetch
    index = _get_index()
    
    def _pinecone_query():
        return index.query(
            vector=query_embedding,
            top_k=max(top_k * 3, 5),
            include_metadata=True
        )
        
    pinecone_start = time.time()
    results = await asyncio.to_thread(_pinecone_query)
    logger.info(f"[TIMING] Pinecone Fetch took {time.time() - pinecone_start:.3f}s")

    if not results.matches:
        return []

    candidates = [match.metadata["text"] for match in results.matches if "text" in match.metadata]
    if not candidates:
        return []

    cohere_client = _get_cohere()
    rerank_start = time.time()
    reranked = await cohere_client.rerank(
        query=query,
        documents=candidates,
        top_n=top_k,
        model="rerank-english-v3.0",
    )
    logger.info(f"[TIMING] Cohere Rerank took {time.time() - rerank_start:.3f}s")

    return [
        {"text": candidates[result.index], "relevance_score": result.relevance_score}
        for result in reranked.results
    ]
