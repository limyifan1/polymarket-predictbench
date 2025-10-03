from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ContractBase(BaseModel):
    contract_id: str
    market_id: str
    name: str
    outcome_type: str | None = None
    current_price: float | None = None
    confidence: float | None = None
    implied_probability: float | None = None

    @field_validator("current_price", "confidence", "implied_probability", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Any) -> float | None:
        if value is None:
            return None
        return float(value)


class Contract(ContractBase):
    raw_data: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class MarketBase(BaseModel):
    market_id: str
    slug: str | None = None
    question: str
    category: str | None = None
    sub_category: str | None = None
    open_time: datetime | None = None
    close_time: datetime | None = None
    volume_usd: float | None = None
    liquidity_usd: float | None = None
    fee_bps: int | None = None
    status: str
    archived: bool
    last_synced_at: datetime
    description: str | None = None
    icon_url: str | None = None

    @field_validator("volume_usd", "liquidity_usd", mode="before")
    @classmethod
    def _coerce_numeric(cls, value: Any) -> float | None:
        if value is None:
            return None
        return float(value)


class Event(BaseModel):
    event_id: str
    slug: str | None = None
    title: str | None = None
    description: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    icon_url: str | None = None
    series_slug: str | None = None
    series_title: str | None = None

    model_config = {"from_attributes": True}


class Market(MarketBase):
    contracts: list[Contract] = Field(default_factory=list)
    event: Event | None = None
    experiment_results: list["ForecastResult"] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class MarketList(BaseModel):
    total: int
    items: list[Market]


class EventWithMarkets(Event):
    markets: list[Market] = Field(default_factory=list)
    market_count: int
    research: list["ResearchArtifact"] = Field(default_factory=list)


class EventList(BaseModel):
    total: int
    items: list[EventWithMarkets]


class ExperimentDescriptor(BaseModel):
    experiment_name: str
    experiment_version: str
    variant_name: str
    variant_version: str
    stage: str


class ExperimentRunSummary(BaseModel):
    run_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None


class PipelineRunSummary(BaseModel):
    run_id: str
    run_date: date
    target_date: date
    window_days: int
    status: str
    environment: str | None = None


class ResearchArtifact(BaseModel):
    descriptor: ExperimentDescriptor
    run: ExperimentRunSummary
    pipeline_run: PipelineRunSummary | None = None
    artifact_id: str | None = None
    artifact_uri: str | None = None
    artifact_hash: str | None = None
    created_at: datetime
    updated_at: datetime
    payload: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class ForecastResult(BaseModel):
    descriptor: ExperimentDescriptor
    run: ExperimentRunSummary
    pipeline_run: PipelineRunSummary | None = None
    recorded_at: datetime
    score: float | None = None
    artifact_uri: str | None = None
    source_artifact_id: str | None = None
    payload: dict[str, Any] | None = None

    model_config = {"from_attributes": True}

    @field_validator("score", mode="before")
    @classmethod
    def _coerce_score(cls, value: Any) -> float | None:
        if value is None:
            return None
        return float(value)


class MarketStatusCount(BaseModel):
    status: str
    count: int


class ExperimentVariantSummary(BaseModel):
    stage: str
    experiment_name: str
    experiment_version: str
    variant_name: str
    variant_version: str
    output_count: int
    last_activity: datetime | None = None


class DatasetOverview(BaseModel):
    generated_at: datetime
    total_events: int
    events_with_research: int
    events_with_forecasts: int
    total_markets: int
    markets_with_forecasts: int
    market_status: list[MarketStatusCount]
    total_research_artifacts: int
    total_forecast_results: int
    research_variants: list[ExperimentVariantSummary]
    forecast_variants: list[ExperimentVariantSummary]
    latest_pipeline_run: PipelineRunSummary | None = None
    recent_pipeline_runs: list[PipelineRunSummary] = Field(default_factory=list)
