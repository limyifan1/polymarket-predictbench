from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
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


class Experiment(Base):
    __tablename__ = "experiments"

    experiment_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_provider: Mapped[str] = mapped_column(String, nullable=False)
    hyperparameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    runs: Mapped[list["ExperimentRun"]] = relationship(
        "ExperimentRun", back_populates="experiment", cascade="all, delete-orphan"
    )


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[int] = mapped_column(Integer, ForeignKey("experiments.experiment_id"), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    prompt_template_version: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")

    experiment: Mapped[Experiment] = relationship("Experiment", back_populates="runs")
    predictions: Mapped[list["Prediction"]] = relationship(
        "Prediction", back_populates="run", cascade="all, delete-orphan"
    )
    metrics: Mapped[list["EvaluationMetric"]] = relationship(
        "EvaluationMetric", back_populates="run", cascade="all, delete-orphan"
    )


class Prediction(Base):
    __tablename__ = "predictions"

    prediction_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("experiment_runs.run_id"), nullable=False)
    market_id: Mapped[str] = mapped_column(String, ForeignKey("markets.market_id"), nullable=False)
    contract_id: Mapped[str | None] = mapped_column(String, ForeignKey("contracts.contract_id"), nullable=True)
    prediction_probability: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    run: Mapped[ExperimentRun] = relationship("ExperimentRun", back_populates="predictions")
    market: Mapped[Market] = relationship("Market")
    contract: Mapped["Contract"] = relationship("Contract")

    __table_args__ = (
        UniqueConstraint("run_id", "market_id", "contract_id", name="uq_prediction_scope"),
    )


class EvaluationMetric(Base):
    __tablename__ = "evaluation_metrics"

    metric_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("experiment_runs.run_id"), nullable=False)
    market_id: Mapped[str | None] = mapped_column(String, ForeignKey("markets.market_id"), nullable=True)
    metric_name: Mapped[str] = mapped_column(String, nullable=False)
    metric_value: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    run: Mapped[ExperimentRun] = relationship("ExperimentRun", back_populates="metrics")
