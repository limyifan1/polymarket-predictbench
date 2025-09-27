from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, ContextManager, FrozenSet, Iterable, Mapping, Sequence
from uuid import uuid4

from loguru import logger

from app.core.config import Settings, get_settings
from app.db import init_db
from app.repositories.pipeline_models import (
    ExperimentResultInput,
    ExperimentRunInput,
    ProcessedContractInput,
    ProcessedEventInput,
    ProcessedMarketInput,
    ResearchArtifactInput,
)
from app.repositories import MarketRepository, ProcessingRepository
from app.domain import NormalizedEvent, NormalizedMarket
from ingestion.client import PolymarketClient
from ingestion.normalize import normalize_market
from ingestion.service import session_scope

from .context import PipelineContext
from app.models import ExperimentStage

from .experiments.base import (
    EventMarketGroup,
    ExperimentExecutionError,
    ExperimentSkip,
    ForecastOutput,
    ResearchOutput,
    ResearchStrategy,
    ForecastStrategy,
)
from .experiments.manifest import build_manifest
from .experiments.registry import load_suites
from .experiments.suites import BaseExperimentSuite


@dataclass(slots=True)
class ExperimentRunMeta:
    suite_id: str
    stage: ExperimentStage
    strategy_name: str
    strategy_version: str
    experiment_name: str
    description: str | None
    strategy: ResearchStrategy | ForecastStrategy
    run_identifier: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    status: str = "running"
    error_messages: list[str] = field(default_factory=list)
    success_count: int = 0
    skip_count: int = 0
    failure_count: int = 0

    def mark_failed(self, message: str) -> None:
        self.status = "failed"
        self.error_messages.append(message)
        self.failure_count += 1

    def mark_completed(self) -> None:
        if self.status == "running":
            self.status = "completed"

    def mark_skipped(self, message: str | None = None) -> None:
        self.skip_count += 1
        if self.status == "failed":
            return
        if self.success_count > 0:
            if message and message not in self.error_messages:
                self.error_messages.append(message)
            return
        if self.status != "skipped":
            self.status = "skipped"
        if message and message not in self.error_messages:
            self.error_messages.append(message)

    def record_success(self) -> None:
        if self.status == "failed":
            return
        if self.status == "skipped":
            self.status = "running"
        self.success_count += 1


@dataclass(slots=True)
class ResearchExecutionRecord:
    meta: ExperimentRunMeta
    output: ResearchOutput
    artifact_id: str | None = None
    bundle_identity: str | None = None


@dataclass(slots=True)
class ForecastExecutionRecord:
    meta: ExperimentRunMeta
    output: ForecastOutput
    dependencies: tuple[str, ...]
    source_artifact_ids: dict[str, str | None] | None = None


@dataclass(slots=True)
class ResearchBundleMember:
    suite_id: str
    strategy_name: str
    strategy: ResearchStrategy
    meta: ExperimentRunMeta
    experiment_name: str
    config_fingerprint: str


@dataclass(slots=True)
class ResearchBundle:
    key: tuple[str, ...]
    identity: str
    members: tuple[ResearchBundleMember, ...]
    shared: bool


@dataclass(slots=True)
class StageRunStats:
    completed: int = 0
    skipped: int = 0
    failed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "completed": self.completed,
            "skipped": self.skipped,
            "failed": self.failed,
        }


@dataclass(slots=True)
class SuiteRunStats:
    research: StageRunStats = field(default_factory=StageRunStats)
    forecast: StageRunStats = field(default_factory=StageRunStats)

    def stage(self, stage: ExperimentStage) -> StageRunStats:
        if stage == ExperimentStage.RESEARCH:
            return self.research
        return self.forecast

    def to_dict(self) -> dict[str, dict[str, int]]:
        return {
            "research": self.research.to_dict(),
            "forecast": self.forecast.to_dict(),
        }


@dataclass(slots=True)
class PipelineSummary:
    run_id: str
    run_date: date
    target_date: date
    window_days: int
    total_markets: int = 0
    processed_markets: int = 0
    failed_markets: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)
    suite_stats: dict[str, SuiteRunStats] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "run_date": self.run_date.isoformat(),
            "target_date": self.target_date.isoformat(),
            "window_days": self.window_days,
            "total_markets": self.total_markets,
            "processed_markets": self.processed_markets,
            "failed_markets": self.failed_markets,
            "failures": self.failures,
            "suite_stats": {
                suite_id: stats.to_dict()
                for suite_id, stats in sorted(self.suite_stats.items())
            },
        }

    def record_experiment_meta(self, meta: ExperimentRunMeta) -> None:
        suite_stats = self.suite_stats.setdefault(meta.suite_id, SuiteRunStats())
        stage_stats = suite_stats.stage(meta.stage)
        stage_stats.completed += meta.success_count
        stage_stats.skipped += meta.skip_count
        stage_stats.failed += meta.failure_count


