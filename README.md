# Wrennon Showcase Agent — L1 + L2

A customer service agent demo built on a LangGraph state backbone, currently
covering:

- **L1** — policy RAG with grounded fallback (ChromaDB + Cohere rerank + Groq)
- **L2** — order status lookup and human handoff, both currently backed by
  mock functions in `app/services/mock_apis.py` with real-matching signatures

L3 (subscription actions) and L4 (multi-agent refund pipeline) are reserved
in the state schema (`app/graph/state.py`) but not yet built.

## Setup

```bash
cd backend
conda create -n wrennon-showcase python=3.12
conda activate wrennon-showcase
pip install -r requirements.txt
cp .env.example .env   # fill in GROQ_API_KEY and COHERE_API_KEY
```

Drop policy documents (PDF or TXT) into `backend/data/policy_docs/`, then:

```bash
python scripts/ingest.py
```

Run the API:

```bash
uvicorn app.main:app --reload --port 8000
```

Open `frontend/index.html` directly in a browser (or serve it with any
static server — e.g. `python -m http.server 5500` from inside `frontend/`).
Make sure the port you serve it on is listed in `CORS_ALLOWED_ORIGINS` in
`.env`.

## Swapping a mock for the real integration

Every function in `app/services/mock_apis.py` keeps the signature and
return shape the real API will use. To go live:

1. Open the function (e.g. `get_order_status`).
2. Replace everything below the `--- MOCK BODY ---` marker with the real
   API call.
3. Keep the return shape identical to what's documented in the docstring.

No other file needs to change — graph nodes call these functions by name
and only care about the shape of what comes back.

## Known limitations (by design, for this phase)

- Sessions are stored in-memory (`SESSION_STORE` in `app/api/chat.py`) —
  fine for a single-process live demo, not for production.
- Intent routing in `app/graph/builder.py` uses keyword matching, not an
  LLM classifier — predictable for scripted demo runs.
- No observability/tracing layer yet — add before this handles real
  customer traffic.
