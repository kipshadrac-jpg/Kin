"""All configuration comes from environment variables (see backend/.env.example)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = Field(default="Kin", alias="APP_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")  # development | production | test
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Database. DATABASE_URL is the restricted kin_api login (no BYPASSRLS).
    database_url: str = Field(alias="DATABASE_URL")
    # Admin URL is used ONLY by the bootstrap/migration command, never by the API.
    database_admin_url: str | None = Field(default=None, alias="DATABASE_ADMIN_URL")
    worker_database_url: str | None = Field(default=None, alias="WORKER_DATABASE_URL")
    kin_api_db_password: str | None = Field(default=None, alias="KIN_API_DB_PASSWORD")
    kin_worker_db_password: str | None = Field(default=None, alias="KIN_WORKER_DB_PASSWORD")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # Auth (Supabase GoTrue)
    supabase_jwt_secret: str | None = Field(default=None, alias="SUPABASE_JWT_SECRET")
    supabase_jwks_url: str | None = Field(default=None, alias="SUPABASE_JWKS_URL")
    supabase_jwt_audience: str = Field(default="authenticated", alias="SUPABASE_JWT_AUDIENCE")
    gotrue_url: str = Field(default="http://auth:9999", alias="GOTRUE_URL")

    # LLM + embeddings
    llm_provider: str = Field(default="anthropic", alias="LLM_PROVIDER")  # anthropic | ollama | fake
    llm_model: str = Field(default="claude-opus-5-5", alias="LLM_MODEL")
    llm_refusal_fallback: str = Field(default="default", alias="LLM_REFUSAL_FALLBACK")  # "default" | "off"
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    ollama_url: str = Field(default="http://localhost:11434", alias="OLLAMA_URL")
    local_llm_model: str = Field(default="llama3.2", alias="LOCAL_LLM_MODEL")

    embedding_provider: str = Field(default="hashing", alias="EMBEDDING_PROVIDER")  # openai | hashing | ollama | fake
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    embedding_dimensions: int = Field(default=1536, alias="EMBEDDING_DIMENSIONS")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")

    # HTTP
    cors_origins: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")

    # Region-specific free support services, used for finance referral (optional).
    safety_resources_path: str = Field(default="app/safety/resources.yaml", alias="SAFETY_RESOURCES_PATH")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
