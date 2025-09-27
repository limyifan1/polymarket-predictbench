# Forecast Experimentation Architecture

## Overview
The daily pipeline now treats forecasting as a two-stage workflow. Research strategies collect external context for a market event, and forecast strategies transform those artifacts into probability estimates. Suites provide an ergonomic way to bundle research/forecast variants, run ablations, and persist structured results. This document captures the technical design implemented in the repository.

## Goals
- Run multiple research and forecast variants per market without editing pipeline plumbing.
- Enable mix-and-match experimentation (e.g. several forecast prompts consuming the same research artifact).
- Persist research artifacts and forecasts with explicit provenance for downstream evaluation.
- Support selective execution (research-only, forecast-only, subset of suites/variants) for rapid iteration.
- Maintain the existing ingestion + persistence flow so new strategies compose with the baseline snapshot logic.

## Core Building Blocks
### Strategies
Located in `backend/pipelines/experiments/base.py`:
- `ResearchStrategy`: protocol for strategies that emit `ResearchOutput` (payload, optional diagnostics, optional artifact URI/hash).
- `ForecastStrategy`: protocol for strategies that emit one or more `ForecastOutput` objects and declare required research variants via `requires`.
- `ForecastOutput` carries the target `market_id`, an `outcome_prices` map, and a natural-language `reasoning` string. The pipeline persists only `{"outcomePrices", "reasoning"}` for each forecast result; linkage back to the market is handled via the foreign key on `experiment_results`.
- `ResearchOutput` remains a lightweight container for research payloads and diagnostics.

### Suites
Suites are assembled via the helpers in `backend/pipelines/experiments/suites.py`. The most ergonomic option is the declarative API:

```python
from pipelines.experiments.suites import DeclarativeExperimentSuite, strategy, suite

class ExampleSuite(DeclarativeExperimentSuite):
    suite_id = "demo"
    research_factories = (
        strategy(MyResearchStrategy, temperature=0.4),
    )
    forecast_factories = (
        strategy(MyForecastStrategy),
    )
```

`strategy(...)` accepts an instance, class, or callable (plus optional kwargs) and instantiates a fresh strategy when the suite is created. Under the hood `DeclarativeExperimentSuite` materialises the strategies and performs the same validation as before (duplicate name detection, dependency checks). Experiment names recorded in the DB follow `"{suite_id}:{stage}:{variant}"`.

Prefer the `suite(...)` helper when no subclass-specific behaviour is required:

```python
from pipelines.experiments.suites import strategy, suite

openai_suite = suite(
    "openai",
    version="0.2",
    description="Experimental OpenAI-backed research + forecast flow",
    research=[
        strategy(OpenAIWebSearchResearch),
        strategy(AtlasResearchSweep),
        strategy(HorizonSignalTimeline),
    ],
    forecasts=[
        strategy(GPT5ForecastStrategy),
    ],
)
```

Both patterns produce a `BaseExperimentSuite` subclass instance; the helper merely removes the boilerplate of defining an empty class body.

When extra control is required you can still subclass `BaseExperimentSuite` directly and override `_build_research_strategies()` / `_build_forecast_strategies()`; the declarative version simply wraps that pattern with less boilerplate.

The default suite (`BaselineSnapshotSuite` in `backend/pipelines/experiments/baseline.py`) provides the legacy snapshot logic as a forecast strategy with no research dependencies.

#### Execution semantics
- **Research stage**: every research strategy listed in the suite runs for each event bucket that flows through the pipeline. A strategy may raise `ExperimentSkip` to opt out for a specific event; otherwise a structured `ResearchOutput` is persisted and keyed by the strategy's `name` attribute.
- **Forecast stage**: forecast strategies run for the same event after their `requires` dependencies are satisfied. The dependency list must reference research strategy names. Multiple forecasts can share the same research artifact, and a single forecast can depend on more than one research variant.
- **Fan-out**: suites may combine multiple research and forecast entries. Each research strategy emits exactly one artifact per event. Forecast strategies are evaluated once per event and generate one or more `ForecastOutput` objects (one per market).
- **Partial failures**: when a research strategy fails, only dependent forecasts are skipped. Other research/forecast variants in the suite continue to run.

Create a **new research strategy** when the prompt, tooling, or output schema changes. Create a **new forecast strategy** when a different model prompt or aggregation logic is required. Create a **new suite** when you want a different combination of strategies to run together (e.g., a lightweight suite for production and a heavier, experimental suite for offline analysis). A single suite can host many strategies as long as the dependency graph remains acyclic.

