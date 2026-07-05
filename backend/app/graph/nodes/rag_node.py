"""
L1 node: retrieve policy context, then let the LLM generate an answer
or say it doesn't know — based on its own judgment of the context, not
a hardcoded score gate.

Two approaches were tried and rejected before this one:

1. Absolute Cohere score threshold (e.g. 0.55). Rejected: Cohere's own
   docs say relevance scores are query-dependent and not comparable
   across queries as fixed numbers. A broad question ("what's your
   return policy?") scored ~0.05 at the top while a specific one
   ("i want to return it") scored ~0.70 — both were genuinely
   well-grounded, just on completely different absolute scales. No
   single fixed number works for both.

2. Relative gap between top and second result (top must be >=1.4x the
   second). Rejected: this actively broke well-grounded queries. For
   "i want to return it", the top three chunks were consecutive steps
   of the same return process — all genuinely relevant, so their
   scores were close together (0.70 / 0.62 / 0.53, ratio ~1.12). The
   gap check read that closeness as "nothing stands out" and routed to
   fallback, when in fact the closeness was a sign of a coherent,
   well-covered answer.

Both failures share a root cause: vector/rerank scores measure semantic
similarity, not "is this enough to answer the question" — that's a
judgment call the LLM is better positioned to make than a fixed number
ever was. The system prompt in app/services/llm.py already instructs
the model to say so plainly if the context doesn't fully answer the
question, so the fallback message below is now a true last resort —
only for the case where retrieval finds nothing at all to hand the
LLM in the first place.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from app.graph.state import ConversationState
from app.services.llm import generate_answer
from app.services.vectorstore import retrieve_and_rerank

ABSOLUTE_FLOOR = 0.01
# Only catches the case where retrieval returns nothing with any signal
# at all (empty collection, or a query genuinely outside the knowledge
# base entirely). Everything above this floor goes to the LLM, which
# makes the actual "is this enough to answer" judgment.

FALLBACK_MESSAGE = (
    "I don't have that information in our policy documentation. "
    "I can connect you with a member of our support team if you'd like."
)


def rag_node(state: ConversationState) -> ConversationState:
    last_user_message = state["messages"][-1].content

    retrieved = retrieve_and_rerank(query=last_user_message, top_k=3)

    if not retrieved or retrieved[0]["relevance_score"] < ABSOLUTE_FLOOR:
        state["last_retrieved_context"] = None
        state["answer_grounded"] = False
        state["handoff_requested"] = True  # Silent escalation for missing knowledge
        return state

    context = "\n\n".join(chunk["text"] for chunk in retrieved)

    state["last_retrieved_context"] = context
    state["answer_grounded"] = True
    return state
