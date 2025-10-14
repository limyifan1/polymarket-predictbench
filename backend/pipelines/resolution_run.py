"""Standalone job that reconciles market and event resolutions."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from loguru import logger

from app.core.config import Settings, get_settings
from app.db import init_db
from app.models import MarketStatus
from app.repositories import MarketRepository
from ingestion.client import PolymarketClient
from ingestion.normalize import normalize_market
from ingestion.service import session_scope


@dataclass(slots=True)
class MarketResolutionSnapshot:
    market_id: str
    is_resolved: bool
    resolved_at: datetime | None = None
    resolution_source: str | None = None
    winning_outcome: str | None = None
    payout_token: str | None = None
    resolution_tx_hash: str | None = None
    resolution_notes: str | None = None


@dataclass(slots=True)
class ResolutionSummary:
    checked_markets: int = 0
    newly_resolved: int = 0
    already_resolved: int = 0
    still_open: int = 0
    updated_events: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_markets": self.checked_markets,
            "newly_resolved": self.newly_resolved,
            "already_resolved": self.already_resolved,
            "still_open": self.still_open,
            "updated_events": self.updated_events,
            "failures": self.failures,
        }


class ResolutionPipeline:
    """Coordinate resolution reconciliation as an independent pipeline."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = PolymarketClient(
            base_url=str(self.settings.polymarket_base_url),
            markets_path=self.settings.polymarket_markets_path,
            page_size=1,
        )

    def run(
        self,
        *,
        limit: int | None = None,
        batch_size: int | None = None,
        event_ids: Sequence[str] | None = None,
        recent_hours: float | None = None,
    ) -> ResolutionSummary:
        init_db()
        summary = ResolutionSummary()
        batch_size = batch_size or self.settings.pipeline_resolution_batch_size
        forced_events = list(self.settings.pipeline_resolution_force_event_ids)
        target_event_ids = set(event_ids or ()) | set(forced_events)
        event_filter = list(target_event_ids) if target_event_ids else None
        recent_cutoff = None
        if recent_hours:
            recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=recent_hours)

        logger.info(
            "Starting resolution sweep: limit={}, batch_size={}, event_filter={}, recent_cutoff={}",
            limit,
            batch_size,
            event_filter,
            recent_cutoff,
        )

        affected_events: set[str] = set()

        with session_scope() as session:
            repo = MarketRepository(session)
            candidates = repo.get_unresolved_markets(
                limit=limit,
                event_ids=event_filter,
                recent_cutoff=recent_cutoff,
            )
            if not candidates:
                logger.info("No unresolved markets found; sweep completed with no updates")
                return summary

            logger.info("Resolution sweep evaluating {} markets", len(candidates))
            for chunk in _chunked(candidates, batch_size):
                for market in chunk:
                    summary.checked_markets += 1
                    snapshot = self._fetch_snapshot(market.market_id)
                    if snapshot is None:
                        summary.failures.append(
                            {"market_id": market.market_id, "reason": "resolution data unavailable"}
                        )
                        continue

                    now = datetime.now(timezone.utc)
                    if not snapshot.is_resolved:
                        if market.last_synced_at != now:
                            market.last_synced_at = now
                        summary.still_open += 1
                        continue

                    was_resolved = bool(market.is_resolved)
                    self._apply_snapshot(market, snapshot, checked_at=now)

                    if not was_resolved and market.is_resolved:
                        summary.newly_resolved += 1
                        if market.event_id:
                            affected_events.add(market.event_id)
                    else:
                        summary.already_resolved += 1

            for event_id in affected_events:
                repo.refresh_event_resolution(event_id)

        summary.updated_events = len(affected_events)
        logger.info(
            "Resolution sweep finished: checked={}, newly_resolved={}, events_updated={}",
            summary.checked_markets,
            summary.newly_resolved,
            summary.updated_events,
        )
        return summary

    def close(self) -> None:
        self._client.close()

    def _fetch_snapshot(self, market_id: str) -> MarketResolutionSnapshot | None:
        payload = self._client.fetch_market(market_id)
        if not payload:
            return None

        normalized = normalize_market(payload)
        if normalized is None:
            return None

        return MarketResolutionSnapshot(
            market_id=market_id,
            is_resolved=bool(normalized.is_resolved),
            resolved_at=normalized.resolved_at,
            resolution_source=normalized.resolution_source,
            winning_outcome=normalized.winning_outcome,
            payout_token=normalized.payout_token,
            resolution_tx_hash=normalized.resolution_tx_hash,
            resolution_notes=normalized.resolution_notes,
        )

    def _apply_snapshot(
        self, market, snapshot: MarketResolutionSnapshot, *, checked_at: datetime
    ) -> bool:
        changed = False

        if not market.is_resolved:
            market.is_resolved = True
            changed = True

        if market.status != MarketStatus.RESOLVED.value:
            market.status = MarketStatus.RESOLVED.value
            changed = True

        if snapshot.resolved_at and market.resolved_at != snapshot.resolved_at:
            market.resolved_at = snapshot.resolved_at
            changed = True

        if snapshot.resolution_source and market.resolution_source != snapshot.resolution_source:
            market.resolution_source = snapshot.resolution_source
            changed = True

        if snapshot.winning_outcome and market.winning_outcome != snapshot.winning_outcome:
            market.winning_outcome = snapshot.winning_outcome
            changed = True

        if snapshot.payout_token and market.payout_token != snapshot.payout_token:
            market.payout_token = snapshot.payout_token
            changed = True

        if snapshot.resolution_tx_hash and market.resolution_tx_hash != snapshot.resolution_tx_hash:
            market.resolution_tx_hash = snapshot.resolution_tx_hash
            changed = True

        if snapshot.resolution_notes and market.resolution_notes != snapshot.resolution_notes:
            market.resolution_notes = snapshot.resolution_notes
            changed = True

        if market.last_synced_at != checked_at:
            market.last_synced_at = checked_at
            changed = True

        return changed


def _chunked(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    if size <= 0:
        yield items
        return
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile market and event resolutions without running the daily pipeline",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of markets to check")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Override the batch size used when fetching and writing resolution updates",
    )
    parser.add_argument(
        "--event-id",
        dest="event_ids",
        action="append",
        help="Restrict the sweep to specific event IDs (can be provided multiple times)",
    )
    parser.add_argument(
        "--recent-hours",
        type=float,
        default=None,
        help="Only re-check markets updated within the last N hours",
    )
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=None,
        help="Optional path where a JSON summary report will be written",
    )
    return parser.parse_args()


def _write_summary(summary: ResolutionSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary.to_dict(), default=str, indent=2))
    logger.info("Resolution summary written to {}", path)


def main() -> ResolutionSummary:
    args = _parse_args()
    settings = get_settings()
    pipeline = ResolutionPipeline(settings)
    try:
        summary = pipeline.run(
            limit=args.limit,
            batch_size=args.batch_size,
            event_ids=args.event_ids,
            recent_hours=args.recent_hours,
        )
    finally:
        pipeline.close()

    if args.summary_path:
        _write_summary(summary, args.summary_path)
    return summary


if __name__ == "__main__":
    main()