### Registry
`backend/pipelines/experiments/registry.py` centralises configuration in code. `REGISTERED_SUITE_BUILDERS` is an ordered tuple of callables that each return a fresh `BaseExperimentSuite`. `load_suites(requested=None)` instantiates every builder and optionally filters by suite ID (used by the CLI's `--suite` flag). Adding or removing a suite is a matter of editing that tuple—no environment variables or stringly typed imports required.

#### YAML format
`backend/pipelines/experiments/configuration.py` parses suite definitions from YAML. The schema mirrors the in-code helpers:

```yaml
suites:
  - suite_id: openai
    version: "0.2"
    description: Experimental OpenAI-backed research + forecast flow
    research:
      - target: pipelines.experiments.openai:OpenAIWebSearchResearch
      - target: pipelines.experiments.openai:AtlasResearchSweep
      - target: pipelines.experiments.openai:HorizonSignalTimeline
    forecasts:
      - target: pipelines.experiments.openai:GPT5ForecastStrategy
```

- Each `research` and `forecasts` entry may be a string (`module:Attribute`) or a mapping with optional `args`/`kwargs` fields that are forwarded when instantiating the strategy.
- All research strategies listed run for every event. Forecast strategies run for the same events once their `requires` dependencies (strategy names) succeed. Missing dependencies raise an error during suite construction so misconfigurations are caught early.
- To run multiple suites from one YAML file, append additional entries to the `suites` array. Use separate suites when you want to opt-in/out of different experiment bundles via CLI flags or environment variables.
- YAML is intentionally optional. It cannot reuse helper functions, share partially applied strategies, or benefit from type checking. Use it sparingly for non-engineering stakeholders; the code-first registry keeps experiment wiring explicit and easier to refactor.

## Configuration
Configuration lives in `pipelines/experiments/registry.py`. The tuple `REGISTERED_SUITE_BUILDERS` defines the suites that run for every pipeline invocation, and `load_suites()` materialises them on demand. CLI filters (`--suite`, `--include-*`, `--stage`) operate on the instantiated suite objects. The YAML loader remains for advanced scenarios, but prefer editing the registry directly for type-checked, discoverable configuration.

## Pipeline Flow (`backend/pipelines/daily_run.py`)
1. Parse CLI args (window/target date, dry-run, limit, summary path, optional `--suite`, `--stage`, `--include-research`, `--include-forecast`).
2. Load suites via `load_suites`, filter by `--suite` when provided, and compute the active stage set:
   - `--stage research` → only research stage executes.
   - `--stage forecast` → only forecast stage executes.
   - `--stage both` (default) → full pipeline.
3. Materialize `ExperimentRunMeta` records (one per strategy) with deterministic experiment names and identifiers. These populate `experiment_runs` once per pipeline invocation.
4. Ingestion / normalization is unchanged: markets are grouped by event ID and fed into the experiment harness.
5. For each suite and event group, `_run_suite_for_group`:
   - Executes research strategies (if the stage is active and not filtered) and memoizes `ResearchExecutionRecord` objects keyed by strategy name.
   - Executes forecast strategies once required research variants are available, producing `ForecastExecutionRecord` items.
   - Strategies may raise `ExperimentSkip` to opt out for a group; errors propagate as `ExperimentExecutionError` and mark the event as failed.
6. When forecasts are required but none succeed, the markets in that event are marked with a `no_forecast_results` failure; otherwise the run proceeds to persistence.
7. Persistence (non dry-run):
   - `processed_events` / `processed_markets` mirror previous behaviour.
   - Each research result is stored twice: as a row in `research_artifacts` (for structured provenance) and as an `experiment_results` entry with `stage='research'`.
   - Forecast outputs become `experiment_results` with `stage='forecast'`. Dependency mappings are embedded under `_research_artifacts` when artifacts exist; a single dependency also populates `source_artifact_id` for quick joins.
   - `crud.upsert_market` keeps the canonical market snapshot current.
8. After the run, `experiment_runs` receive final statuses (`completed`, `skipped`, or `failed`) with accumulated error messages.

## Data Model Updates
- `ExperimentStage` enum added to `app/models.py` alongside new stage columns on `experiment_runs` and `experiment_results` (auto-added in `_apply_schema_updates`).
- `experiment_results` gains `variant_name`, `variant_version`, and `source_artifact_id` for provenance.
- New `ResearchArtifactRecord` table (`research_artifacts`) tracks artifacts with payload, optional URI, and hash for dedupe.
- `ProcessedEvent` / `ProcessedMarket` now relationship to `ResearchArtifactRecord` so artifacts can be queried alongside forecasts.

## CRUD Helpers (`backend/app/crud.py`)
- `ExperimentRunInput` / `ExperimentResultInput` extended to accept stage + variant metadata.
- `record_research_artifact` persists artifacts and returns the ORM record.
- `record_experiment_result` stores stage-aware results and optional source-artifact linkage.

## CLI Enhancements
- `--suite <id>` (repeatable): run only specific suites.
- `--stage {research,forecast,both}`: limit execution to selected stages.
- `--include-research foo,bar` and `--include-forecast promptA,promptB`: filter variants by name or `suite_id:variant`. Filters apply before execution; filtered variants are marked as `skipped` in run metadata.
- `--debug-dump-dir ./tmp/dumps`: emit per-event JSON payloads for quick inspection (defaults to `PIPELINE_DEBUG_DUMP_DIR`; add `--no-debug-dump` to skip).

## Artifact Layout
No additional filesystem storage is required. Artifacts live in the database and, optionally, suites can set `artifact_uri` values pointing at external blobs (e.g. Supabase storage) when needed.

## Baseline Compatibility
- The baseline snapshot continues to run via `BaselineSnapshotSuite` and produces the same payload as before.
- If a run excludes the forecast stage, research artifacts still persist (when writes are enabled) so future forecast-only jobs can reference them once we add replay tooling.

## Future Extensions
- Add orchestration helpers (`pipelines/experiments/runner.py`) for offline ablations that replay forecasts against stored research artifacts.
- Expand `SuiteInventory` to support post-processing stages (calibration, evaluation) when required.
- Implement caching for expensive research strategies when multiple suites share the same variant.
- Enrich the summary artifact with per-suite success counts and latency metrics.

## Summary
The implemented architecture keeps ingestion untouched while providing a clear structure for research and forecast experimentation. Suites encapsulate stage variants, strategy outputs are memoized within each event group, and both research artifacts and forecasts persist with explicit provenance. CLI filters and stage gating enable fast iteration without touching pipeline internals.
