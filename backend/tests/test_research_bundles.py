"""Unit tests covering research bundle grouping and execution reuse."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from app.domain import NormalizedMarket
from app.models import ExperimentStage
from pipelines.context import PipelineContext
from pipelines.daily_run import (
    _build_research_bundles,
    _execute_research_bundles,
    _prepare_experiment_metadata,
)
from pipelines.experiments.base import EventMarketGroup, ResearchOutput
from pipelines.experiments.suites import DeclarativeExperimentSuite, strategy


class FakeSettings:
    """Minimal settings stub that exposes experiment overrides."""

    def __init__(self, overrides: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self._overrides = dict(overrides or {})
        self.llm_default_provider = "openai"

    def experiment_config(self, experiment_name: str) -> Mapping[str, Any]:
        return self._overrides.get(experiment_name, {})


class TrackingResearchStrategy:
    """Research strategy with a shared identity that records executions."""

    name = "shared_research"
    version = "1.0"
    description = "tracking stub"
    shared_identity = "catalog:shared:v1"

    def __init__(self, *, label: str, tracker: list[str]) -> None:
        self.label = label
        self.tracker = tracker
        self._experiment_name: str | None = None

    def run(self, group: EventMarketGroup, context: PipelineContext) -> ResearchOutput:
        del group, context
        self.tracker.append(self.label)
        return ResearchOutput(payload={"label": self.label})


class SharedSuite(DeclarativeExperimentSuite):
    """Suite that exposes the tracking strategy for research."""

    def __init__(self, suite_id: str, tracker: list[str]) -> None:
        super().__init__(
            suite_id=suite_id,
            research=[strategy(lambda: TrackingResearchStrategy(label=suite_id, tracker=tracker))],
            forecasts=[],
        )


def _make_context(settings: FakeSettings) -> PipelineContext:
    return PipelineContext(
        run_id="run",
        run_date=date(2024, 1, 1),
        target_date=date(2024, 1, 1),
        window_days=0,
        settings=settings,
        db_session=SimpleNamespace(),
        dry_run=True,
    )


def _make_group() -> EventMarketGroup:
    market = NormalizedMarket(
        market_id="m-1",
        slug=None,
        question="sample",
        category=None,
        sub_category=None,
        open_time=None,
        close_time=None,
        volume_usd=None,
        liquidity_usd=None,
        fee_bps=None,
        status="open",
        description=None,
        icon_url=None,
        event=None,
        contracts=[],
        raw_data=None,
    )
    return EventMarketGroup(event=None, markets=[market])


def _prepare(
    suites: Sequence[SharedSuite],
) -> tuple[PipelineContext, dict[tuple[str, ExperimentStage, str], Any]]:
    _, meta_index = _prepare_experiment_metadata(suites)
    overrides: dict[str, Mapping[str, Any]] = {}
    settings = FakeSettings(overrides)
    context = _make_context(settings)
    return context, meta_index


def test_shared_bundles_reuse_single_execution() -> None:
    tracker: list[str] = []
    suites = (SharedSuite("suite_a", tracker), SharedSuite("suite_b", tracker))
    context, meta_index = _prepare(suites)

    bundles = _build_research_bundles(suites, context, meta_index)

    assert len(bundles) == 1
    bundle = bundles[0]
    assert bundle.shared is True
    assert bundle.identity == "catalog:shared:v1"
    assert {member.suite_id for member in bundle.members} == {"suite_a", "suite_b"}

    records = _execute_research_bundles(
        suites,
        bundles,
        _make_group(),
        context,
        active_stages={ExperimentStage.RESEARCH},
        enabled_research=None,
    )

    assert len(tracker) == 1, "shared bundle should execute underlying strategy once"

    record_a = records["suite_a"]["shared_research"]
    record_b = records["suite_b"]["shared_research"]
    assert record_a.output is record_b.output
    assert record_a.bundle_identity == "catalog:shared:v1"
    assert record_b.bundle_identity == "catalog:shared:v1"

    meta_a = meta_index[("suite_a", ExperimentStage.RESEARCH, "shared_research")]
    meta_b = meta_index[("suite_b", ExperimentStage.RESEARCH, "shared_research")]
    assert meta_a.success_count == 1
    assert meta_b.success_count == 1
    assert meta_a.failure_count == 0
    assert meta_b.failure_count == 0
    assert meta_a.skip_count == 0
    assert meta_b.skip_count == 0


def test_different_overrides_disable_sharing() -> None:
    tracker: list[str] = []
    suites = (SharedSuite("suite_a", tracker), SharedSuite("suite_b", tracker))
    experiment_metas, meta_index = _prepare_experiment_metadata(suites)

    overrides = {
        meta_index[("suite_a", ExperimentStage.RESEARCH, "shared_research")].experiment_name: {
            "request_options": {"temperature": 0.1}
        },
        meta_index[("suite_b", ExperimentStage.RESEARCH, "shared_research")].experiment_name: {
            "request_options": {"temperature": 0.9}
        },
    }
    context = _make_context(FakeSettings(overrides))

    bundles = _build_research_bundles(suites, context, meta_index)

    assert len(bundles) == 2
    assert all(not bundle.shared for bundle in bundles)

    records = _execute_research_bundles(
        suites,
        bundles,
        _make_group(),
        context,
        active_stages={ExperimentStage.RESEARCH},
        enabled_research=None,
    )

    assert len(tracker) == 2, "strategies should execute independently when overrides differ"

    record_a = records["suite_a"]["shared_research"]
    record_b = records["suite_b"]["shared_research"]
    assert record_a.bundle_identity is None
    assert record_b.bundle_identity is None
    assert record_a.output.payload == {"label": "suite_a"}
    assert record_b.output.payload == {"label": "suite_b"}

    meta_a = meta_index[("suite_a", ExperimentStage.RESEARCH, "shared_research")]
    meta_b = meta_index[("suite_b", ExperimentStage.RESEARCH, "shared_research")]
    assert meta_a.success_count == 1
    assert meta_b.success_count == 1
    assert meta_a.failure_count == 0
    assert meta_b.failure_count == 0
    assert meta_a.skip_count == 0
    assert meta_b.skip_count == 0
