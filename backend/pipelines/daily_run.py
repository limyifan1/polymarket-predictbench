from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from loguru import logger

from app import crud
from app.core.config import get_settings
from app.db import init_db
from app.crud import (
    ExperimentResultInput,
    ExperimentRunInput,
    NormalizedMarket,
    ProcessedContractInput,
    ProcessedMarketInput,
)
from ingestion.client import PolymarketClient
from ingestion.normalize import normalize_market
from ingestion.service import session_scope

from .context import PipelineContext
from .experiments.base import Experiment, ExperimentExecutionError, ExperimentResult, ExperimentSkip
from .registry import load_experiments


@dataclass(slots=True)
class ExperimentRunMeta:
    experiment: Experiment
    run_identifier: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    status: str = "running"
    error_messages: list[str] = field(default_factory=list)


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
        }


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
    return parser.parse_args()


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


def _execute_experiments(
    *,
    market: NormalizedMarket,
    pipeline_context: PipelineContext,
    experiment_runs: list[ExperimentRunMeta],
) -> list[ExperimentResult]:
    results: list[ExperimentResult] = []
    for meta in experiment_runs:
        try:
            result = meta.experiment.run(market, pipeline_context)
        except ExperimentSkip as exc:
            logger.info(
                "Experiment {} skipped market {}: {}",
                meta.experiment.name,
                market.market_id,
                exc,
            )
            continue
        except ExperimentExecutionError as exc:
            meta.status = "failed"
            meta.error_messages.append(str(exc))
            logger.error(
                "Experiment {} failed for market {}: {}",
                meta.experiment.name,
                market.market_id,
                exc,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            meta.status = "failed"
            meta.error_messages.append(str(exc))
            logger.exception(
                "Unexpected error in experiment {} for market {}",
                meta.experiment.name,
                market.market_id,
            )
            raise ExperimentExecutionError(str(exc)) from exc
        else:
            results.append(result)
    return results


def _write_summary(path: Path, summary: PipelineSummary) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    args = _parse_args()
    settings = get_settings()
    init_db()

    now = datetime.now(timezone.utc)
    run_date = now.date()
    window_days, target_date = _resolve_dates(
        run_date=run_date, window_days=args.window_days, target_date_override=args.target_date
    )

    start_bound, end_bound = _day_bounds(target_date)
    filters = _build_filters(settings=settings, start=start_bound, end=end_bound)

    experiments = load_experiments(settings.processing_experiments)
    if not experiments:
        raise RuntimeError("No experiments registered; aborting pipeline run")

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

    with session_scope() as session:
        pipeline_context = PipelineContext(
            run_id=run_id,
            run_date=run_date,
            target_date=target_date,
            window_days=window_days,
            settings=settings,
            db_session=session,
            dry_run=args.dry_run,
        )

        experiment_metas: list[ExperimentRunMeta] = [
            ExperimentRunMeta(experiment=experiment, run_identifier=str(uuid4()))
            for experiment in experiments
        ]
        experiment_meta_index = {
            (meta.experiment.name, meta.experiment.version): meta for meta in experiment_metas
        }

        processing_run = None
        if not args.dry_run:
            processing_run = crud.create_processing_run(
                session,
                run_id=run_id,
                run_date=run_date,
                window_days=window_days,
                target_date=target_date,
                git_sha=git_sha,
                environment=settings.environment,
            )
            for meta in experiment_metas:
                crud.record_experiment_run(
                    session,
                    ExperimentRunInput(
                        experiment_run_id=meta.run_identifier,
                        run_id=run_id,
                        experiment_name=meta.experiment.name,
                        experiment_version=meta.experiment.version,
                        status=meta.status,
                        started_at=meta.started_at,
                        finished_at=None,
                        error_message=None,
                    ),
                    description=getattr(meta.experiment, "description", None),
                )

        client = PolymarketClient(page_size=settings.ingestion_page_size, filters=filters)

        try:
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
                        "Normalization failed for market payload {}", raw_market.get("id", "unknown")
                    )
                    if not args.dry_run:
                        crud.record_processing_failure(
                            session,
                            run_id=run_id,
                            market_id=raw_market.get("id"),
                            reason="normalization_failed",
                            retriable=True,
                            details={"message": str(exc)},
                        )
                    continue

                try:
                    experiment_results = _execute_experiments(
                        market=normalized,
                        pipeline_context=pipeline_context,
                        experiment_runs=experiment_metas,
                    )
                except ExperimentExecutionError as exc:
                    summary.failed_markets += 1
                    failure_reason = f"experiment_failed: {exc}"
                    summary.failures.append(
                        {
                            "market_id": normalized.market_id,
                            "reason": failure_reason,
                        }
                    )
                    if not args.dry_run:
                        crud.record_processing_failure(
                            session,
                            run_id=run_id,
                            market_id=normalized.market_id,
                            reason="experiment_failed",
                            retriable=True,
                            details={"message": str(exc)},
                        )
                    continue

                if not experiment_results:
                    summary.failed_markets += 1
                    summary.failures.append(
                        {
                            "market_id": normalized.market_id,
                            "reason": "no_experiment_results",
                        }
                    )
                    logger.warning(
                        "No experiment results returned for market {}; skipping persistence",
                        normalized.market_id,
                    )
                    if not args.dry_run:
                        crud.record_processing_failure(
                            session,
                            run_id=run_id,
                            market_id=normalized.market_id,
                            reason="no_experiment_results",
                            retriable=False,
                            details=None,
                        )
                    continue

                summary.processed_markets += 1

                if args.dry_run:
                    continue

                processed_market_id = str(uuid4())
                processed_market = crud.record_processed_market(
                    session,
                    ProcessedMarketInput(
                        processed_market_id=processed_market_id,
                        run_id=run_id,
                        market_id=normalized.market_id,
                        market_slug=normalized.slug,
                        question=normalized.question,
                        close_time=normalized.close_time,
                        raw_snapshot=normalized.raw_data,
                        contracts=_convert_contracts(normalized),
                    ),
                )

                crud.upsert_market(session, normalized)

                for result in experiment_results:
                    meta = experiment_meta_index.get((result.name, result.version))
                    if meta is None:
                        logger.warning(
                            "No experiment metadata found for result {} {}; skipping record",
                            result.name,
                            result.version,
                        )
                        continue
                    crud.record_experiment_result(
                        session,
                        ExperimentResultInput(
                            experiment_run_id=meta.run_identifier,
                            processed_market_id=processed_market.processed_market_id,
                            payload=result.payload,
                            score=result.score,
                            artifact_uri=result.artifact_uri,
                        ),
                    )
        finally:
            client.close()

        finished_at = datetime.now(timezone.utc)

        if not args.dry_run and processing_run is not None:
            crud.finalize_processing_run(
                session,
                processing_run,
                status="completed" if summary.failed_markets == 0 else "completed_with_errors",
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
                crud.record_experiment_run(
                    session,
                    ExperimentRunInput(
                        experiment_run_id=meta.run_identifier,
                        run_id=run_id,
                        experiment_name=meta.experiment.name,
                        experiment_version=meta.experiment.version,
                        status=status,
                        started_at=meta.started_at,
                        finished_at=meta.finished_at,
                        error_message="; ".join(meta.error_messages) if meta.error_messages else None,
                    ),
                    description=getattr(meta.experiment, "description", None),
                )

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


if __name__ == "__main__":
    main()
