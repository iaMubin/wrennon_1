#!/bin/bash
set -e

echo "==> Running policy doc ingestion..."
python scripts/ingest.py

echo "==> Starting Wrennon backend..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
