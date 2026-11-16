"""At-rest protection for agents' 2FA (TOTP) secrets.

A TOTP secret is the second factor itself: anyone who can read the ``agents`` table (a leaked backup, a
read-only SQL injection, a curious DB admin) could generate valid codes and 2FA would protect nothing.
Secrets are therefore stored as ``enc:v1:<fernet token>`` whenever a key is configured
(SECRETS_ENCRYPTION_KEY). Legacy plaintext values keep working and are upgraded in place the next time the
agent authenticates (or in bulk with scripts/encrypt_totp_secrets.py).
"""

from __future__ import annotations

from app.logger import logger
from app.security import secrets_box

PREFIX = "enc:v1:"


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)


def read_secret(agent) -> str | None:
    """Plain TOTP secret for *agent*, or None when absent / undecryptable.
    Undecryptable (wrong or missing key) fails CLOSED: 2FA verification simply fails, it never falls back to
    accepting a login without the second factor."""
    value = agent.totp_secret
    if not value:
        return None
    if not is_encrypted(value):
        return value
    try:
        return secrets_box.decrypt(value[len(PREFIX):])
    except secrets_box.SecretsUnavailable as e:
        logger.error(f"Cannot decrypt 2FA secret for {agent.username}: {e}")
        return None


def write_secret(agent, plain: str) -> None:
    """Store *plain* encrypted (or, if no key is configured, as before, with a warning)."""
    if secrets_box.is_configured():
        agent.totp_secret = PREFIX + secrets_box.encrypt(plain)
    else:
        logger.warning("SECRETS_ENCRYPTION_KEY is not set: 2FA secrets are being stored UNENCRYPTED.")
        agent.totp_secret = plain


def upgrade_if_plaintext(agent) -> bool:
    """Encrypt a legacy plaintext secret in place (caller commits). True if it changed."""
    value = agent.totp_secret
    if value and not is_encrypted(value) and secrets_box.is_configured():
        agent.totp_secret = PREFIX + secrets_box.encrypt(value)
        return True
    return False
