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

Gemini experiments reuse the same declarative helper while swapping in Gemini
strategies:

```python
from pipelines.experiments.gemini import (
    GeminiForecastStrategy,
    GeminiWebSearchResearch,
)
from pipelines.experiments.suites import strategy, suite

gemini_suite = suite(
    "gemini",
    research=(strategy(GeminiWebSearchResearch),),
    forecasts=(
        strategy(
            GeminiForecastStrategy,
            requires=("gemini_web_search",),
        ),
    ),
)
```

`strategy(...)` accepts a class, instance, or factory callable plus kwargs. Each
suite instantiation creates fresh strategy objects, so they remain stateless
between runs.

#### Strategy variants & overrides
- Pass `alias` to `strategy(...)` to rename a variant without subclassing. This
  keeps names unique when you want multiple versions of the same class in one
  suite (`alias="gpt41_forecast"`).
- Override metadata inline with `version=` / `description=` when the variant
  deviates from the base prompt or model choice.
- Supply `overrides={...}` to bake provider/model tweaks into the suite. The
  mapping is stored under the experiment's full name
  (`suite:stage:strategy`) and fed to `resolve_llm_request`, so you can swap
  models or request options without touching `.env`.
- Example snippet:

  ```python
  openai_suite = suite(
      "openai",
      research=(strategy(OpenAIWebSearchResearch),),
      forecasts=(
          strategy(
              GPT5ForecastStrategy,
              requires=("openai_web_search",),
          ),
          strategy(
              GPT5ForecastStrategy,
              requires=("openai_web_search", "atlas_research_sweep"),
              alias="gpt41_forecast",
              version="0.2-gpt4.1",
              overrides={"model": "gpt-4.1"},
          ),
      ),
  )
  ```

  The pipeline now runs two forecast variants side-by-side; `gpt41_forecast`
  automatically receives the GPT‑4.1 override during execution.

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
- When switching providers, review default tools: Gemini research stages now
  opt into the `google_search` grounding tool by default (the provider will
  downgrade to `google_search_retrieval` automatically for legacy 1.x models).
  Supply `tools=[]` or override the tool if you need to disable or customise
  the grounding behaviour.

### Per-run overrides for ablations
- Use `--experiment-override` on the pipeline CLI to swap models or tweak
  request options without touching `.env`. Experiments use the pattern
  `suite:stage:strategy.key=value`, so running a research variant on GPT-4.1
  looks like:

  ```bash
  uv run python -m pipelines.daily_run --dry-run --limit 5 \
    --experiment-override openai:research:openai_web_search.model="gpt-4.1-mini"
  ```

- Repeat the flag to override multiple strategies in a single run. Nested keys
  are supported (`request_options.temperature=0.4`).
- Store larger matrices of overrides in JSON and load them with
  `--experiment-override-file overrides.json`:

  ```json
  {
    "openai:research:openai_web_search": {"model": "gpt-4o-mini"},
    "openai:forecast:gpt5_forecast": {"model": "gpt-4.1"}
  }
  ```

- Combine these flags with `--suite`/`--include-*` to iterate through model
  ablations quickly while reusing the same strategy code.

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
