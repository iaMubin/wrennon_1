#!/bin/bash
set -x

echo "==> Running policy doc ingestion..."
if python scripts/ingest.py; then
    echo "Ingestion completed successfully."
else
    echo "WARNING: Ingestion failed or skipped (this is OK if policy_docs/ is empty)"
fi

echo "==> Running database migrations..."
alembic upgrade head
migration_status=$?
if [ $migration_status -ne 0 ]; then
    echo "ERROR: Database migration failed with status $migration_status"
    exit 1
fi

export WEB_CONCURRENCY=${WEB_CONCURRENCY:-2}

echo "==> Verifying app.main loads without errors..."
if ! python -c "import app.main"; then
    echo "ERROR: app.main failed to import! The traceback above is the root cause."
    exit 1
fi

echo "==> Starting Wrennon backend on port ${PORT:-8000} with ${WEB_CONCURRENCY} workers..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY}
