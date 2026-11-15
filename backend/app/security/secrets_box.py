"""Encryption at rest for per-tenant credentials (e.g. Shopify Admin API tokens).

Uses Fernet (AES-128-CBC + HMAC-SHA256). The key comes from TENANT_SECRETS_KEY
(``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``).
Without it, storing a tenant credential is refused rather than saved in clear text.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class SecretsUnavailable(RuntimeError):
    pass


def _fernet() -> Fernet:
    if not settings.tenant_secrets_key:
        raise SecretsUnavailable("TENANT_SECRETS_KEY is not configured; refusing to store or read tenant credentials.")
    return Fernet(settings.tenant_secrets_key.encode())


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise SecretsUnavailable("Stored tenant credential cannot be decrypted (wrong TENANT_SECRETS_KEY?)") from e
