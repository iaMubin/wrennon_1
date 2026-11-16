"""Encryption at rest for per-tenant credentials (e.g. Shopify Admin API tokens).

Uses Fernet (AES-128-CBC + HMAC-SHA256). The key comes from TENANT_SECRETS_KEY
(``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``).
Without it, storing a tenant credential is refused rather than saved in clear text.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import settings


class SecretsUnavailable(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(settings.tenant_secrets_key and settings.tenant_secrets_key.strip())


def _fernet() -> MultiFernet:
    if not is_configured():
        raise SecretsUnavailable("SECRETS_ENCRYPTION_KEY (or TENANT_SECRETS_KEY) is not configured; refusing to store or read secrets.")
    # Comma-separated keys = rotation: the first key encrypts, every key can decrypt.
    return MultiFernet([Fernet(k.strip().encode()) for k in settings.tenant_secrets_key.split(",") if k.strip()])


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise SecretsUnavailable("Stored tenant credential cannot be decrypted (wrong TENANT_SECRETS_KEY?)") from e
