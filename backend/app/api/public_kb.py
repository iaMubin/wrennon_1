from fastapi import APIRouter, Request, Query
from app.services.vectorstore import retrieve_and_rerank
from app.limiter import limiter

router = APIRouter()

@router.get("/search")
@limiter.limit("10/minute")
async def search_kb(request: Request, q: str = Query(..., min_length=2)):
    results = await retrieve_and_rerank(q, top_k=5)
    return {"results": results}
