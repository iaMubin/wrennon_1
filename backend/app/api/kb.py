from fastapi import APIRouter
from pydantic import BaseModel
import random

router = APIRouter()

class KBResponse(BaseModel):
    title: str
    content: str
    confidence: str

@router.post("/suggest", response_model=KBResponse)
async def suggest_kb():
    # Mock generation based on recent queries
    titles = [
        "How to Handle Order Delays",
        "Updated Return Policy 2026",
        "Troubleshooting Payment Failures",
        "International Shipping Guidelines"
    ]
    contents = [
        "This article covers the standard operating procedures for handling order delays. When an order is delayed, agents should proactively reach out and offer a 10% discount on the next purchase...",
        "Our new return policy allows customers to return items within 60 days. Products must be in original packaging. Exceptions apply to perishable goods...",
        "If a customer experiences a payment failure, first verify their billing address matches the card on file. If the issue persists, advise them to contact their bank or try an alternative payment method...",
        "For international shipping, ensure that customs forms are accurately filled out. Delivery times vary by region, typically taking 7-14 business days. Expedited options are available..."
    ]
    
    idx = random.randint(0, len(titles) - 1)  # nosec B311
    return KBResponse(
        title=titles[idx],
        content=contents[idx],
        confidence=f"{random.randint(85, 99)}%"  # nosec B311
    )
