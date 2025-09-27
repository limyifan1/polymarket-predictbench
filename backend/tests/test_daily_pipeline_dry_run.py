from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Iterable

from pipelines.daily_run import run_pipeline
from pipelines.experiments.base import ForecastOutput, ResearchOutput
from pipelines.experiments.suites import DeclarativeExperimentSuite, strategy


class DummyResearchStrategy:
    name = "baseline_research"
    version = "0.0.1"
    description = "stub research"

    def run(self, group, context) -> ResearchOutput:
        market_ids = [market.market_id for market in group.markets]
        return ResearchOutput(payload={"market_ids": market_ids})


class DummyForecastStrategy:
    name = "baseline_forecast"
    version = "0.0.1"
    description = "stub forecast"
    requires = ("baseline_research",)

    def run(self, group, research_artifacts, context) -> Iterable[ForecastOutput]:
        outputs: list[ForecastOutput] = []
        for market in group.markets:
            prices = {contract.contract_id: 0.5 for contract in market.contracts}
            outputs.append(
                ForecastOutput(
                    market_id=market.market_id,
                    outcome_prices=prices,
                    reasoning="stub output",
                )
            )
        return outputs


class DummySuite(DeclarativeExperimentSuite):
    def __init__(self) -> None:
        super().__init__(
            suite_id="dummy",
            research=[strategy(lambda: DummyResearchStrategy())],
            forecasts=[strategy(lambda: DummyForecastStrategy())],
        )


class StubClient:
    def __init__(self, markets: Iterable[dict[str, Any]]) -> None:
        self._markets = list(markets)
        self.closed = False

    def iter_markets(self):
        for market in self._markets:
            yield market

    def close(self) -> None:
        self.closed = True


class DummyProcessingRepository:
    def __init__(self, session: object) -> None:
        self.session = session
        self.failures: list[dict[str, Any]] = []

    def create_processing_run(self, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(processing_run_id="run")

    def record_experiment_run(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def record_processing_failure(self, **kwargs: Any) -> None:
        self.failures.append(kwargs)

    def record_processed_event(self, input_obj):
        return SimpleNamespace(processed_event_id=input_obj.processed_event_id)

    def record_processed_market(self, input_obj):
        return SimpleNamespace(processed_market_id=input_obj.processed_market_id)

    def record_research_artifact(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def record_experiment_result(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def finalize_processing_run(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class DummyMarketRepository:
    def __init__(self, session: object) -> None:
        self.session = session
        self.upserted = []

    def upsert_market(self, market) -> None:
        self.upserted.append(market)


@contextmanager
def dummy_session_scope():
    yield object()


def test_daily_pipeline_dry_run_processes_markets(
    sample_market_payload,
    pipeline_args,
    test_settings,
    tmp_path,
):
    stub_markets = [sample_market_payload]

    summary = run_pipeline(
        pipeline_args,
        test_settings,
        suites=[DummySuite()],
        client_factory=lambda: StubClient(stub_markets),
        session_factory=dummy_session_scope,
        init_db_fn=lambda: None,
        processing_repo_factory=DummyProcessingRepository,
        market_repo_factory=DummyMarketRepository,
    )

    assert summary.total_markets == 1
    assert summary.processed_markets == 1
    assert summary.failed_markets == 0

    stats = summary.suite_stats["dummy"]
    assert stats.research.completed == 1
    assert stats.forecast.completed == 1

    summary_path = pipeline_args.summary_path
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["total_markets"] == 1
    assert payload["failed_markets"] == 0
