from functools import lru_cache
from typing import List
from pydantic import Field
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
