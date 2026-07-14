#!/bin/bash
set -x

echo "==> Running database migrations..."
alembic upgrade head
migration_status=$?
if [ $migration_status -ne 0 ]; then
    echo "ERROR: Database migration failed with status $migration_status"
    exit 1
fi

echo "==> Running policy doc ingestion..."
if python scripts/ingest.py; then
    echo "Ingestion completed successfully."
else
    echo "WARNING: Ingestion failed or skipped (this is OK if policy_docs/ is empty)"
fi

echo "==> Pre-deploy tasks completed successfully."