@dataclass(slots=True)
class EventBucket:
    event: NormalizedEvent | None
    markets: list[NormalizedMarket] = field(default_factory=list)


def _parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run the daily Polymarket processing pipeline")
    parser.add_argument(
        "--window-days",
        type=int,
        default=settings.target_close_window_days,
        help="Number of days ahead to target for market close date",
    )
    parser.add_argument(
        "--target-date",
        type=str,
        default=None,
        help="Explicit target date in YYYY-MM-DD (overrides --window-days)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute without persisting any database changes",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for number of markets to process (testing only)",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=None,
        help="Write JSON summary to the specified path",
    )
    parser.add_argument(
        "--suite",
        action="append",
        default=None,
        help="Restrict execution to suite_id (repeatable)",
    )
    parser.add_argument(
        "--stage",
        choices=["research", "forecast", "both"],
        default="both",
        help="Limit execution to research-only, forecast-only, or both stages",
    )
    parser.add_argument(
        "--include-research",
        type=str,
        default=None,
        help="Comma-separated research variant names or suite_id:variant entries to run",
    )
    parser.add_argument(
        "--include-forecast",
        type=str,
        default=None,
        help="Comma-separated forecast variant names or suite_id:variant entries to run",
    )
    parser.add_argument(
        "--debug-dump-dir",
        type=Path,
        default=(
            Path(settings.pipeline_debug_dump_dir)
            if settings.pipeline_debug_dump_dir
            else None
        ),
        help="Directory to write research/forecast payload dumps (set via PIPELINE_DEBUG_DUMP_DIR; use --no-debug-dump to disable)",
    )
    parser.add_argument(
        "--no-debug-dump",
        action="store_true",
        help="Disable writing debug payload dumps for this run",
    )
    parser.add_argument(
        "--list-experiments",
        action="store_true",
        help="Print the configured experiment manifest and exit",
    )
    return parser.parse_args()


@dataclass(slots=True, frozen=True)
class StageConfig:
    active_stages: FrozenSet[ExperimentStage]
    enabled_research: FrozenSet[str] | None
    enabled_forecast: FrozenSet[str] | None


def _resolve_stage_config(args: argparse.Namespace) -> StageConfig:
    stage_map = {
        "research": frozenset({ExperimentStage.RESEARCH}),
        "forecast": frozenset({ExperimentStage.FORECAST}),
        "both": frozenset({ExperimentStage.RESEARCH, ExperimentStage.FORECAST}),
    }
    active_stages = stage_map[args.stage]

    enabled_research = _parse_variant_filter(args.include_research)
    normalized_research: FrozenSet[str] | None = None
    if enabled_research:
        normalized_research = frozenset(enabled_research)

    enabled_forecast = _parse_variant_filter(args.include_forecast)
    normalized_forecast: FrozenSet[str] | None = None
    if enabled_forecast:
        normalized_forecast = frozenset(enabled_forecast)

    return StageConfig(
        active_stages=active_stages,
        enabled_research=normalized_research,
        enabled_forecast=normalized_forecast,
    )


def _resolve_dates(
    *,
    run_date: date,
    window_days: int,
    target_date_override: str | None,
) -> tuple[int, date]:
    if target_date_override:
        target_date = datetime.strptime(target_date_override, "%Y-%m-%d").date()
        window_days = (target_date - run_date).days
        if window_days < 0:
            raise ValueError("Target date cannot be before the run date")
        return window_days, target_date
    return window_days, run_date + timedelta(days=window_days)


