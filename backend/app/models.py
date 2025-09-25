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


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Market(Base):
    __tablename__ = "markets"

    market_id: Mapped[str] = mapped_column(String, primary_key=True)
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
    price_snapshots: Mapped[list["PriceSnapshot"]] = relationship(
        "PriceSnapshot", back_populates="market", cascade="all, delete-orphan"
    )


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


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    snapshot_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(String, ForeignKey("markets.market_id"), nullable=False)
    contract_id: Mapped[str] = mapped_column(String, ForeignKey("contracts.contract_id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)

    market: Mapped[Market] = relationship("Market", back_populates="price_snapshots")
    contract: Mapped[Contract] = relationship("Contract")

    __table_args__ = (UniqueConstraint("market_id", "contract_id", "timestamp", name="uq_snapshot"),)


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


class ProcessedMarket(Base):
    __tablename__ = "processed_markets"

    processed_market_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("processing_runs.run_id"), nullable=False)
    market_id: Mapped[str] = mapped_column(String, nullable=False)
    market_slug: Mapped[str | None] = mapped_column(String, nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    run: Mapped[ProcessingRun] = relationship("ProcessingRun", back_populates="markets")
    contracts: Mapped[list["ProcessedContract"]] = relationship(
        "ProcessedContract", back_populates="processed_market", cascade="all, delete-orphan"
    )
    experiment_results: Mapped[list["ExperimentResultRecord"]] = relationship(
        "ExperimentResultRecord", back_populates="processed_market", cascade="all, delete-orphan"
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


class ExperimentResultRecord(Base):
    __tablename__ = "experiment_results"

    experiment_result_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_run_id: Mapped[str] = mapped_column(
        String, ForeignKey("experiment_runs.experiment_run_id"), nullable=False
    )
    processed_market_id: Mapped[str] = mapped_column(
        String, ForeignKey("processed_markets.processed_market_id"), nullable=False
    )
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    score: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    artifact_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    experiment_run: Mapped[ExperimentRunRecord] = relationship(
        "ExperimentRunRecord", back_populates="results"
    )
    processed_market: Mapped[ProcessedMarket] = relationship(
        "ProcessedMarket", back_populates="experiment_results"
    )

    __table_args__ = (
        UniqueConstraint(
            "experiment_run_id",
            "processed_market_id",
            name="uq_experiment_result_scope",
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
