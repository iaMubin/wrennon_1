#!/bin/bash
set -e
set -x

export WEB_CONCURRENCY=${WEB_CONCURRENCY:-2}

echo "==> Running database migrations..."
alembic upgrade head

echo "==> Verifying app.main loads without errors..."
if ! python -c "import app.main"; then
    echo "ERROR: app.main failed to import! The traceback above is the root cause."
    exit 1
fi

echo "==> Starting Wrennon backend on port ${PORT:-8000} with ${WEB_CONCURRENCY} workers..."
# --ws-max-size: refuse WebSocket frames > 64 KiB at the protocol layer (default is
#   16 MiB). Chat text is capped at 2000 chars (re-checked by the app); uploads use HTTP.
# --proxy-headers/--forwarded-allow-ips: behind Render's load balancer the TCP peer is
#   the proxy, so without this EVERY client shares one IP and all per-IP limits (login
#   lockout, /chat/init, KB search, uploads, WS) collapse into one global bucket. Render's
#   port is only reachable through its proxy, so trusting its X-Forwarded-For is safe;
#   set FORWARDED_ALLOW_IPS to the proxy's address if you front this with something else.
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY} \
    --ws-max-size 65536 --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}"
