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
    with pytest.raises(ValidationError):
        Settings(
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

def test_production_rejects_sqlite_database_url():
    # Render's (and most PaaS) filesystem is ephemeral — SQLite in
    # production would silently lose all data on every deploy/restart,
    # with no error anywhere. This must fail startup, the same way the
    # insecure-JWT-key and wildcard-CORS cases already do.
    with pytest.raises(ValidationError):
        Settings(
            groq_api_key="test",
            cohere_api_key="test",
            pinecone_api_key="test",
            pinecone_host="test",
            app_env="production",
            _env_file=None,
            agent_password_hash="testhash",
            database_url="sqlite:///./data/wrennon.db",
            redis_url="redis://localhost:6379",
            cors_allowed_origins="https://example.com",
            jwt_secret_key="secure_key",
        )

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
