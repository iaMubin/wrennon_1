#!/usr/bin/env bash
# Run from the repo root AFTER applying wrennon-all-security-fixes.patch.
# Checks that every part of the patch is really in your working tree, then runs the test-suite.
set -u
ok=0; bad=0
chk() { if [ -e "$1" ]; then echo "  ok       $1"; ok=$((ok+1)); else echo "  MISSING  $1"; bad=$((bad+1)); fi; }
grepchk() { if grep -qE "$2" "$1" 2>/dev/null; then echo "  ok       $1  ($3)"; ok=$((ok+1)); else echo "  MISSING  $1  ($3)"; bad=$((bad+1)); fi; }

echo "== new files"
for f in backend/app/security/sanitize.py backend/app/security/pii.py backend/app/security/kb_guard.py \
         backend/app/security/secrets_box.py backend/app/db/tenancy.py backend/app/auth/access.py \
         backend/app/auth/sessions.py backend/app/services/uploads.py backend/app/services/ratelimit.py \
         backend/app/services/erasure.py backend/app/services/public_identity.py backend/app/api/uploads.py \
         backend/alembic/versions/a9e2c6d1b4f7_multi_tenancy_foundation.py \
         backend/tests/test_multi_tenancy.py backend/tests/test_security_hardening.py \
         backend/tests/test_store_hardening.py backend/scripts/create_tenant.py; do chk "$f"; done

echo "== key code markers"
grepchk backend/app/realtime/websocket_routes.py "_origin_allowed"            "WS Origin check (CSWSH)"
grepchk backend/app/realtime/websocket_routes.py "build_page_event_text"      "page_event allow-list"
grepchk backend/app/api/store.py                 "trk_fail"                   "order-tracking brute-force budget"
grepchk backend/app/api/store.py                 "cust_login_fail"            "customer login lockout"
grepchk backend/app/services/integrations/base.py "requires_verification = True" "order lookup fails closed"
grepchk backend/app/api/v1_public.py             "require_scope"              "API key scopes"
grepchk frontend/widget.js                       "wrennon.v1"                 "WS token not in URL"

ENVV="GROQ_API_KEY=x COHERE_API_KEY=x PINECONE_API_KEY=x PINECONE_HOST=x DATABASE_URL=sqlite:///./verify.db REDIS_URL=memory://local JWT_SECRET_KEY=verify-secret-verify-secret-verify-secret-1 AGENT_PASSWORD_HASH=x AGENT_USERNAME=verify PYTHONPATH=."

echo "== alembic: exactly one head?"
heads=$(cd backend && env $ENVV python -m alembic heads 2>/dev/null | grep -c "(head)")
echo "  heads: $heads (want 1)"
if [ "$heads" = "1" ]; then ok=$((ok+1)); else bad=$((bad+1)); fi

echo "== static mirror in sync?"
if python3 scripts/sync_static.py --check; then ok=$((ok+1)); else bad=$((bad+1)); fi

echo "== tests (needs: pip install -r backend/requirements.txt -r backend/requirements-dev.txt)"
(cd backend && rm -f verify.db && env $ENVV python -m pytest tests -q 2>&1 | tail -3 ; exit ${PIPESTATUS[0]}); rc=$?
rm -f backend/verify.db
if [ "$rc" = "0" ]; then ok=$((ok+1)); else bad=$((bad+1)); fi

echo; echo "checks ok: $ok   problems: $bad"
if [ "$bad" = "0" ]; then echo "ALL GOOD"; else echo "SOMETHING IS MISSING OR FAILING"; exit 1; fi
