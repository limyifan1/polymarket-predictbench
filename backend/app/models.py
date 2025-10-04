from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class MarketStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    RESOLVED = "resolved"


class ExperimentStage(str, Enum):
    RESEARCH = "research"
    FORECAST = "forecast"
    POSTHOC = "posthoc"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Market(Base):
    __tablename__ = "markets"

    market_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str | None] = mapped_column(String, ForeignKey("events.event_id"), nullable=True)
    slug: Mapped[str | None] = mapped_column(String, nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    sub_category: Mapped[str | None] = mapped_column(String, nullable=True)
    open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    volume_usd: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    liquidity_usd: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    fee_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default=MarketStatus.OPEN.value)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon_url: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    contracts: Mapped[list["Contract"]] = relationship(
        "Contract", back_populates="market", cascade="all, delete-orphan"
    )
    event: Mapped[Event | None] = relationship("Event", back_populates="markets")


class Contract(Base):
    __tablename__ = "contracts"

    contract_id: Mapped[str] = mapped_column(String, primary_key=True)
    market_id: Mapped[str] = mapped_column(String, ForeignKey("markets.market_id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    outcome_type: Mapped[str | None] = mapped_column(String, nullable=True)
    current_price: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    implied_probability: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    market: Mapped[Market] = relationship("Market", back_populates="contracts")


class Event(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    slug: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    icon_url: Mapped[str | None] = mapped_column(String, nullable=True)
    series_slug: Mapped[str | None] = mapped_column(String, nullable=True)
    series_title: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    markets: Mapped[list[Market]] = relationship(
        "Market", back_populates="event", cascade="all, delete-orphan"
    )


class ProcessingRun(Base):
    __tablename__ = "processing_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    total_markets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_markets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_markets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    git_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    environment: Mapped[str | None] = mapped_column(String, nullable=True)

    markets: Mapped[list["ProcessedMarket"]] = relationship(
        "ProcessedMarket", back_populates="run", cascade="all, delete-orphan"
    )
    experiment_runs: Mapped[list["ExperimentRunRecord"]] = relationship(
        "ExperimentRunRecord", back_populates="processing_run", cascade="all, delete-orphan"
    )
    failures: Mapped[list["ProcessingFailure"]] = relationship(
        "ProcessingFailure", back_populates="processing_run", cascade="all, delete-orphan"
    )
    events: Mapped[list["ProcessedEvent"]] = relationship(
        "ProcessedEvent", back_populates="run", cascade="all, delete-orphan"
    )
    research_runs: Mapped[list["ResearchRunRecord"]] = relationship(
        "ResearchRunRecord", back_populates="processing_run", cascade="all, delete-orphan"
    )


class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    processed_event_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("processing_runs.run_id"), nullable=False)
    event_key: Mapped[str | None] = mapped_column(String, nullable=True)
    event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    event_slug: Mapped[str | None] = mapped_column(String, nullable=True)
    event_title: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    run: Mapped[ProcessingRun] = relationship("ProcessingRun", back_populates="events")
    markets: Mapped[list[ProcessedMarket]] = relationship(
        "ProcessedMarket", back_populates="processed_event", cascade="all, delete-orphan"
    )
    experiment_results: Mapped[list["ExperimentResultRecord"]] = relationship(
        "ExperimentResultRecord", back_populates="processed_event", cascade="all, delete-orphan"
    )
    research_artifacts: Mapped[list["ResearchArtifactRecord"]] = relationship(
        "ResearchArtifactRecord", back_populates="processed_event", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("run_id", "event_id", name="uq_processed_event_scope"),
        UniqueConstraint("event_key", name="uq_processed_event_key"),
    )


class ProcessedMarket(Base):
    __tablename__ = "processed_markets"

    processed_market_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("processing_runs.run_id"), nullable=False)
    processed_event_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("processed_events.processed_event_id"), nullable=True
    )
    market_id: Mapped[str] = mapped_column(String, nullable=False)
    market_slug: Mapped[str | None] = mapped_column(String, nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    run: Mapped[ProcessingRun] = relationship("ProcessingRun", back_populates="markets")
    processed_event: Mapped[ProcessedEvent | None] = relationship(
        "ProcessedEvent", back_populates="markets"
    )
    contracts: Mapped[list["ProcessedContract"]] = relationship(
        "ProcessedContract", back_populates="processed_market", cascade="all, delete-orphan"
    )
    experiment_results: Mapped[list["ExperimentResultRecord"]] = relationship(
        "ExperimentResultRecord", back_populates="processed_market", cascade="all, delete-orphan"
    )
    research_artifacts: Mapped[list["ResearchArtifactRecord"]] = relationship(
        "ResearchArtifactRecord", back_populates="processed_market", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("run_id", "market_id", name="uq_processed_market_scope"),
    )


class ProcessedContract(Base):
    __tablename__ = "processed_contracts"

    processed_contract_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    processed_market_id: Mapped[str] = mapped_column(
        String, ForeignKey("processed_markets.processed_market_id"), nullable=False
    )
    contract_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    price: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    processed_market: Mapped[ProcessedMarket] = relationship(
        "ProcessedMarket", back_populates="contracts"
    )

    __table_args__ = (
        UniqueConstraint("processed_market_id", "contract_id", name="uq_processed_contract_scope"),
    )


class ExperimentDefinition(Base):
    __tablename__ = "experiments"

    experiment_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_experiment_definition"),
    )

    runs: Mapped[list["ExperimentRunRecord"]] = relationship(
        "ExperimentRunRecord", back_populates="experiment", cascade="all, delete-orphan"
    )