def _day_bounds(target: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def _isoformat(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_filters(
    *,
    settings,
    start: datetime,
    end: datetime,
) -> dict[str, object]:
    filters = dict(settings.ingestion_filters)
    filters["closed"] = False
    filters["end_date_min"] = _isoformat(start)
    filters["end_date_max"] = _isoformat(end)
    return filters


def _convert_contracts(market: NormalizedMarket) -> list[ProcessedContractInput]:
    contracts: list[ProcessedContractInput] = []
    for contract in market.contracts:
        attributes = {
            "outcome_type": contract.outcome_type,
            "confidence": contract.confidence,
            "implied_probability": contract.implied_probability,
            "raw_data": contract.raw_data,
        }
        contracts.append(
            ProcessedContractInput(
                contract_id=contract.contract_id,
                name=contract.name,
                price=contract.current_price,
                attributes=attributes,
            )
        )
    return contracts



def _compute_artifact_hash(payload: dict[str, object] | None) -> str | None:
    if payload is None:
        return None
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _enrich_payload(
    payload: dict[str, Any] | None,
    *,
    diagnostics: dict[str, Any] | None = None,
    references: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if payload is None and not diagnostics and not references:
        return payload
    data = dict(payload or {})
    if diagnostics:
        data.setdefault("_diagnostics", diagnostics)
    if references:
        data.setdefault("_research_artifacts", references)
    return data


def _parse_variant_filter(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {item.strip() for item in raw.split(',') if item.strip()}


def _serialize_event(event: NormalizedEvent | None) -> dict[str, Any] | None:
    if event is None:
        return None
    return {
        "event_id": event.event_id,
        "slug": event.slug,
        "title": event.title,
        "description": event.description,
        "start_time": event.start_time.isoformat() if event.start_time else None,
        "end_time": event.end_time.isoformat() if event.end_time else None,
        "icon_url": event.icon_url,
        "series_slug": event.series_slug,
        "series_title": event.series_title,
    }


def _serialize_market(market: NormalizedMarket) -> dict[str, Any]:
    return {
        "market_id": market.market_id,
        "slug": market.slug,
        "question": market.question,
        "category": market.category,
        "sub_category": market.sub_category,
        "open_time": market.open_time.isoformat() if market.open_time else None,
        "close_time": market.close_time.isoformat() if market.close_time else None,
        "status": market.status,
        "volume_usd": market.volume_usd,
        "liquidity_usd": market.liquidity_usd,
        "fee_bps": market.fee_bps,
        "contracts": [
            {
                "contract_id": contract.contract_id,
                "name": contract.name,
                "outcome_type": contract.outcome_type,
                "current_price": contract.current_price,
                "confidence": contract.confidence,
                "implied_probability": contract.implied_probability,
            }
            for contract in market.contracts
        ],
    }


def _dump_debug_artifacts(
    base_dir: Path,
    *,
    run_id: str,
    suite_id: str,
    group: EventMarketGroup,
    research_records: dict[str, ResearchExecutionRecord],
    forecast_records: Sequence[ForecastExecutionRecord],
) -> None:
    event_identifier: str
    if group.event and group.event.event_id:
        event_identifier = group.event.event_id
    elif group.markets:
        event_identifier = f"market-{group.markets[0].market_id}"
    else:
        event_identifier = "event-unknown"

    dump_dir = base_dir / run_id / suite_id
    try:
        dump_dir.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to create debug dump directory {}", dump_dir)
        return

    payload = {
        "run_id": run_id,
        "suite_id": suite_id,
        "event": _serialize_event(group.event),
        "markets": [_serialize_market(market) for market in group.markets],
        "research": {
            name: {
                "variant": record.meta.strategy_name,
                "version": record.meta.strategy_version,
                "artifact_id": record.artifact_id,
                "artifact_uri": record.output.artifact_uri,
                "artifact_hash": record.output.artifact_hash,
                "payload": record.output.payload,
                "diagnostics": record.output.diagnostics,
            }
            for name, record in research_records.items()
        },
        "forecasts": {
            variant: {
                record.output.market_id: {
                    "outcomePrices": record.output.outcome_prices,
                    "reasoning": record.output.reasoning,
                }
                for record in variant_records
            }
            for variant, variant_records in _group_forecasts_by_variant(forecast_records).items()
        },
    }

    target_path = dump_dir / f"{event_identifier}.json"
    try:
        target_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + os.linesep,
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to write debug dump for suite {} event {}", suite_id, event_identifier
        )


def _group_forecasts_by_variant(
    records: Sequence[ForecastExecutionRecord],
) -> dict[str, list[ForecastExecutionRecord]]:
    grouped: dict[str, list[ForecastExecutionRecord]] = {}
    for record in records:
        grouped.setdefault(record.meta.strategy_name, []).append(record)
    return grouped


def _normalize_for_fingerprint(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_for_fingerprint(val)
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_normalize_for_fingerprint(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _fingerprint_mapping(mapping: Mapping[str, Any] | None) -> str:
    if not mapping:
        return "default"
    normalized = _normalize_for_fingerprint(mapping)
    serialized = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _variant_selected(
    suite_id: str,
    strategy_name: str,
    selection: set[str] | None,
) -> bool:
    if not selection:
        return True
    return strategy_name in selection or f"{suite_id}:{strategy_name}" in selection


def _build_research_bundles(
    suites: Sequence[BaseExperimentSuite],
    context: PipelineContext,
    meta_index: Mapping[tuple[str, ExperimentStage, str], ExperimentRunMeta],
) -> tuple[ResearchBundle, ...]:
    bundles: dict[tuple[str, ...], list[ResearchBundleMember]] = {}
    for suite in suites:
        for strategy in suite.research_strategies():
            meta = meta_index[(suite.suite_id, ExperimentStage.RESEARCH, strategy.name)]
            experiment_name = suite.experiment_name(
                ExperimentStage.RESEARCH, strategy.name
            )
            overrides = context.settings.experiment_config(experiment_name)
            fingerprint = _fingerprint_mapping(overrides)
            identity = getattr(strategy, "shared_identity", None)
            if identity:
                key: tuple[str, ...] = (
                    "shared",
                    identity,
                    getattr(strategy, "version", "1.0"),
                    fingerprint,
                )
            else:
                key = ("suite", suite.suite_id, strategy.name)
            member = ResearchBundleMember(
                suite_id=suite.suite_id,
                strategy_name=strategy.name,
                strategy=strategy,
                meta=meta,
                experiment_name=experiment_name,
                config_fingerprint=fingerprint,
            )
            bundles.setdefault(key, []).append(member)

    ordered_keys = sorted(bundles, key=lambda item: item)
    result: list[ResearchBundle] = []
    for key in ordered_keys:
        members = bundles[key]
        shared = key[0] == "shared" and len(members) > 1
        if key[0] == "shared":
            identity = key[1]
        else:
            identity = f"{members[0].suite_id}:{members[0].strategy_name}"
        result.append(
            ResearchBundle(
                key=key,
                identity=identity,
                members=tuple(members),
                shared=shared,
            )
        )
    return tuple(result)


def _execute_research_bundles(
    suites: Sequence[BaseExperimentSuite],
    bundles: Sequence[ResearchBundle],
    group: EventMarketGroup,
    context: PipelineContext,
    *,
    active_stages: set[ExperimentStage],
    enabled_research: set[str] | None,
) -> dict[str, dict[str, ResearchExecutionRecord]]:
    suite_records: dict[str, dict[str, ResearchExecutionRecord]] = {
        suite.suite_id: {} for suite in suites
    }

    if ExperimentStage.RESEARCH not in active_stages:
        for bundle in bundles:
            for member in bundle.members:
                member.meta.mark_skipped(
                    "research stage disabled by run configuration"
                )
        return suite_records

    for bundle in bundles:
        active_members: list[ResearchBundleMember] = []
        for member in bundle.members:
            if not _variant_selected(
                member.suite_id, member.strategy_name, enabled_research
            ):
                member.meta.mark_skipped(
                    "research variant filtered by include-research"
                )
                continue
            active_members.append(member)

        if not active_members:
            continue

        canonical = active_members[0]
        strategy = canonical.strategy
        try:
            output = strategy.run(group, context)
        except ExperimentSkip as exc:
            message = str(exc)
            for member in active_members:
                member.meta.mark_skipped(message)
            logger.info(
                "Research bundle {} skipped group (suites={}, event={}): {}",
                bundle.identity,
                ", ".join(member.suite_id for member in active_members),
                group.event.event_id if group.event else "none",
                message,
            )
            continue
        except ExperimentExecutionError as exc:
            message = str(exc)
            for member in active_members:
                member.meta.mark_failed(message)
            logger.error(
                "Research bundle {} failed for event {}: {}",
                bundle.identity,
                group.event.event_id if group.event else "none",
                exc,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            for member in active_members:
                member.meta.mark_failed(message)
            logger.exception(
                "Unexpected error in research bundle {} for event {}",
                bundle.identity,
                group.event.event_id if group.event else "none",
            )
            raise ExperimentExecutionError(message) from exc
        else:
            bundle_identity = bundle.identity if bundle.shared else None
            canonical.meta.record_success()
            suite_records[canonical.suite_id][canonical.strategy_name] = (
                ResearchExecutionRecord(
                    meta=canonical.meta,
                    output=output,
                    bundle_identity=bundle_identity,
                )
            )
            for member in active_members[1:]:
                member.meta.record_success()
                suite_records[member.suite_id][member.strategy_name] = (
                    ResearchExecutionRecord(
                        meta=member.meta,
                        output=output,
                        bundle_identity=bundle_identity,
                    )
                )
            if bundle.shared and len(active_members) > 1:
                logger.info(
                    "Reused research strategy {} across suites [{}] (fingerprint={})",
                    canonical.strategy_name,
                    ", ".join(member.suite_id for member in active_members),
                    canonical.config_fingerprint,
                )

    return suite_records


def _execute_forecast_stage(
    suites: Sequence[BaseExperimentSuite],
    group: EventMarketGroup,
    context: PipelineContext,
    meta_index: Mapping[tuple[str, ExperimentStage, str], ExperimentRunMeta],
    suite_research_records: Mapping[str, Mapping[str, ResearchExecutionRecord]],
    *,
    active_stages: set[ExperimentStage],
    enabled_forecast: set[str] | None,
) -> list[ForecastExecutionRecord]:
    forecast_records: list[ForecastExecutionRecord] = []

    if ExperimentStage.FORECAST not in active_stages:
        for suite in suites:
            for strategy in suite.forecast_strategies():
                meta = meta_index[(suite.suite_id, ExperimentStage.FORECAST, strategy.name)]
                meta.mark_skipped(
                    "forecast stage disabled by run configuration"
                )
        return forecast_records

    for suite in suites:
        available_outputs = {
            name: record.output
            for name, record in suite_research_records.get(suite.suite_id, {}).items()
        }
        for strategy in suite.forecast_strategies():
            meta = meta_index[(suite.suite_id, ExperimentStage.FORECAST, strategy.name)]
            if not _variant_selected(
                suite.suite_id, strategy.name, enabled_forecast
            ):
                meta.mark_skipped(
                    "forecast variant filtered by include-forecast"
                )
                continue
            missing = [name for name in strategy.requires if name not in available_outputs]
            if missing:
                meta.mark_skipped(
                    "missing research dependencies: " + ", ".join(missing)
                )
                logger.warning(
                    "Skipping forecast strategy {} in suite {} due to missing research dependencies: {}",
                    strategy.name,
                    suite.suite_id,
                    ", ".join(missing),
                )
                continue
            try:
                outputs = list(strategy.run(group, available_outputs, context))
            except ExperimentSkip as exc:
                meta.mark_skipped(str(exc))
                logger.info(
                    "Forecast strategy {} skipped group (suite {}, event {})",
                    strategy.name,
                    suite.suite_id,
                    group.event.event_id if group.event else "none",
                )
                continue
            except ExperimentExecutionError as exc:
                meta.mark_failed(str(exc))
                logger.error(
                    "Forecast strategy {} failed for suite {} and event {}: {}",
                    strategy.name,
                    suite.suite_id,
                    group.event.event_id if group.event else "none",
                    exc,
                )
                raise
            except Exception as exc:  # noqa: BLE001
                meta.mark_failed(str(exc))
                logger.exception(
                    "Unexpected error in forecast strategy {} for suite {}",
                    strategy.name,
                    suite.suite_id,
                )
                raise ExperimentExecutionError(str(exc)) from exc
            else:
                meta.record_success()
                for output in outputs:
                    forecast_records.append(
                        ForecastExecutionRecord(
                            meta=meta,
                            output=output,
                            dependencies=tuple(strategy.requires),
                        )
                    )

    return forecast_records





def _prepare_experiment_metadata(
    suites: Sequence[BaseExperimentSuite],
) -> tuple[list[ExperimentRunMeta], dict[tuple[str, ExperimentStage, str], ExperimentRunMeta]]:
    metas: list[ExperimentRunMeta] = []
    index: dict[tuple[str, ExperimentStage, str], ExperimentRunMeta] = {}
    for suite in suites:
        for strategy in suite.research_strategies():
            meta = ExperimentRunMeta(
                suite_id=suite.suite_id,
                stage=ExperimentStage.RESEARCH,
                strategy_name=strategy.name,
                strategy_version=strategy.version,
                experiment_name=suite.experiment_name(ExperimentStage.RESEARCH, strategy.name),
                description=getattr(strategy, "description", None),
                strategy=strategy,
                run_identifier=str(uuid4()),
            )
            setattr(strategy, "_experiment_name", meta.experiment_name)
            metas.append(meta)
            index[(suite.suite_id, ExperimentStage.RESEARCH, strategy.name)] = meta
        for strategy in suite.forecast_strategies():
            meta = ExperimentRunMeta(
                suite_id=suite.suite_id,
                stage=ExperimentStage.FORECAST,
                strategy_name=strategy.name,
                strategy_version=strategy.version,
                experiment_name=suite.experiment_name(ExperimentStage.FORECAST, strategy.name),
                description=getattr(strategy, "description", None),
                strategy=strategy,
                run_identifier=str(uuid4()),
            )
            setattr(strategy, "_experiment_name", meta.experiment_name)
            metas.append(meta)
            index[(suite.suite_id, ExperimentStage.FORECAST, strategy.name)] = meta
    return metas, index




def run_pipeline(
    args: argparse.Namespace,
    settings: Settings,
    *,
    suites: Sequence[BaseExperimentSuite] | None = None,
    stage_config: StageConfig | None = None,
    now: datetime | None = None,
    client_factory: Callable[[], PolymarketClient] | None = None,
    session_factory: Callable[[], ContextManager[Any]] | None = None,
    init_db_fn: Callable[[], None] = init_db,
    processing_repo_factory: Callable[[Any], ProcessingRepository] | None = None,
    market_repo_factory: Callable[[Any], MarketRepository] | None = None,
) -> PipelineSummary:
    suites = tuple(suites) if suites is not None else tuple(load_suites(args.suite))
    stage_config = stage_config or _resolve_stage_config(args)

    active_stages = set(stage_config.active_stages)
    enabled_research = (
        set(stage_config.enabled_research) if stage_config.enabled_research else None
    )
    enabled_forecast = (
        set(stage_config.enabled_forecast) if stage_config.enabled_forecast else None
    )

    if session_factory is None:
        init_db_fn()
        session_factory = session_scope

    processing_repo_factory = processing_repo_factory or (
        lambda session: ProcessingRepository(session)
    )
    market_repo_factory = market_repo_factory or (lambda session: MarketRepository(session))

    now = now or datetime.now(timezone.utc)
    run_date = now.date()
    window_days, target_date = _resolve_dates(
        run_date=run_date,
        window_days=args.window_days,
        target_date_override=args.target_date,
    )

    start_bound, end_bound = _day_bounds(target_date)
    filters = _build_filters(settings=settings, start=start_bound, end=end_bound)

    debug_dump_dir: Path | None = None
    if not args.no_debug_dump and args.debug_dump_dir:
        debug_dump_dir = Path(args.debug_dump_dir).expanduser().resolve()
        debug_dump_dir.mkdir(parents=True, exist_ok=True)

    experiment_metas, experiment_meta_index = _prepare_experiment_metadata(suites)

    run_id = str(uuid4())
    summary = PipelineSummary(
        run_id=run_id,
        run_date=run_date,
        target_date=target_date,
        window_days=window_days,
    )

    git_sha = os.getenv("GITHUB_SHA")
    logger.info(
        "Starting pipeline run {} (target {}, window {} days, dry_run={})",
        run_id,
        target_date,
        window_days,
        args.dry_run,
    )

    with session_factory() as session:
        processing_repo = processing_repo_factory(session)
        market_repo = market_repo_factory(session)

        pipeline_context = PipelineContext(
            run_id=run_id,
            run_date=run_date,
            target_date=target_date,
            window_days=window_days,
            settings=settings,
            db_session=session,
            dry_run=args.dry_run,
        )

        research_bundles = _build_research_bundles(
            suites,
            pipeline_context,
            experiment_meta_index,
        )

        processing_run = None
        if not args.dry_run:
            processing_run = processing_repo.create_processing_run(
                run_id=run_id,
                run_date=run_date,
                window_days=window_days,
                target_date=target_date,
                git_sha=git_sha,
                environment=settings.environment,
            )
            for meta in experiment_metas:
                processing_repo.record_experiment_run(
                    ExperimentRunInput(
                        experiment_run_id=meta.run_identifier,
                        run_id=run_id,
                        experiment_name=meta.experiment_name,
                        experiment_version=meta.strategy_version,
                        stage=meta.stage.value,
                        status=meta.status,
                        started_at=meta.started_at,
                        finished_at=None,
                        error_message=None,
                    ),
                    description=meta.description,
                )

        if client_factory is None:
            def _default_client_factory() -> PolymarketClient:
                return PolymarketClient(
                    page_size=settings.ingestion_page_size, filters=filters
                )

            client_factory = _default_client_factory

        client = client_factory()

        try:
            grouped_markets: dict[str, EventBucket] = {}
            event_order: list[str] = []

            for index, raw_market in enumerate(client.iter_markets(), start=1):
                if args.limit and index > args.limit:
                    logger.info("Limit reached ({}); stopping early", args.limit)
                    break

                summary.total_markets += 1

                try:
                    normalized = normalize_market(raw_market)
                except Exception as exc:  # noqa: BLE001
                    summary.failed_markets += 1
                    failure_reason = f"normalization_failed: {exc}"
                    summary.failures.append(
                        {
                            "market_id": raw_market.get("id", "unknown"),
                            "reason": failure_reason,
                        }
                    )
                    logger.exception(
                        "Normalization failed for market payload {}",
                        raw_market.get("id", "unknown"),
                    )
                    if not args.dry_run:
                        processing_repo.record_processing_failure(
                            run_id=run_id,
                            market_id=raw_market.get("id"),
                            reason="normalization_failed",
                            retriable=True,
                            details={"message": str(exc)},
                        )
                    continue

                event = normalized.event
                if event and event.event_id:
                    group_key = event.event_id
                else:
                    group_key = f"market:{normalized.market_id}"

                bucket = grouped_markets.get(group_key)
                if bucket is None:
                    bucket = EventBucket(event=event)
                    grouped_markets[group_key] = bucket
                    event_order.append(group_key)
                elif bucket.event is None and event is not None:
                    bucket.event = event

                bucket.markets.append(normalized)

            for group_key in event_order:
                bucket = grouped_markets[group_key]
                markets = bucket.markets
                event_payload = bucket.event
                group = EventMarketGroup(event=event_payload, markets=markets)

                try:
                    suite_research_records = _execute_research_bundles(
                        suites,
                        research_bundles,
                        group,
                        pipeline_context,
                        active_stages=active_stages,
                        enabled_research=enabled_research,
                    )
                    forecast_records = _execute_forecast_stage(
                        suites,
                        group,
                        pipeline_context,
                        experiment_meta_index,
                        suite_research_records,
                        active_stages=active_stages,
                        enabled_forecast=enabled_forecast,
                    )
                except ExperimentExecutionError as exc:
                    for market in markets:
                        summary.failed_markets += 1
                        failure_reason = f"experiment_failed: {exc}"
                        summary.failures.append(
                            {
                                "market_id": market.market_id,
                                "reason": failure_reason,
                            }
                        )
                        if not args.dry_run:
                            processing_repo.record_processing_failure(
                                run_id=run_id,
                                market_id=market.market_id,
                                reason="experiment_failed",
                                retriable=True,
                                details={"message": str(exc)},
                            )
                    continue

                if debug_dump_dir:
                    for suite in suites:
                        suite_forecasts = [
                            record
                            for record in forecast_records
                            if record.meta.suite_id == suite.suite_id
                        ]
                        _dump_debug_artifacts(
                            debug_dump_dir,
                            run_id=run_id,
                            suite_id=suite.suite_id,
                            group=group,
                            research_records=suite_research_records.get(suite.suite_id, {}),
                            forecast_records=suite_forecasts,
                        )

                expect_forecasts = ExperimentStage.FORECAST in active_stages
                if expect_forecasts and not forecast_records:
                    for market in markets:
                        summary.failed_markets += 1
                        summary.failures.append(
                            {
                                "market_id": market.market_id,
                                "reason": "no_forecast_results",
                            }
                        )
                        logger.warning(
                            "No forecast results returned for market {}; skipping persistence",
                            market.market_id,
                        )
                        if not args.dry_run:
                            processing_repo.record_processing_failure(
                                run_id=run_id,
                                market_id=market.market_id,
                                reason="no_forecast_results",
                                retriable=False,
                                details=None,
                            )
                    continue

                summary.processed_markets += len(markets)

                if args.dry_run:
                    continue

                processed_event_id = str(uuid4())
                processed_event = processing_repo.record_processed_event(
                    ProcessedEventInput(
                        processed_event_id=processed_event_id,
                        run_id=run_id,
                        event_id=event_payload.event_id if event_payload else None,
                        event_slug=event_payload.slug if event_payload else None,
                        event_title=event_payload.title if event_payload else None,
                        raw_snapshot=event_payload.raw_data if event_payload else None,
                    )
                )

                market_to_processed: dict[str, str] = {}

                for market in markets:
                    processed_market_id = str(uuid4())
                    processed_market = processing_repo.record_processed_market(
                        ProcessedMarketInput(
                            processed_market_id=processed_market_id,
                            run_id=run_id,
                            market_id=market.market_id,
                            market_slug=market.slug,
                            question=market.question,
                            close_time=market.close_time,
                            raw_snapshot=market.raw_data,
                            processed_event_id=processed_event.processed_event_id,
                            contracts=_convert_contracts(market),
                        )
                    )
                    market_to_processed[market.market_id] = processed_market.processed_market_id

                    market_repo.upsert_market(market)

                for suite_id, records in suite_research_records.items():
                    for variant_name, record in records.items():
                        payload = _enrich_payload(
                            record.output.payload,
                            diagnostics=record.output.diagnostics,
                        )
                        artifact_hash = record.output.artifact_hash or _compute_artifact_hash(payload)
                        artifact_id = str(uuid4())
                        record.artifact_id = artifact_id
                        processing_repo.record_research_artifact(
                            ResearchArtifactInput(
                                artifact_id=artifact_id,
                                experiment_run_id=record.meta.run_identifier,
                                processed_market_id=None,
                                processed_event_id=processed_event.processed_event_id,
                                variant_name=record.meta.strategy_name,
                                variant_version=record.meta.strategy_version,
                                artifact_hash=artifact_hash,
                                payload=payload,
                                artifact_uri=record.output.artifact_uri,
                            )
                        )
                        processing_repo.record_experiment_result(
                            ExperimentResultInput(
                                experiment_run_id=record.meta.run_identifier,
                                processed_market_id=None,
                                processed_event_id=processed_event.processed_event_id,
                                stage=ExperimentStage.RESEARCH.value,
                                variant_name=record.meta.strategy_name,
                                variant_version=record.meta.strategy_version,
                                source_artifact_id=artifact_id,
                                payload=payload,
                                score=None,
                                artifact_uri=record.output.artifact_uri,
                            )
                        )

                for forecast_record in forecast_records:
                    dependencies: dict[str, str] = {}
                    suite_records = suite_research_records.get(forecast_record.meta.suite_id, {})
                    for dep in forecast_record.dependencies:
                        artifact = suite_records.get(dep)
                        if artifact and artifact.artifact_id:
                            dependencies[dep] = artifact.artifact_id
                    primary_artifact_id = None
                    if len(dependencies) == 1:
                        primary_artifact_id = next(iter(dependencies.values()))
                    processed_market_id = market_to_processed.get(
                        forecast_record.output.market_id
                    )
                    if not processed_market_id:
                        logger.warning(
                            "Missing processed market mapping for forecast market {} -- skipping result",
                            forecast_record.output.market_id,
                        )
                        continue
                    payload = {
                        "outcomePrices": forecast_record.output.outcome_prices,
                        "reasoning": forecast_record.output.reasoning,
                    }
                    processing_repo.record_experiment_result(
                        ExperimentResultInput(
                            experiment_run_id=forecast_record.meta.run_identifier,
                            processed_market_id=processed_market_id,
                            processed_event_id=processed_event.processed_event_id,
                            stage=ExperimentStage.FORECAST.value,
                            variant_name=forecast_record.meta.strategy_name,
                            variant_version=forecast_record.meta.strategy_version,
                            source_artifact_id=primary_artifact_id,
                            payload=payload,
                            score=forecast_record.output.score,
                            artifact_uri=forecast_record.output.artifact_uri,
                        )
                    )

        finally:
            if hasattr(client, "close"):
                client.close()

        finished_at = datetime.now(timezone.utc)

        if not args.dry_run and processing_run is not None:
            processing_repo.finalize_processing_run(
                processing_run,
                status="completed"
                if summary.failed_markets == 0
                else "completed_with_errors",
                total_markets=summary.total_markets,
                processed_markets=summary.processed_markets,
                failed_markets=summary.failed_markets,
                finished_at=finished_at,
            )
            for meta in experiment_metas:
                meta.finished_at = finished_at
                status = meta.status
                if status == "running":
                    status = "completed"
                processing_repo.record_experiment_run(
                    ExperimentRunInput(
                        experiment_run_id=meta.run_identifier,
                        run_id=run_id,
                        experiment_name=meta.experiment_name,
                        experiment_version=meta.strategy_version,
                        stage=meta.stage.value,
                        status=status,
                        started_at=meta.started_at,
                        finished_at=meta.finished_at,
                        error_message="; ".join(meta.error_messages)
                        if meta.error_messages
                        else None,
                    ),
                    description=meta.description,
                )

    for meta in experiment_metas:
        summary.record_experiment_meta(meta)

    logger.info(
        "Pipeline run {} completed. processed={}, failed={}, total={}",
        run_id,
        summary.processed_markets,
        summary.failed_markets,
        summary.total_markets,
    )

    if args.summary_path:
        _write_summary(args.summary_path, summary)
        logger.info("Wrote pipeline summary to {}", args.summary_path)

    if summary.failed_markets:
        logger.warning(
            "Pipeline completed with {} failures", summary.failed_markets,
        )

    return summary


def _write_summary(path: Path, summary: PipelineSummary) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = _parse_args()
    settings = get_settings()
    suites = tuple(load_suites(args.suite))
    stage_config = _resolve_stage_config(args)

    if args.list_experiments:
        manifest = build_manifest(
            suites,
            active_stages=set(stage_config.active_stages),
            enabled_research=set(stage_config.enabled_research)
            if stage_config.enabled_research
            else None,
            enabled_forecast=set(stage_config.enabled_forecast)
            if stage_config.enabled_forecast
            else None,
        )
        manifest["configuration"] = {
            "stage": args.stage,
            "suite_filter": list(args.suite or []),
            "include_research": sorted(stage_config.enabled_research)
            if stage_config.enabled_research
            else None,
            "include_forecast": sorted(stage_config.enabled_forecast)
            if stage_config.enabled_forecast
            else None,
        }
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return

    run_pipeline(
        args,
        settings,
        suites=suites,
        stage_config=stage_config,
    )


if __name__ == "__main__":
    main()
