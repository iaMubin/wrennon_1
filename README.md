# Wrennon Customer Support Platform

An omnichannel, AI-first customer support platform built on a LangGraph state backbone. It seamlessly routes customer queries to an autonomous AI agent for immediate resolution, with real-time handoff to human agents when complex intervention is required.

## Key Features

- **Autonomous AI Resolution:** Uses LangGraph to orchestrate customer intent routing, policy retrieval (RAG via Pinecone + Cohere Rerank), and empathetic response generation (via Groq/Llama-3).
- **Seamless Human Handoff:** Real-time WebSockets ensure that when an AI reaches its limits, the conversation is instantly transferred to a live human agent without the customer experiencing dropped context.
- **Live Agent Dashboard:** A secure portal for agents to handle escalated tickets, view customer history and order details dynamically, communicate via internal notes, and manage SLAs.
- **Admin Control Panel:** Role-based access control (RBAC) allowing Admins to manage agent accounts, monitor performance, and enforce security policies.
- **Omnichannel Context:** Automatically parses messages for Order IDs and emails to retrieve and display context-rich customer data instantly to agents.
- **Multimedia Support:** Supports image uploads and parsing for enhanced issue diagnosis.

## Architecture Stack

- **Backend:** Python 3.12, FastAPI, WebSockets, SQLAlchemy (SQLite), LangChain / LangGraph.
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
- `JWT_SECRET` (You can generate one using `openssl rand -hex 32`)

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
wrennon-showcase/
├── backend/
│   ├── app/
│   │   ├── api/            # REST API endpoints (Admin, Agent, Chat)
│   │   ├── auth/           # JWT Security and RBAC dependencies
│   │   ├── db/             # SQLAlchemy Models and CRUD operations
│   │   ├── graph/          # LangGraph Nodes & State Management (AI Logic)
│   │   ├── realtime/       # WebSocket routing and connection manager
│   │   ├── services/       # Mock APIs, LLM clients, Analytics
│   │   └── static/         # Served frontend assets
│   ├── data/               # Vector db storage / temporary files
│   └── tests/              # Pytest suite
└── frontend/               # UI Source code (Widget, Agent, Admin dashboards)
```

## Deployment

The platform is designed to be easily deployed via Docker. 

**Docker / Render Deployment:**
The provided `Dockerfile` will install dependencies, run migrations/pre-deploy scripts (`pre_deploy.sh`), and start the production web server using `start.sh` with dynamically configured workers.

**Vercel Deployment:**
The `frontend/` directory can be deployed directly to Vercel as a static site. Ensure your `API_BASE` and `WS_BASE` variables in `widget.js` and `agent.js` point to your deployed backend URL.

## Security Notes

- **Internal Notes:** Agents can leave internal notes visible only to other agents. Strict backend enforcement prevents agents from deleting notes they do not own (unless they are an Admin).
- **Passwords:** Agent passwords are cryptographically hashed using `passlib` (bcrypt).
- **RBAC:** Only `admin` roles can manage accounts. Regular `manager` or `agent` accounts are restricted appropriately.
