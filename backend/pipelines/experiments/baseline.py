from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..context import PipelineContext
from .base import EventMarketGroup, ForecastOutput, ForecastStrategy, ResearchOutput
from .suites import DeclarativeExperimentSuite, strategy


@dataclass(slots=True)
class BaselineSnapshotForecast(ForecastStrategy):
    """Capture normalized market snapshot for downstream auditing."""

    requires: tuple[str, ...] = ()

    name: str = "baseline_snapshot"
    version: str = "1.0"
    description: str | None = "Persist normalized Polymarket market and contract payloads."

    def run(
        self,
        group: EventMarketGroup,
        research_artifacts: Mapping[str, ResearchOutput],
        context: PipelineContext,
    ) -> list[ForecastOutput]:
        outputs: list[ForecastOutput] = []
        for market in group.markets:
            outcome_prices: dict[str, float | None] = {
                contract.name: float(contract.current_price) if contract.current_price is not None else None
                for contract in market.contracts
            }
            reasoning = "Baseline snapshot of Polymarket order book; no modeled forecast applied."
            outputs.append(
                ForecastOutput(
                    market_id=market.market_id,
                    outcome_prices=outcome_prices,
                    reasoning=reasoning,
                )
            )
        return outputs


class BaselineSnapshotSuite(DeclarativeExperimentSuite):
    """Default suite providing baseline snapshot persistence."""

    suite_id = "baseline"
    version = "1.0"
    description = "Persist normalized market snapshots without additional research."

    research_factories = ()
    forecast_factories = (strategy(BaselineSnapshotForecast),)


__all__ = ["BaselineSnapshotSuite", "BaselineSnapshotForecast"]
