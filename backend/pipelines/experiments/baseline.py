from __future__ import annotations

from app.crud import NormalizedMarket

from .base import Experiment, ExperimentResult
from ..context import PipelineContext


class BaselineSnapshotExperiment(Experiment):
    """Capture normalized market snapshot for downstream auditing."""

    name = "baseline_snapshot"
    version = "1.0"
    description = "Persist normalized Polymarket market and contract payloads."

    def run(self, market: NormalizedMarket, context: PipelineContext) -> ExperimentResult:
        contract_payloads = [
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
        ]
        payload = {
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
            "contracts": contract_payloads,
        }
        return ExperimentResult(
            name=self.name,
            version=self.version,
            payload=payload,
        )
