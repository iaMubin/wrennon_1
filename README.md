# Wrennon Customer Support Platform

An AI-first, web-chat customer support platform built on a LangGraph state backbone. It seamlessly routes customer queries to an autonomous AI agent for immediate resolution, with real-time handoff to human agents when complex intervention is required.

## Key Features

- **Autonomous AI Resolution:** Uses LangGraph to orchestrate customer intent routing, policy retrieval (RAG via Pinecone + Cohere Rerank), and empathetic response generation (via Groq/Llama-3).
- **Seamless Human Handoff:** Real-time WebSockets ensure that when an AI reaches its limits, the conversation is instantly transferred to a live human agent without the customer experiencing dropped context.
- **Live Agent Dashboard:** A secure portal for agents to handle escalated tickets, view customer history and order details dynamically, communicate via internal notes, and manage SLAs.
- **Admin Control Panel:** Role-based access control (RBAC) allowing Admins to manage agent accounts, monitor performance, and enforce security policies.
- **Order Context:** Parses messages for Order IDs and emails to retrieve and display customer/order data to agents (web chat channel only; Shopify/Zendesk integrations are stubs, demo data is used when `USE_MOCK_INTEGRATIONS=true`).
- **Multimedia Support:** Supports image uploads and parsing for enhanced issue diagnosis.

## Evals

`backend/evals/cases.yaml` holds the agent's regression cases (order lookup + identity checks, prompt-injection vs. money tools, escalation, PII masking). Add one case for every production failure.

```bash
cd backend && pytest tests/test_evals.py      # CI: scripted LLM, deterministic, free
python -m evals.run_live --dry-run            # check the live runner itself, no API calls
python -m evals.run_live                      # REAL model, billable (needs GROQ_API_KEY + `alembic upgrade head`)
```
Stub mode proves the code *around* the model (routing, tool gating, masking). Only `run_live` tells you how the model itself behaves.

## Architecture Stack

- **Backend:** Python 3.12, FastAPI, WebSockets, SQLAlchemy (PostgreSQL in production, SQLite for local dev), LangChain / LangGraph.
- **Frontend:** Vanilla HTML, CSS, JavaScript (zero-build, highly optimized widget).
- **AI & Data:** Groq (LLM), Pinecone (Vector Database), Cohere (Reranking).

---

## Local Setup

### 1. Environment Preparation
```bash
cd backend
python -m venv venv
# On Windows
venv\Scripts\activate
# On Mac/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configuration
Copy the example environment file and fill in your API keys:
```bash
cp .env.example .env
```
Ensure you provide valid keys for:
- `GROQ_API_KEY`
- `PINECONE_API_KEY`
- `COHERE_API_KEY`
- `JWT_SECRET_KEY` (generate with `openssl rand -hex 32`)
- `AGENT_PASSWORD_HASH` (run `python scripts/generate_agent_password.py`)
- `CORS_ALLOWED_ORIGINS` — your exact frontend origin(s). The agent WebSocket also checks the browser `Origin` against this list.
- `REDIS_URL` — a real Redis in production (`memory://` is dev-only and the app refuses to start with it when `APP_ENV=production`)

### 3. Database & Vector Store
If using the RAG features, ensure your Pinecone index matches the dimensions of your embedding model. 
Initialize the local SQLite database automatically by starting the server.

### 4. Running the Application
Start the FastAPI backend:
```bash
uvicorn app.main:app --reload --port 8000
```
*(The backend also serves the frontend static files at `http://localhost:8000/`)*

Alternatively, if running the frontend separately via a static server, ensure its port is added to `CORS_ALLOWED_ORIGINS` in your `.env`.

---

## Project Structure

```text
wrennon_1/
├── backend/
│   ├── app/
│   │   ├── api/            # REST API endpoints (Admin, Agent, Chat)
│   │   ├── auth/           # JWT Security and RBAC dependencies
│   │   ├── db/             # SQLAlchemy Models and CRUD operations
│   │   ├── graph/          # LangGraph Nodes & State Management (AI Logic)
│   │   ├── realtime/       # WebSocket routing and connection manager
│   │   ├── services/       # Mock APIs, LLM clients, Analytics
│   │   └── static/         # GENERATED mirror of frontend/ — never edit by hand
│   ├── data/               # Vector db storage / temporary files
│   └── tests/              # Pytest suite
└── frontend/               # UI source of truth (Widget, Agent, Admin). After editing run:
                            #   python scripts/sync_static.py   (CI fails if the mirror drifts)
```

## Deployment

The platform is designed to be easily deployed via Docker. 

**Docker / Render Deployment:**
The provided `Dockerfile` will install dependencies, run migrations/pre-deploy scripts (`pre_deploy.sh`), and start the production web server using `start.sh` with dynamically configured workers.

**Vercel Deployment:**
The `frontend/` directory can be deployed directly to Vercel as a static site. Ensure your `API_BASE` and `WS_BASE` variables in `widget.js` and `agent.js` point to your deployed backend URL.

## Security Notes

- **Auth:** agent sessions are an `httpOnly` cookie only — the JWT is never stored in or readable from page JS. Cookie-authenticated writes require the `X-Wrennon-Client` header (CSRF), and the agent WebSocket rejects foreign `Origin`s.
- **Roles:** `admin` > `manager` > `agent`. Only an `admin` can create, modify, delete or reset another `admin`; a `manager` can manage `agent` accounts only. Promote an account with `python scripts/set_agent_role.py <username> <role>`.
- **Passwords:** bcrypt-hashed (max 72 bytes). Password reset and logout revoke existing tokens (`token_version`).
- **2FA (TOTP):** failed codes count toward the login lockout, codes can't be replayed, and (re)enrolling requires the current password (plus a current code if 2FA is already on).
- **Internal notes:** visible only to agents; only the author (or an admin) can delete a note.
- **Privacy:** `GET/DELETE /api/admin/customer-data` export/erase a customer's conversations (matched by stored email or an email typed in chat; `dry_run=true` previews a delete). `scripts/purge_old_conversations.py` enforces retention — schedule it (e.g. a Render Cron Job). Sentry is configured to drop request bodies, cookies and chat log lines.
- **Customer-facing identity:** AI replies are labelled as the AI assistant; human replies show the agent's first name only.
