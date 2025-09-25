from functools import lru_cache
from typing import Any

from pydantic import AnyUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _ensure_sqlalchemy_postgres_scheme(value: str) -> str:
    if value.startswith("postgresql+psycopg://") or value.startswith("postgresql+asyncpg://"):
        return value
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://") :]
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://") :]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    debug: bool = Field(False, description="Enable FastAPI debug mode")
    environment: str = Field(
        default="development",
        description="Runtime environment (development|staging|production)",
    )
    database_url: AnyUrl | str = Field(
        default="sqlite:///../data/predictbench.db",
        description="SQLAlchemy compatible database URL",
    )
    supabase_db_url: AnyUrl | str | None = Field(
        default=None,
        description="Supabase pooled Postgres connection string for production runs",
    )
    supabase_service_role_key: str | None = Field(
        default=None,
        description="Supabase service role key for privileged operations",
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
    target_close_window_days: int = Field(
        default=7,
        description="Number of days ahead to fetch closing markets for the daily pipeline",
        ge=0,
    )
    pipeline_run_time_utc: str = Field(
        default="07:00",
        description="Daily pipeline run time in HH:MM (24h) UTC",
    )
    processing_experiments: list[str] = Field(
        default_factory=lambda: [
            "pipelines.experiments.baseline:BaselineSnapshotExperiment",
        ],
        description="List of experiment classes to execute during processing",
    )

    @field_validator("pipeline_run_time_utc")
    @classmethod
    def _validate_pipeline_time(cls, value: str) -> str:
        if len(value) != 5 or value[2] != ":":
            raise ValueError("pipeline_run_time_utc must be formatted as HH:MM")
        hours, minutes = value.split(":", 1)
        if not (hours.isdigit() and minutes.isdigit()):
            raise ValueError("pipeline_run_time_utc must contain numeric hour and minute")
        hour_int = int(hours)
        minute_int = int(minutes)
        if not 0 <= hour_int < 24 or not 0 <= minute_int < 60:
            raise ValueError("pipeline_run_time_utc hour must be 0-23 and minute 0-59")
        return value

    @classmethod
    @field_validator("database_url", "supabase_db_url", mode="before")
    def _normalize_postgres_urls(cls, value: Any) -> Any:
        if value is None or not isinstance(value, str):
            return value

        if value.startswith("postgresql+psycopg://") or value.startswith(
            "postgresql+asyncpg://"
        ):
            return value

        normalized = value
        if normalized.startswith("postgres://"):
            normalized = "postgresql://" + normalized[len("postgres://") :]

        return normalized

    @classmethod
    @field_validator("supabase_db_url")
    def _require_postgres_scheme(cls, value: Any) -> Any:
        if value is None:
            return value
        url_str = str(value)
        scheme = url_str.split(":", 1)[0].lower()
        valid_schemes = {
            "postgres",
            "postgresql",
            "postgresql+psycopg",
            "postgresql+asyncpg",
        }
        if scheme not in valid_schemes:
            raise ValueError(
                "SUPABASE_DB_URL must be a PostgreSQL connection string (e.g. postgresql://...)."
            )
        return value

    @property
    def resolved_database_url(self) -> str:
        environment = self.environment.lower()
        if environment == "production":
            if not self.supabase_db_url:
                raise ValueError(
                    "SUPABASE_DB_URL must be set when ENVIRONMENT=production"
                )
            return _ensure_sqlalchemy_postgres_scheme(str(self.supabase_db_url))
        return _ensure_sqlalchemy_postgres_scheme(str(self.database_url))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
