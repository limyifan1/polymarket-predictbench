# Experiments Guide

Experiment suites power the research and forecast workflow. This guide explains
the key abstractions, how to add new strategies, and how to work with multiple
LLM providers.

## Strategy interfaces
Located in `backend/pipelines/experiments/base.py`.

| Interface | Purpose | Key attributes |
| --- | --- | --- |
| `ResearchStrategy` | Collect external context for an event. | `name`, `version`, `description`, `run(group, context)` returning `ResearchOutput`. |
| `ForecastStrategy` | Convert research artifacts into probability forecasts. | `name`, `version`, `requires`, `run(group, artifacts, context)` returning `ForecastOutput`. |
| `ResearchOutput` | Container for structured research payloads. | `payload`, `diagnostics`, optional `artifact_uri` / `artifact_hash`. |
| `ForecastOutput` | Forecast for a single market. | `market_id`, `outcome_prices`, `reasoning`, optional `artifact_uri`. |

Raise `ExperimentSkip` inside `run()` when a strategy should opt out for a
specific event without failing the entire suite. Unexpected exceptions are
wrapped in `ExperimentExecutionError` and recorded as failures.

## Suite patterns
Defined in `backend/pipelines/experiments/suites.py` and registered via
`pipelines/experiments/registry.py`.

### Declarative suites
Use the `suite(...)` helper for the most concise syntax:

```python
from pipelines.experiments.suites import strategy, suite
from pipelines.experiments import baseline

baseline_suite = suite(
    "baseline",
    version="0.1",
    description="Snapshot without LLM research",
    research=[],
    forecasts=[strategy(baseline.BaselineSnapshotStrategy)],
)
```

`strategy(...)` accepts a class, instance, or factory callable plus kwargs. Each
suite instantiation creates fresh strategy objects, so they remain stateless
between runs.

### Custom suites
Subclass `DeclarativeExperimentSuite` when you need additional logic (shared
helpers, dynamic strategy wiring) or fall back to overriding the `_build_*`
methods from `BaseExperimentSuite` for maximum control.

### Registry
Add or remove suites by editing `REGISTERED_SUITE_BUILDERS` in
`pipelines/experiments/registry.py`. The daily pipeline imports the registry
directly, so updating the tuple is enough to change the executed suites.

## Dependency model
- Research strategies run for every event bucket. Their outputs are keyed by
  strategy `name`.
- Forecast strategies declare dependencies via the `requires` tuple. They run
  only after all required research artifacts succeed for the event.
- Skipped research strategies cause dependent forecasts to skip. Other suites
  continue executing, so partial failures do not abort the entire run.

## Working with LLM providers
Provider abstractions live in `backend/app/services/llm/`.

- `LLM_DEFAULT_PROVIDER` (env var) selects the fallback provider when strategies
  do not override `provider` explicitly.
- Built-in providers: **OpenAI** and **Gemini**. Configure their API keys via
  `.env` (`OPENAI_API_KEY`, `GEMINI_API_KEY`). Providers expose sensible default
  models per stage (`research` vs `forecast`) but strategies can override
  `model`, `tools`, or other request options per run.
- `resolve_llm_request` prepares an `LLMRequestSpec` that includes provider
  hooks for JSON-mode kwargs, invocation, and usage accounting. Strategies call
  the methods on the request spec rather than importing provider-specific
  helpers.
- When switching providers, review default tools: Gemini does not enable web
  search tooling by default, so strategies requiring search should opt out or
  provide provider-specific overrides.

## Adding a new strategy
1. Implement `ResearchStrategy` or `ForecastStrategy` subclass with descriptive
   `name`/`version` values. Ensure `run()` returns the appropriate output type.
2. Update or create a suite that includes the new strategy via `strategy(...)`.
3. Append the suite builder to `REGISTERED_SUITE_BUILDERS`.
4. Run `uv run python -m pipelines.daily_run --dry-run --limit 5 --suite <id>` to
   verify wiring and payload shape.
5. Update docs and `.env.example` if the strategy requires additional
   configuration (API keys, feature flags, etc.).

## Persisted metadata
- Each strategy execution creates an `experiment_runs` row capturing duration,
  status, and error messages.
- Successful research outputs land in `research_artifacts` with hashes and
  optional URIs, enabling deduplication and external storage.
- Forecast outputs populate `experiment_results` with normalized
  `outcome_prices` and reasoning text. Forecast entries include provenance links
  back to research artifacts when applicable.

Use these tables to evaluate experiment performance, compare suites, or replay
forecasts offline.
