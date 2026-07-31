"""
Centralized app settings, loaded once from environment variables / .env.

Nothing else in the codebase should call os.getenv directly — import
`settings` from here instead. Keeps config sourcing in one place when
this moves from local dev to a real deployment.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator


class Settings(BaseSettings):
    # LangSmith Tracing
    langchain_tracing_v2: bool = False
    langchain_api_key: str | None = None
    langchain_project: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # LLM
    openrouter_api_key: str | None = None
    groq_api_key: str
    openai_api_key: str | None = None
    cohere_api_key: str

    pinecone_api_key: str
    pinecone_host: str

    app_env: str = "development"
    cors_allowed_origins: str = "*"

    database_url: str = "sqlite:///./data/wrennon.db"
    redis_url: str = "redis://localhost:6379"

    # Global circuit breaker: total customer WS messages/minute across
    # ALL sessions and IPs combined. This exists specifically because the
    # per-session (15/min) and per-IP (60/min) limits below it are both
    # bypassable by a distributed attacker (many IPs, many sessions) —
    # no single-key Redis counter can stop that. This one can't identify
    # or block the attacker either, but it puts a hard ceiling on total
    # paid-LLM-call volume (cost/quota exposure) the app will ever allow
    # in a given minute, regardless of how the load is distributed.
    # Tune this to your actual Groq/Cohere/Pinecone paid-tier throughput.
    global_ws_message_limit_per_minute: int = 300

    # JWT settings for agent login. jwt_secret_key MUST be overridden in
    # .env for any real deployment — this default is fine for local dev
    # only, since anyone reading this source file could forge a token
    # otherwise.
    jwt_secret_key: str = "dev-only-change-this-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480  # 8-hour agent shift

    # Hardcoded single agent account, per Mubin's decision for this
    # build phase. Replace with a real Agent table + registration flow
    # before adding a second agent.
    agent_username: str = "mubin"
    agent_password_hash: str = ""  # set in .env — see generate_agent_password.py

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",")]

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.app_env not in ("development", "staging", "production"):
            raise ValueError("app_env must be one of: development, staging, production")

        if self.app_env == "production":
            if self.jwt_secret_key == "dev-only-change-this-in-production":  # nosec B105
                raise ValueError(
                    "JWT_SECRET_KEY is using the insecure development default in "
                    "production. Set a real, random JWT_SECRET_KEY before starting "
                    "the app in production — a warning here isn't enough, since "
                    "this key signs every agent session token."
                )
            if self.cors_allowed_origins.strip() == "*":
                raise ValueError(
                    "CORS_ALLOWED_ORIGINS is still the wildcard default in "
                    "production. Set it to your actual frontend origin(s) — "
                    "wildcard CORS in production also silently disables "
                    "credentialed requests (see main.py), which would break "
                    "cookie-based agent auth rather than just being insecure."
                )
            if self.database_url.startswith("sqlite"):
                raise ValueError(
                    "DATABASE_URL is still SQLite in production. Render's (and "
                    "most PaaS) filesystem is ephemeral, so every deploy/restart "
                    "would silently wipe all conversations/agents/audit logs with "
                    "no error at all. Set DATABASE_URL to your Postgres instance "
                    "before starting the app in production."
                )
        return self


settings = Settings()
