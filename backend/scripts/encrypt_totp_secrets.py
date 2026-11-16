"""Encrypt every legacy plaintext 2FA secret in the agents table (idempotent).

Needs SECRETS_ENCRYPTION_KEY (or TENANT_SECRETS_KEY) in the environment / backend/.env.

    python scripts/encrypt_totp_secrets.py            # report only
    python scripts/encrypt_totp_secrets.py --apply    # encrypt

Back up the database first. Keep the key safe: without it the encrypted secrets cannot be read and the
affected agents must re-enrol 2FA.
"""
import argparse
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.models import Agent  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.security import secrets_box  # noqa: E402
from app.security.totp_store import is_encrypted, upgrade_if_plaintext  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not secrets_box.is_configured():
        print("SECRETS_ENCRYPTION_KEY is not set; nothing can be encrypted.", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        agents = db.query(Agent).filter(Agent.totp_secret.isnot(None)).all()
        todo = [a for a in agents if not is_encrypted(a.totp_secret)]
        print(f"{len(agents)} agent(s) with 2FA, {len(todo)} still plaintext")
        if args.apply:
            for a in todo:
                upgrade_if_plaintext(a)
            db.commit()
            print(f"encrypted {len(todo)} secret(s)")
        elif todo:
            print("re-run with --apply to encrypt them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
