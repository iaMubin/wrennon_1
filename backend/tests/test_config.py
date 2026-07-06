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
    with pytest.raises(ValidationError) as excinfo:
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
    assert "JWT_SECRET_KEY must be overridden" in str(excinfo.value)

def test_production_rejects_sqlite():
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            groq_api_key="test",
            cohere_api_key="test",
            pinecone_api_key="test",
            pinecone_host="test",
            app_env="production",
            _env_file=None,
            agent_password_hash="testhash",
            jwt_secret_key="secure_key",
            redis_url="redis://localhost:6379",
            cors_allowed_origins="https://example.com",
            database_url="sqlite:///./data/wrennon.db"
        )
    assert "DATABASE_URL cannot use sqlite in production" in str(excinfo.value)

def test_production_rejects_memory_redis():
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            groq_api_key="test",
            cohere_api_key="test",
            pinecone_api_key="test",
            pinecone_host="test",
            app_env="production",
            _env_file=None,
            agent_password_hash="testhash",
            jwt_secret_key="secure_key",
            database_url="postgresql://user:pass@host/db",
            cors_allowed_origins="https://example.com",
            redis_url="memory://"
        )
    assert "REDIS_URL cannot use memory backend in production" in str(excinfo.value)

def test_production_rejects_wildcard_cors():
    with pytest.raises(ValidationError) as excinfo:
        Settings(
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
            cors_allowed_origins="*"
        )
    assert "CORS_ALLOWED_ORIGINS cannot contain '*' wildcard in production" in str(excinfo.value)

def test_production_rejects_empty_password_hash():
    with pytest.raises(ValidationError) as excinfo:
        Settings(
            groq_api_key="test",
            cohere_api_key="test",
            pinecone_api_key="test",
            pinecone_host="test",
            app_env="production",
            _env_file=None,
            agent_password_hash="",
            jwt_secret_key="secure_key",
            database_url="postgresql://user:pass@host/db",
            redis_url="redis://localhost:6379",
            cors_allowed_origins="https://example.com"
        )
    assert "AGENT_PASSWORD_HASH must be set in production" in str(excinfo.value)

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