class ExperimentRunRecord(Base):
    __tablename__ = "experiment_runs"

    experiment_run_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("processing_runs.run_id"), nullable=False)
    experiment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("experiments.experiment_id"), nullable=False
    )
    stage: Mapped[str] = mapped_column(
        String, nullable=False, default=ExperimentStage.FORECAST.value
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    processing_run: Mapped[ProcessingRun] = relationship(
        "ProcessingRun", back_populates="experiment_runs"
    )
    experiment: Mapped[ExperimentDefinition] = relationship(
        "ExperimentDefinition", back_populates="runs"
    )
    results: Mapped[list["ExperimentResultRecord"]] = relationship(
        "ExperimentResultRecord", back_populates="experiment_run", cascade="all, delete-orphan"
    )
    __table_args__ = (
        UniqueConstraint("run_id", "experiment_id", name="uq_experiment_run_scope"),
    )


class ResearchRunRecord(Base):
    __tablename__ = "research_runs"

    research_run_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("processing_runs.run_id"), nullable=False
    )
    suite_id: Mapped[str] = mapped_column(String, nullable=False)
    experiment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("experiments.experiment_id"), nullable=False
    )
    strategy_name: Mapped[str] = mapped_column(String, nullable=False)
    strategy_version: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    processing_run: Mapped[ProcessingRun] = relationship(
        "ProcessingRun", back_populates="research_runs"
    )
    experiment: Mapped[ExperimentDefinition] = relationship("ExperimentDefinition")
    artifacts: Mapped[list["ResearchArtifactRecord"]] = relationship(
        "ResearchArtifactRecord", back_populates="research_run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id", "suite_id", "strategy_name", "strategy_version", name="uq_research_run_scope"
        ),
    )


class ResearchArtifactRecord(Base):
    __tablename__ = "research_artifacts"

    artifact_id: Mapped[str] = mapped_column(String, primary_key=True)
    experiment_run_id: Mapped[str] = mapped_column(
        String, ForeignKey("experiment_runs.experiment_run_id"), nullable=False
    )
    research_run_id: Mapped[str] = mapped_column(
        String, ForeignKey("research_runs.research_run_id"), nullable=False
    )
    processed_market_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("processed_markets.processed_market_id"), nullable=True
    )
    processed_event_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("processed_events.processed_event_id"), nullable=True
    )
    variant_name: Mapped[str] = mapped_column(String, nullable=False)
    variant_version: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    artifact_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    artifact_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    experiment_run: Mapped[ExperimentRunRecord] = relationship("ExperimentRunRecord")
    research_run: Mapped[ResearchRunRecord] = relationship(
        "ResearchRunRecord", back_populates="artifacts"
    )
    processed_market: Mapped[ProcessedMarket | None] = relationship(
        "ProcessedMarket", back_populates="research_artifacts"
    )
    processed_event: Mapped[ProcessedEvent | None] = relationship(
        "ProcessedEvent", back_populates="research_artifacts"
    )
    forecast_links: Mapped[list["ForecastResearchLink"]] = relationship(
        "ForecastResearchLink", back_populates="artifact", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "research_run_id",
            "processed_market_id",
            "artifact_hash",
            name="uq_research_artifact_hash"
        ),
    )




class ExperimentResultRecord(Base):
    __tablename__ = "experiment_results"

    experiment_result_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_run_id: Mapped[str] = mapped_column(
        String, ForeignKey("experiment_runs.experiment_run_id"), nullable=False
    )
    processed_market_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("processed_markets.processed_market_id"), nullable=True
    )
    processed_event_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("processed_events.processed_event_id"), nullable=True
    )
    stage: Mapped[str] = mapped_column(
        String, nullable=False, default=ExperimentStage.FORECAST.value
    )
    variant_name: Mapped[str | None] = mapped_column(String, nullable=True)
    variant_version: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    score: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    artifact_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    experiment_run: Mapped[ExperimentRunRecord] = relationship(
        "ExperimentRunRecord", back_populates="results"
    )
    processed_market: Mapped[ProcessedMarket | None] = relationship(
        "ProcessedMarket", back_populates="experiment_results"
    )
    processed_event: Mapped[ProcessedEvent | None] = relationship(
        "ProcessedEvent", back_populates="experiment_results"
    )
    research_links: Mapped[list["ForecastResearchLink"]] = relationship(
        "ForecastResearchLink", back_populates="experiment_result", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "experiment_run_id",
            "processed_event_id",
            "processed_market_id",
            name="uq_experiment_result_scope",
        ),
    )


class ForecastResearchLink(Base):
    __tablename__ = "forecast_research_links"

    link_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_result_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("experiment_results.experiment_result_id"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(
        String, ForeignKey("research_artifacts.artifact_id"), nullable=False
    )
    dependency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    experiment_result: Mapped[ExperimentResultRecord] = relationship(
        "ExperimentResultRecord", back_populates="research_links"
    )
    artifact: Mapped[ResearchArtifactRecord] = relationship(
        "ResearchArtifactRecord", back_populates="forecast_links"
    )

    __table_args__ = (
        UniqueConstraint(
            "experiment_result_id",
            "artifact_id",
            "dependency_key",
            name="uq_forecast_research_dependency",
        ),
    )


class ProcessingFailure(Base):
    __tablename__ = "processing_failures"

    failure_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("processing_runs.run_id"), nullable=False)
    market_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    retriable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    processing_run: Mapped[ProcessingRun] = relationship(
        "ProcessingRun", back_populates="failures"
    )
