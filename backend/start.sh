#!/bin/bash
set -x

export WEB_CONCURRENCY=${WEB_CONCURRENCY:-2}

echo "==> Verifying app.main loads without errors..."
if ! python -c "import app.main"; then
    echo "ERROR: app.main failed to import! The traceback above is the root cause."
    exit 1
fi

echo "==> Starting Wrennon backend on port ${PORT:-8000} with ${WEB_CONCURRENCY} workers..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY}
