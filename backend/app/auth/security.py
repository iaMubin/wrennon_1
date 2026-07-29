"""
Password hashing and JWT token handling for agent login.

Why hash the password at all, for a small set of accounts: the hash
(not the plain password) lives in .env / the database. If either ever
leaks (committed by accident, server compromised), a hash can't be
reversed into the original password — a plaintext password sitting in
a config file could be, trivially, by anyone who reads it.
"""

from __future__ import annotations

import datetime
import bcrypt
import jwt
from jwt.exceptions import PyJWTError as JWTError

from app.config import settings


def hash_password(plain_password: str) -> str:
    password_bytes = plain_password.encode('utf-8')
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode('utf-8')
    try:
        hashed_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except (ValueError, TypeError):
        # Stored value isn't a valid bcrypt hash (e.g. AGENT_PASSWORD_HASH
        # was misconfigured with a plaintext value). Fail closed instead
        # of falling back to a plaintext `==` comparison — that fallback
        # would silently accept a misconfigured plaintext secret as a
        # valid password check, which is exactly the failure mode
        # hashing exists to prevent.
        return False


def create_access_token(subject: str, token_version: int) -> str:
    expire = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(
        minutes=settings.jwt_expire_minutes
    )
    payload = {"sub": subject, "exp": expire, "tv": token_version}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return {"sub": payload.get("sub"), "tv": payload.get("tv")}
    except JWTError:
        return None


def create_session_token(session_id: str) -> str:
    expire = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=72)
    payload = {"session_id": session_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_session_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return payload.get("session_id")
    except JWTError:
        return None