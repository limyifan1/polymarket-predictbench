from functools import lru_cache
from typing import Any

from pydantic import AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    debug: bool = Field(False, description="Enable FastAPI debug mode")
    database_url: AnyUrl | str = Field(
        default="sqlite:///../data/predictbench.db",
        description="SQLAlchemy compatible database URL",
    )
    polymarket_base_url: AnyUrl = Field(
        default="https://gamma-api.polymarket.com",
        description="Base URL for Polymarket API",
    )
    polymarket_markets_path: str = Field(
        default="/markets",
        description="Relative path for markets endpoint",
    )
    ingestion_page_size: int = Field(
        200, description="Number of markets to fetch per page"
    )
    ingestion_filters: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional query parameters applied when fetching Polymarket markets",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
