from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.auth.tenant_resolution import TENANT_KEY_HEADER, resolve_public_tenant
from app.db.session import get_db

from app.limiter import limiter
from app.services import ratelimit
from app.services.vectorstore import retrieve_and_rerank

router = APIRouter()

_MAX_SNIPPET = 1200
_GLOBAL_HOURLY_CAP = 1500   # total public searches/hour: bounds Cohere + Pinecone spend


@router.get("/search")
@limiter.limit("10/minute;60/hour")
async def search_kb(request: Request, q: str = Query(..., min_length=2, max_length=200), db: Session = Depends(get_db)):
    """Unauthenticated help-center search.

    Only *public* documents are returned (auto-drafted conversation articles are
    internal), only their text, trimmed, and the query is length-bounded: the old
    version embedded and reranked arbitrarily long input for anyone.
    """
    tenant_id = resolve_public_tenant(db, request.headers.get(TENANT_KEY_HEADER))
    if await ratelimit.hit("pubkb:global", 3600) > _GLOBAL_HOURLY_CAP:
        raise HTTPException(status_code=429, detail="Search is busy. Please try again later.")
    results = await retrieve_and_rerank(q.strip(), top_k=5, include_internal=False, tenant_id=tenant_id)
    return {"results": [{"text": r.get("text", "")[:_MAX_SNIPPET], "relevance_score": r.get("relevance_score")} for r in results]}
