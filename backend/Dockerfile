FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cached layer — only re-runs when
# requirements.txt changes, not on every code change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend code
COPY . .

# Ingest policy docs into ChromaDB at build time so the vector store
# is ready when the container starts. If data/policy_docs/ is empty
# the script should handle that gracefully.
RUN python scripts/ingest.py

EXPOSE 8000

# $PORT is set by Render at runtime; default to 8000 for local Docker runs
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
