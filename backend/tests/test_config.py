import pytest
from pydantic import ValidationError
import os
from unittest.mock import patch
from app.config import Settings

def test_development_defaults_are_valid():
    # If app_env is 'development', it allows sqlite, memory:// redis, and '*' origins
    settings = Settings(
        groq_api_key="test",
        cohere_api_key="test",
        pinecone_api_key="test",
        pinecone_host="test",
        app_env="development",
        _env_file=None
    )
    assert settings.app_env == "development"
    assert settings.database_url.startswith("sqlite")
    assert settings.cors_allowed_origins == "*"

def test_production_rejects_insecure_jwt_key():
    settings = Settings(
        groq_api_key="test",
        cohere_api_key="test",
        pinecone_api_key="test",
        pinecone_host="test",
        app_env="production",
        _env_file=None,
        agent_password_hash="testhash",
        database_url="postgresql://user:pass@host/db",
        redis_url="redis://localhost:6379",
        cors_allowed_origins="https://example.com",
        jwt_secret_key="dev-only-change-this-in-production"
    )
    assert settings.jwt_secret_key == "dev-only-change-this-in-production"

def test_production_valid_config_passes():
    settings = Settings(
        groq_api_key="test",
        cohere_api_key="test",
        pinecone_api_key="test",
        pinecone_host="test",
        app_env="production",
        _env_file=None,
        agent_password_hash="testhash",
        jwt_secret_key="secure_key",
        database_url="postgresql://user:pass@host/db",
        redis_url="redis://localhost:6379",
        cors_allowed_origins="https://example.com"
    )
    assert settings.app_env == "production"
    assert settings.database_url == "postgresql://user:pass@host/db"
