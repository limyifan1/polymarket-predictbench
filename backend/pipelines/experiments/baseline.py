from __future__ import annotations

from .base import EventMarketGroup, Experiment, ExperimentResult
from ..context import PipelineContext


class BaselineSnapshotExperiment(Experiment):
    """Capture normalized market snapshot for downstream auditing."""

    name = "baseline_snapshot"
    version = "1.0"
    description = "Persist normalized Polymarket market and contract payloads."

    def run(self, group: EventMarketGroup, context: PipelineContext) -> ExperimentResult:
        event_payload = None
        if group.event:
            event = group.event
            event_payload = {
                "event_id": event.event_id,
                "slug": event.slug,
                "title": event.title,
                "description": event.description,
                "start_time": event.start_time.isoformat() if event.start_time else None,
                "end_time": event.end_time.isoformat() if event.end_time else None,
                "icon_url": event.icon_url,
                "series_slug": event.series_slug,
                "series_title": event.series_title,
                "raw_data": event.raw_data,
            }

        markets_payload = [
            {
                "market": {
                    "market_id": market.market_id,
                    "slug": market.slug,
                    "question": market.question,
                    "category": market.category,
                    "sub_category": market.sub_category,
                    "open_time": market.open_time.isoformat() if market.open_time else None,
                    "close_time": market.close_time.isoformat() if market.close_time else None,
                    "volume_usd": market.volume_usd,
                    "liquidity_usd": market.liquidity_usd,
                    "fee_bps": market.fee_bps,
                    "status": market.status,
                    "description": market.description,
                    "icon_url": market.icon_url,
                    "raw_data": market.raw_data,
                },
                "contracts": [
                    {
                        "contract_id": contract.contract_id,
                        "name": contract.name,
                        "outcome_type": contract.outcome_type,
                        "current_price": contract.current_price,
                        "confidence": contract.confidence,
                        "implied_probability": contract.implied_probability,
                        "raw_data": contract.raw_data,
                    }
                    for contract in market.contracts
                ],
            }
            for market in group.markets
        ]

        payload = {
            "event": event_payload,
            "markets": markets_payload,
        }
        return ExperimentResult(
            name=self.name,
            version=self.version,
            payload=payload,
        )
