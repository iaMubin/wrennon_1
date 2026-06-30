#!/bin/bash

echo "==> Running policy doc ingestion..."
python scripts/ingest.py || echo "WARNING: Ingestion failed or skipped (this is OK if policy_docs/ is empty)"

echo "==> Starting Wrennon backend on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
