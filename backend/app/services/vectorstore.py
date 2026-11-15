"""
Vector store access: Pinecone for retrieval, Cohere for both
embeddings and reranking.

Embeddings are generated via Cohere's API (embed-english-v3.0) instead
of a local sentence-transformers model. This keeps RAM usage under the
512 MB limit on Render's free tier — sentence-transformers + PyTorch
alone would consume ~500 MB before any application code even loads.
"""

from __future__ import annotations

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

def namespace_for(tenant_id: str | None = None) -> str:
    """Pinecone namespace of a tenant. The default tenant keeps the legacy (empty)
    namespace so existing vectors stay valid; every other tenant is isolated in
    its own namespace and can never retrieve another tenant's documents."""
    from app.db.tenancy import DEFAULT_TENANT_ID, current_tenant

    tid = tenant_id or current_tenant.get() or DEFAULT_TENANT_ID
    return "" if tid == DEFAULT_TENANT_ID else f"t_{tid}"


async def retrieve_and_rerank(query: str, top_k: int = 3, include_internal: bool = True, tenant_id: str | None = None) -> list[dict]:
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
    namespace = namespace_for(tenant_id)
    
    def _pinecone_query():
        return index.query(
            vector=query_embedding,
            top_k=max(top_k * 3, 5),
            include_metadata=True,
            namespace=namespace,
        )
        
    pinecone_start = time.time()
    results = await asyncio.to_thread(_pinecone_query)
    logger.info(f"[TIMING] Pinecone Fetch took {time.time() - pinecone_start:.3f}s")

    if not results.matches:
        return []

    # Filter in Python (not via a Pinecone $ne filter): documents ingested before
    # the visibility field existed have no such key and must count as public.
    candidates = [
        match.metadata["text"]
        for match in results.matches
        if "text" in match.metadata and (include_internal or match.metadata.get("visibility", "public") != "internal")
    ]
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

def delete_from_pinecone(gap_id: str, tenant_id: str | None = None) -> None:
    """Remove a previously inserted auto-generated article (unpublish / rollback)."""
    if settings.pinecone_api_key == "YOUR_NEW_PINECONE_API_KEY":
        logger.info(f"Mocked removal of vector for: {gap_id}")
        return
    vector_id = "kb_" + gap_id   # a vector id, not SQL
    _get_index().delete(ids=[vector_id], namespace=namespace_for(tenant_id))
    logger.info(f"Removed KB article kb_{gap_id} from Pinecone")


def insert_into_pinecone(title: str, text: str, gap_id: str, approved_by: str | None = None, tenant_id: str | None = None):
    """Embeds and inserts a new KB article into Pinecone."""
    if settings.pinecone_api_key == "YOUR_NEW_PINECONE_API_KEY":
        logger.info(f"Mocked insert into pinecone for: {title}")
        return

    # Use document embedding type for indexing
    embedding = _doc_embedder.embed_documents([text])[0]
    
    index = _get_index()
    index.upsert(
        namespace=namespace_for(tenant_id),
        vectors=[
            {
                "id": f"kb_{gap_id}",
                "values": embedding,
                "metadata": {
                    "title": title,
                    "text": text,
                    "source": "auto_generated_gap",
                    # Drafted from conversations: usable by the AI agent, never
                    # returned by the unauthenticated public search.
                    "visibility": "internal",
                    "approved_by": approved_by or "",
                }
            }
        ]
    )
    logger.info(f"Inserted new KB article into Pinecone: {title}")
