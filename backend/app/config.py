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
    groq_api_key: str
    openai_api_key: str | None = None
    cohere_api_key: str

    pinecone_api_key: str
    pinecone_host: str

    app_env: str = "development"
    cors_allowed_origins: str = "*"

    database_url: str = "sqlite:///./data/wrennon.db"
    redis_url: str = "redis://localhost:6379"

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
        if self.app_env != "development":
            if self.jwt_secret_key == "dev-only-change-this-in-production":
                raise ValueError(
                    "JWT_SECRET_KEY must be overridden in non-development environments! "
                    "Current value is the insecure default."
                )
        return self


settings = Settings()
