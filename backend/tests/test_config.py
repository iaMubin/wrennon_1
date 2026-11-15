import pytest
from pydantic import ValidationError
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
        jwt_secret_key="a-long-random-production-secret-0123456789abcdef",
        database_url="postgresql://user:pass@host/db",
        redis_url="redis://localhost:6379",
        cors_allowed_origins="https://example.com"
    )
    assert settings.app_env == "production"
    assert settings.database_url == "postgresql://user:pass@host/db"


def test_production_rejects_short_jwt_secret():
    with pytest.raises(ValidationError):
        Settings(
            groq_api_key="test", cohere_api_key="test", pinecone_api_key="test", pinecone_host="test",
            app_env="production", _env_file=None, agent_password_hash="testhash",
            database_url="postgresql://user:pass@host/db", redis_url="redis://localhost:6379",
            cors_allowed_origins="https://example.com", jwt_secret_key="secure_key",
        )


def test_ws_query_token_default_depends_on_environment():
    base = dict(groq_api_key="t", cohere_api_key="t", pinecone_api_key="t", pinecone_host="t", _env_file=None, agent_password_hash="h")
    assert Settings(**base).allow_ws_query_token is True
    prod = Settings(**base, app_env="production", jwt_secret_key="x" * 40, database_url="postgresql://u:p@h/d", redis_url="redis://localhost:6379", cors_allowed_origins="https://e.com")
    assert prod.allow_ws_query_token is False
    assert Settings(**base, ws_allow_query_token=False).allow_ws_query_token is False
