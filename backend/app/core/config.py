from functools import lru_cache
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "TraceMind API"
    APP_VERSION: str = "0.2.3a"
    ENVIRONMENT: str = Field(default="development", description="Runtime environment: development, staging, production")
    DEBUG: bool = Field(default=False, description="Enable debug mode")
    API_V1_PREFIX: str = "/api/v1"

    # PostgreSQL Database URL (Defaults to local Docker compose Postgres)
    DATABASE_URL: str = Field(
        default="postgresql+psycopg2://tracemind:tracemind_secret@localhost:5432/tracemind_db",
        description="SQLAlchemy database connection URL"
    )
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+psycopg2://", 1)
        return v

    # CORS configuration for frontend dev servers
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # Telemetry and Demo data configuration
    DEMO_MODE: bool = Field(default=True, description="Enable deterministic simulated telemetry providers")
    DEFAULT_PROJECT_SLUG: str = "core-ecommerce"

    # Google Gemini AI Provider Configuration
    GEMINI_API_KEY: Optional[str] = Field(default=None, description="Google Gemini API key for incident investigation")
    GEMINI_MODEL: str = Field(default="gemini-2.5-flash", description="Stable Gemini model for root-cause synthesis")
    GEMINI_TIMEOUT_SECONDS: int = Field(default=25, description="Timeout in seconds for Gemini API investigation requests")
    INVESTIGATION_PROMPT_VERSION: str = "v1.0"
    INVESTIGATION_SCHEMA_VERSION: str = "v1.0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
