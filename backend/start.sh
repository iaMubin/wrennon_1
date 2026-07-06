#!/bin/bash

echo "==> Running policy doc ingestion..."
python scripts/ingest.py || echo "WARNING: Ingestion failed or skipped (this is OK if policy_docs/ is empty)"
echo "==> Running database migrations..."
alembic upgrade head

# Set default concurrency if not provided
export WEB_CONCURRENCY=${WEB_CONCURRENCY:-2}

echo "==> Starting Wrennon backend on port ${PORT:-8000} with ${WEB_CONCURRENCY} workers..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY}
