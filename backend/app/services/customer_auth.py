"""
Storefront customer identity.

A customer signs in on the website (POST /api/store/auth/login) and gets a signed customer token. When the chat
widget starts a session it sends that token, and the backend stamps the *verified* email into the chat session
token. From then on the conversation is tied to that customer: the agent dashboard shows who they are and their
order history without anyone having to ask, and the bot can look up their orders without asking for an email.
The email is only ever taken from a token we signed, never from anything the browser types.
"""

from __future__ import annotations

import datetime
from typing import Optional

import jwt
from jwt.exceptions import PyJWTError

from app.auth.security import hash_password, verify_password
from app.config import settings

CUSTOMER_TOKEN_DAYS = 7
# Compared against when the email is unknown, so "no such account" and "wrong password" take the same time.
_DUMMY_HASH = hash_password("not-a-real-password")


def hash_pw(plain: str) -> str:
    return hash_password(plain)


def check_pw(plain: str, hashed: Optional[str]) -> bool:
    return verify_password(plain, hashed or _DUMMY_HASH) and bool(hashed)


def _exp(**delta) -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(**delta)


def issue_customer_token(email: str, name: str = "") -> str:
    payload = {"typ": "customer", "sub": email.lower(), "name": name, "exp": _exp(days=CUSTOMER_TOKEN_DAYS)}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def customer_email_from_header(authorization: Optional[str]) -> Optional[str]:
    """Verified customer email from an 'Authorization: Bearer <customer token>' header, else None."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        p = jwt.decode(authorization[7:].strip(), settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except PyJWTError:
        return None
    return str(p["sub"]).lower() if p.get("typ") == "customer" and p.get("sub") else None


def session_token_for_customer(session_id: str, authorization: Optional[str]) -> Optional[str]:
    """Chat session token carrying the verified customer email, or None for guests."""
    email = customer_email_from_header(authorization)
    if not email:
        return None
    payload = {"session_id": session_id, "customer_email": email, "exp": _exp(hours=72)}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def session_customer_email(session_token: Optional[str]) -> Optional[str]:
    """The verified customer email inside a chat session token (None for guests / bad tokens)."""
    if not session_token:
        return None
    try:
        p = jwt.decode(session_token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except PyJWTError:
        return None
    return p.get("customer_email")
