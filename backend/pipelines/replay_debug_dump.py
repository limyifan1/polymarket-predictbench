"""Persist debug dump payloads back into the database."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from loguru import logger

from app.core.config import get_settings
from app.db import init_db
from app.domain import NormalizedContract, NormalizedEvent, NormalizedMarket
from app.models import ExperimentStage
from app.repositories import MarketRepository, ProcessingRepository
from app.repositories.pipeline_models import (
    ExperimentResultInput,
    ProcessedContractInput,
    ProcessedEventInput,
    ProcessedMarketInput,
    ResearchArtifactInput,
)
from ingestion.service import session_scope


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    try:
        normalized = candidate.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        logger.warning("Failed to parse datetime value %s", value)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class SuiteDump:
    suite_id: str
    research: dict[str, Any] = field(default_factory=dict)
    forecasts: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EventDump:
    event_key: str
    event_payload: dict[str, Any] | None
    markets: list[dict[str, Any]]
    suites: dict[str, SuiteDump]


def _load_run_dumps(run_dir: Path, includes: set[str] | None) -> dict[str, EventDump]:
    events: dict[str, EventDump] = {}

    for suite_dir in sorted(run_dir.iterdir()):
        if not suite_dir.is_dir():
            continue

        suite_id = suite_dir.name
        for dump_path in sorted(suite_dir.glob("*.json")):
            try:
                payload = json.loads(dump_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.exception("Failed to parse debug dump %s", dump_path)
                continue

            event_info = payload.get("event")
            markets = payload.get("markets") or []
            if event_info and event_info.get("event_id"):
                event_key = str(event_info.get("event_id"))
            elif markets:
                event_key = f"market:{markets[0].get('market_id')}"
            else:
                event_key = dump_path.stem

            if includes and event_key not in includes:
                continue

            entry = events.get(event_key)
            if entry is None:
                entry = EventDump(
                    event_key=event_key,
                    event_payload=event_info,
                    markets=markets,
                    suites={},
                )
                events[event_key] = entry

            suite_entry = SuiteDump(
                suite_id=suite_id,
                research=payload.get("research") or {},
                forecasts=payload.get("forecasts") or {},
            )
            entry.suites[suite_id] = suite_entry

    return events


def _build_normalized_event(payload: dict[str, Any] | None) -> NormalizedEvent | None:
    if not payload or not payload.get("event_id"):
        return None
    return NormalizedEvent(
        event_id=str(payload.get("event_id")),
        slug=payload.get("slug"),
        title=payload.get("title"),
        description=payload.get("description"),
        start_time=_parse_datetime(payload.get("start_time")),
        end_time=_parse_datetime(payload.get("end_time")),
        icon_url=payload.get("icon_url"),
        series_slug=payload.get("series_slug"),
        series_title=payload.get("series_title"),
        raw_data=payload.get("raw_data"),
    )


def _build_normalized_market(
    payload: dict[str, Any],
    event: NormalizedEvent | None,
) -> NormalizedMarket:
    contracts: list[NormalizedContract] = []
    for contract in payload.get("contracts", []):
        contracts.append(
            NormalizedContract(
                contract_id=str(contract.get("contract_id")),
                name=contract.get("name") or "Unknown",
                outcome_type=contract.get("outcome_type"),
                current_price=_parse_float(contract.get("current_price")),
                confidence=_parse_float(contract.get("confidence")),
                implied_probability=_parse_float(contract.get("implied_probability")),
                raw_data=contract.get("raw_data"),
            )
        )

    return NormalizedMarket(
        market_id=str(payload.get("market_id")),
        slug=payload.get("slug"),
        question=payload.get("question") or "",
        category=payload.get("category"),
        sub_category=payload.get("sub_category"),
        open_time=_parse_datetime(payload.get("open_time")),
        close_time=_parse_datetime(payload.get("close_time")),
        volume_usd=_parse_float(payload.get("volume_usd")),
        liquidity_usd=_parse_float(payload.get("liquidity_usd")),
        fee_bps=int(payload.get("fee_bps")) if payload.get("fee_bps") is not None else None,
        status=payload.get("status") or "open",
        description=payload.get("description"),
        icon_url=payload.get("icon_url"),
        event=event,
        contracts=contracts,
        raw_data=payload.get("raw_data"),
    )


def _convert_contracts(payload: dict[str, Any]) -> list[ProcessedContractInput]:
    contracts: list[ProcessedContractInput] = []
    for contract in payload.get("contracts", []):
        attributes = {
            "outcome_type": contract.get("outcome_type"),
            "confidence": contract.get("confidence"),
            "implied_probability": contract.get("implied_probability"),
            "raw_data": contract.get("raw_data"),
        }
        contracts.append(
            ProcessedContractInput(
                contract_id=str(contract.get("contract_id")),
                name=contract.get("name") or "Unknown",
                price=_parse_float(contract.get("current_price")),
                attributes=attributes,
            )
        )
    return contracts


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


def _persist_event_bundle(
    *,
    run_id: str,
    event: EventDump,
    skip_market_upsert: bool,
    dry_run: bool,
) -> None:
    event_display = event.event_payload.get("title") if event.event_payload else event.event_key

    logger.info(
        "Persisting event %s (%s) with %d suites",
        event.event_key,
        event_display,
        len(event.suites),
    )

    if dry_run:
        logger.info("Dry-run enabled; skipping database writes for %s", event.event_key)
        return

    normalized_event = _build_normalized_event(event.event_payload)

    with session_scope() as session:
        processing_repo = ProcessingRepository(session)
        market_repo = MarketRepository(session)

        processed_event_id = str(uuid4())
        processed_event = processing_repo.record_processed_event(
            ProcessedEventInput(
                processed_event_id=processed_event_id,
                run_id=run_id,
                event_key=event.event_key,
                event_id=normalized_event.event_id if normalized_event else None,
                event_slug=normalized_event.slug if normalized_event else None,
                event_title=normalized_event.title if normalized_event else None,
                raw_snapshot=event.event_payload,
            )
        )

        market_map: dict[str, str] = {}
        for market_payload in event.markets:
            processed_market_id = str(uuid4())
            processing_repo.record_processed_market(
                ProcessedMarketInput(
                    processed_market_id=processed_market_id,
                    run_id=run_id,
                    market_id=str(market_payload.get("market_id")),
                    market_slug=market_payload.get("slug"),
                    question=market_payload.get("question") or "",
                    close_time=_parse_datetime(market_payload.get("close_time")),
                    raw_snapshot=market_payload,
                    processed_event_id=processed_event.processed_event_id,
                    contracts=_convert_contracts(market_payload),
                )
            )
            market_map[str(market_payload.get("market_id"))] = processed_market_id

            if not skip_market_upsert:
                normalized_market = _build_normalized_market(
                    market_payload,
                    normalized_event,
                )
                market_repo.upsert_market(normalized_market)

        artifact_registry: dict[tuple[str, str], str] = {}

        for suite_id, suite_dump in sorted(event.suites.items()):
            for variant_key, research_entry in suite_dump.research.items():
                experiment_run_id = research_entry.get("experiment_run_id")
                if not experiment_run_id:
                    logger.warning(
                        "Missing experiment_run_id for research variant %s in suite %s",
                        variant_key,
                        suite_id,
                    )
                    continue

                artifact_id = research_entry.get("artifact_id") or str(uuid4())
                payload = _enrich_payload(
                    research_entry.get("payload"),
                    diagnostics=research_entry.get("diagnostics"),
                )

                processing_repo.record_research_artifact(
                    ResearchArtifactInput(
                        artifact_id=artifact_id,
                        experiment_run_id=experiment_run_id,
                        processed_market_id=None,
                        processed_event_id=processed_event.processed_event_id,
                        variant_name=research_entry.get("variant"),
                        variant_version=research_entry.get("version"),
                        artifact_hash=research_entry.get("artifact_hash"),
                        payload=payload,
                        artifact_uri=research_entry.get("artifact_uri"),
                    )
                )
                processing_repo.record_experiment_result(
                    ExperimentResultInput(
                        experiment_run_id=experiment_run_id,
                        processed_market_id=None,
                        processed_event_id=processed_event.processed_event_id,
                        stage=ExperimentStage.RESEARCH.value,
                        variant_name=research_entry.get("variant"),
                        variant_version=research_entry.get("version"),
                        source_artifact_id=artifact_id,
                        payload=payload,
                        score=None,
                        artifact_uri=research_entry.get("artifact_uri"),
                    )
                )

                artifact_registry[(suite_id, research_entry.get("variant"))] = artifact_id

            for variant_name, forecasts in suite_dump.forecasts.items():
                for market_id, forecast_entry in forecasts.items():
                    experiment_run_id = forecast_entry.get("experiment_run_id")
                    if not experiment_run_id:
                        logger.warning(
                            "Missing experiment_run_id for forecast variant %s market %s",
                            variant_name,
                            market_id,
                        )
                        continue

                    processed_market_id = market_map.get(str(market_id))
                    if not processed_market_id:
                        logger.warning(
                            "Skipping forecast for market %s (no processed market entry)",
                            market_id,
                        )
                        continue

                    dependencies = {}
                    raw_dependencies = forecast_entry.get("_research_artifacts") or {}
                    for dependency_name in raw_dependencies.keys():
                        resolved = artifact_registry.get((suite_id, dependency_name))
                        if resolved:
                            dependencies[dependency_name] = resolved

                    primary_artifact_id = None
                    if len(dependencies) == 1:
                        primary_artifact_id = next(iter(dependencies.values()))

                    payload = _enrich_payload(
                        {
                            "outcomePrices": forecast_entry.get("outcomePrices"),
                            "reasoning": forecast_entry.get("reasoning"),
                        },
                        diagnostics=forecast_entry.get("diagnostics"),
                        references=dependencies if dependencies else None,
                    )

                    processing_repo.record_experiment_result(
                        ExperimentResultInput(
                            experiment_run_id=experiment_run_id,
                            processed_market_id=processed_market_id,
                            processed_event_id=processed_event.processed_event_id,
                            stage=ExperimentStage.FORECAST.value,
                            variant_name=forecast_entry.get("variant", variant_name),
                            variant_version=forecast_entry.get("version"),
                            source_artifact_id=primary_artifact_id,
                            payload=payload,
                            score=_parse_float(forecast_entry.get("score")),
                            artifact_uri=forecast_entry.get("artifact_uri"),
                        )
                    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay pipeline debug dump payloads")
    parser.add_argument("--run-id", required=True, help="Pipeline run identifier to replay")
    parser.add_argument(
        "--dump-dir",
        help="Directory containing debug dumps (defaults to PIPELINE_DEBUG_DUMP_DIR)",
    )
    parser.add_argument(
        "--event",
        action="append",
        dest="events",
        help="Limit replay to specific event IDs (can be passed multiple times)",
    )
    parser.add_argument(
        "--skip-market-upsert",
        action="store_true",
        help="Skip updating base market snapshots while replaying",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse dumps without writing to the database",
    )

    args = parser.parse_args()

    settings = get_settings()
    base_dir = args.dump_dir or settings.pipeline_debug_dump_dir
    if not base_dir:
        raise SystemExit("Debug dump directory must be provided via --dump-dir or settings")

    dump_root = Path(base_dir).expanduser().resolve()
    run_dir = dump_root / args.run_id
    if not run_dir.exists():
        raise SystemExit(f"Run directory {run_dir} does not exist")

    includes = set(args.events or [])

    events = _load_run_dumps(run_dir, includes)
    if not events:
        logger.info("No events found for run %s; nothing to replay", args.run_id)
        return

    logger.info(
        "Discovered %d events across %d suites in %s",
        len(events),
        len({suite for event in events.values() for suite in event.suites}),
        run_dir,
    )

    init_db()

    for event in events.values():
        try:
            _persist_event_bundle(
                run_id=args.run_id,
                event=event,
                skip_market_upsert=args.skip_market_upsert,
                dry_run=args.dry_run,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to replay event %s", event.event_key)


if __name__ == "__main__":
    main()

