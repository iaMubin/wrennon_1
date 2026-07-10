# """
# Password hashing and JWT token handling for agent login.

# Why hash the password at all, for a single hardcoded account: the hash
# (not the plain password) lives in .env and in this codebase. If the
# .env file ever leaks (committed by accident, server compromised), a
# hash can't be reversed into the original password — the plain password
# sitting in a config file could be, trivially, by anyone who reads it.
# """

# from __future__ import annotations

# import datetime

# from jose import JWTError, jwt
# from passlib.context import CryptContext

# from app.config import settings

# _pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# def hash_password(plain_password: str) -> str:
#     """Used once, offline, to generate the value that goes into
#     AGENT_PASSWORD_HASH in .env — see scripts/generate_agent_password.py."""
#     return _pwd_context.hash(plain_password)


# def verify_password(plain_password: str, hashed_password: str) -> bool:
#     return _pwd_context.verify(plain_password, hashed_password)


# def create_access_token(subject: str) -> str:
#     """subject is the agent's username. Encoded into a signed JWT that
#     proves, without hitting the database again, who this is and that
#     they logged in successfully within the last jwt_expire_minutes."""
#     expire = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(
#         minutes=settings.jwt_expire_minutes
#     )
#     payload = {"sub": subject, "exp": expire}
#     return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


# def decode_access_token(token: str) -> str | None:
#     """Returns the username if the token is valid and not expired,
#     otherwise None. Never raises — callers just treat None as
#     'not authenticated'."""
#     try:
#         payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
#         return payload.get("sub")
#     except JWTError:
#         return None


from __future__ import annotations

import datetime
import bcrypt
from jose import JWTError, jwt

from app.config import settings


def hash_password(plain_password: str) -> str:
    password_bytes = plain_password.encode('utf-8')
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    try:
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except ValueError:
        # If the stored 'hash' is invalid (e.g. user put plaintext in AGENT_PASSWORD_HASH by mistake)
        return plain_password == hashed_password


def create_access_token(subject: str, pwd_hash: str) -> str:
    expire = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(
        minutes=settings.jwt_expire_minutes
    )
    pwd_frag = pwd_hash[-10:] if pwd_hash else ""
    payload = {"sub": subject, "exp": expire, "pwd_frag": pwd_frag}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return {"sub": payload.get("sub"), "pwd_frag": payload.get("pwd_frag")}
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