from functools import lru_cache
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pydantic import AnyUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _ensure_sqlalchemy_postgres_scheme(value: str) -> str:
    if not value.lower().startswith("postgres"):
        return value

    parsed = urlparse(value)
    scheme = parsed.scheme.lower()

    if scheme == "postgres":
        scheme = "postgresql"

    if scheme == "postgresql":
        scheme = "postgresql+psycopg"

    if scheme not in {"postgresql+psycopg", "postgresql+asyncpg"}:
        scheme = "postgresql+psycopg"

    query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_params.setdefault("sslmode", "require")
    query_params.setdefault("target_session_attrs", "read-write")
    new_query = urlencode(query_params, doseq=True)

    normalized = urlunparse(
        parsed._replace(
            scheme=scheme,
            query=new_query,
        )
    )
    return normalized


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
    pipeline_debug_dump_dir: str | None = Field(
        default="../debug_dumps",
        description="Default directory where pipeline debug dumps are written (set blank to disable)",
    )
    pipeline_event_batch_size: int = Field(
        default=10,
        description="Number of event groups processed concurrently during the daily pipeline",
        ge=1,
    )
    pipeline_db_retry_attempts: int = Field(
        default=3,
        description="Number of attempts to retry pipeline database writes when transient errors occur",
        ge=1,
    )
    pipeline_db_retry_backoff_seconds: list[float] | tuple[float, ...] | str = Field(
        default_factory=lambda: [1.0, 2.0, 4.0],
        description="Comma-separated list or array of backoff delays (seconds) between database retry attempts",
    )
    llm_default_provider: str = Field(
        default="openai",
        description="Fallback provider used when strategies do not override the provider name",
    )
    openai_api_key: str | None = Field(
        default=None,
        description="API key used for OpenAI-powered research and forecasting",
    )
    openai_api_base: AnyUrl | str | None = Field(
        default=None,
        description="Optional override for the OpenAI API base URL (Azure/proxy support)",
    )
    openai_org_id: str | None = Field(
        default=None,
        description="Optional OpenAI organization identifier",
    )
    openai_project_id: str | None = Field(
        default=None,
        description="Optional OpenAI project identifier for usage scoping",
    )
    gemini_api_key: str | None = Field(
        default=None,
        description="API key used for Gemini-powered research and forecasting",
    )
    gemini_additional_api_keys: list[str] | str = Field(
        default_factory=list,
        description=(
            "Optional fallback Gemini API keys; the provider will cycle through them "
            "if the primary key is rate-limited or fails."
        ),
    )
    experiment_overrides: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-experiment overrides keyed by experiment name",
    )

    def experiment_config(self, experiment_name: str) -> dict[str, Any]:
        base = dict(self.experiment_overrides.get("__default__", {}))
        specific = self.experiment_overrides.get(experiment_name, {})
        if specific:
            base.update(specific)
        return base

    @field_validator("pipeline_run_time_utc")
    @classmethod
    def _validate_pipeline_time(cls, value: str) -> str:
        if len(value) != 5 or value[2] != ":":
            raise ValueError("pipeline_run_time_utc must be formatted as HH:MM")
        hours, minutes = value.split(":", 1)
        if not (hours.isdigit() and minutes.isdigit()):
            raise ValueError(
                "pipeline_run_time_utc must contain numeric hour and minute"
            )
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

    @field_validator("gemini_additional_api_keys", mode="after")
    @classmethod
    def _parse_additional_gemini_keys(cls, value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                return []
            return [
                item for item in (part.strip() for part in candidate.split(",")) if item
            ]
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        raise ValueError(
            "GEMINI_ADDITIONAL_API_KEYS must be provided as a list or comma-separated string"
        )

    @field_validator("pipeline_db_retry_backoff_seconds", mode="before")
    @classmethod
    def _parse_retry_backoff(cls, value: Any) -> list[float]:
        if value in (None, "", []):
            return [1.0, 2.0, 4.0]
        if isinstance(value, str):
            tokens = [token.strip() for token in value.split(",") if token.strip()]
            if not tokens:
                raise ValueError("PIPELINE_DB_RETRY_BACKOFF_SECONDS must contain at least one value")
            value = tokens
        if isinstance(value, (list, tuple)):
            backoff: list[float] = []
            for item in value:
                try:
                    delay = float(item)
                except (TypeError, ValueError) as exc:
                    raise ValueError("PIPELINE_DB_RETRY_BACKOFF_SECONDS entries must be numeric") from exc
                if delay <= 0:
                    raise ValueError("PIPELINE_DB_RETRY_BACKOFF_SECONDS entries must be positive")
                backoff.append(delay)
            if not backoff:
                raise ValueError("PIPELINE_DB_RETRY_BACKOFF_SECONDS must contain at least one value")
            return backoff
        raise ValueError(
            "PIPELINE_DB_RETRY_BACKOFF_SECONDS must be provided as a comma-separated string or list of numbers"
        )

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

    @property
    def pipeline_db_retry_backoff_schedule(self) -> tuple[float, ...]:
        sequence = tuple(float(value) for value in self.pipeline_db_retry_backoff_seconds)
        if not sequence:
            return (1.0,)
        return sequence


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
