# LLM Call Inventory for the Superforecaster Pipeline

## Why so many requests?
The daily pipeline loads every suite registered in `REGISTERED_SUITE_BUILDERS`, which currently includes the baseline snapshot suite, the OpenAI research/forecast suite, and the superforecaster suite.【F:backend/pipelines/experiments/registry.py†L33-L50】 Only the baseline suite avoids language models, so a full run always executes both OpenAI-heavy suites.

During execution the pipeline groups strategies into "research bundles". Strategies that declare the same `shared_identity` and have identical configuration fingerprints share a single request and reuse the response across suites; otherwise each strategy runs independently.【F:backend/pipelines/daily_run.py†L560-L709】 This sharing is why the OpenAI web-search research prompt only fires once even though both the OpenAI and superforecaster suites depend on it.【F:backend/pipelines/experiments/openai/research_web_search.py†L12-L78】【F:backend/pipelines/experiments/openai/suite.py†L15-L25】【F:backend/pipelines/experiments/superforecaster/suite.py†L14-L24】

## Research stage calls per event group
Research strategies run once for each `EventMarketGroup` (usually an event and all of its markets). Each strategy issues exactly one LLM request via `StructuredLLMResearchStrategy.run()` and `runtime.invoke(...)`.【F:backend/pipelines/experiments/openai/base.py†L90-L220】 For the registered suites the per-group call count is:

| Strategy | Suite(s) | Calls per event group | Notes |
| --- | --- | --- | --- |
| `openai_web_search` | OpenAI + Superforecaster | 1 (shared) | Shared identity ensures a single call reused across both suites.【F:backend/pipelines/experiments/openai/research_web_search.py†L12-L78】【F:backend/pipelines/daily_run.py†L560-L709】 |
| `atlas_research_sweep` | OpenAI | 1 | Independent request for balanced evidence sweep.【F:backend/pipelines/experiments/openai/research_atlas.py†L12-L69】 |
| `horizon_signal_timeline` | OpenAI | 1 | Independent request enumerating past/upcoming catalysts.【F:backend/pipelines/experiments/openai/research_timeline.py†L12-L69】 |
| `superforecaster_briefing` | Superforecaster | 1 | Generates the base-rate anchored briefing.【F:backend/pipelines/experiments/superforecaster/research_briefing.py†L12-L189】 |

**Total research LLM calls:** 4 per event group.

## Forecast stage calls per market
Forecast strategies iterate over every market in the event group and invoke the model inside their loop.【F:backend/pipelines/experiments/openai/forecast_gpt5.py†L111-L190】【F:backend/pipelines/experiments/superforecaster/forecast_calibrated.py†L184-L260】 Because both suites are active, each market triggers:

| Strategy | Suite | Calls per market | Dependencies |
| --- | --- | --- | --- |
| `gpt5_forecast` | OpenAI | 1 | Requires the shared web-search artifact.【F:backend/pipelines/experiments/openai/forecast_gpt5.py†L129-L190】 |
| `superforecaster_delphi` | Superforecaster | 1 | Requires the superforecaster briefing and optionally other research artifacts.【F:backend/pipelines/experiments/superforecaster/forecast_calibrated.py†L204-L260】 |

**Total forecast LLM calls:** `2 × (# of markets in the group)`.

## Putting it together
For a single-market event group the pipeline performs:

- 4 research calls (one per research strategy listed above).
- 2 forecast calls (one from each forecast strategy).

That yields **6 OpenAI API calls** for just one market. For an event with *m* markets the total becomes `4 + 2m` LLM calls.

## Mitigation levers
- **Filter suites:** Run the pipeline with `--suite superforecaster` (or `--suite openai`) to limit execution to the desired suite(s), reducing duplicate forecasts.
- **Prune strategies:** Implement configuration flags (e.g., `--include-research` / `--include-forecast`) to disable specific strategies when debugging or conserving quota; the pipeline already honors these filters when provided.【F:backend/pipelines/daily_run.py†L632-L799】
- **Extend sharing:** Only strategies that opt into `shared_identity` share responses. Additional research variants could adopt shared identities (where safe) to avoid redundant calls across suites.
