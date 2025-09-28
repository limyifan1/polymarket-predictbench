# Parallel LLM Execution & Token Metrics Design

## Goals
- Reduce wall-clock duration of research + forecast stages by running LLM strategies concurrently.
- Preserve existing suite semantics (shared research bundles, deterministic persistence order) and ensure reruns remain idempotent.
- Improve robustness with structured retries and bounded concurrency to avoid overwhelming providers.
- Capture per-run LLM token usage and surface it in pipeline diagnostics and summaries.

## Architecture Overview
- **Execution model**: replace sequential loops in `backend/pipelines/daily_run.py` with a parallel orchestration layer (`LLMTaskExecutor`). The executor uses an `asyncio` event loop with a bounded `asyncio.Semaphore` to limit concurrent LLM requests per provider.
- **Task submission**: research bundle members submit a single task for their canonical strategy; additional members await the same `Future` to reuse shared outputs. Forecast strategies submit one task per market to maximize overlap while honoring dependencies.
- **Retries**: every task executes inside a retry harness (e.g., `tenacity`) with exponential backoff keyed by provider throttling guidance. Failures exhaust retries and propagate as `ExperimentExecutionError`, marking the associated `ExperimentRunMeta` as failed without canceling sibling tasks.
- **Result gathering**: the executor returns results in submission order. Research bundle outputs are cached per bundle identity; forecast outputs are reassembled per market to maintain deterministic persistence and downstream hashing.
- **Thread-safety**: mutable state on `ExperimentRunMeta` and stats accumulators is updated on the event loop thread after awaiting task results. No shared state is mutated inside threads.

## Implementation Plan

### 1. LLMTaskExecutor
Create `backend/pipelines/experiments/llm_executor.py`:
- `LLMTaskExecutor` manages an internal event loop (`asyncio.new_event_loop()`) and a `ThreadPoolExecutor` sized to match maximum concurrency.
- `submit(callable, /, *, key, provider)` registers a task, wrapping the callable with retry logic and collecting timing metadata.
- `run_all()` awaits the completion of all submitted tasks, returns `LLMTaskResult` objects (payload, diagnostics, token usage, errors).
- Concurrency configuration pulled from `PipelineContext.settings.llm_max_concurrency` with optional overrides per provider (`openai_max_concurrency`, etc.).
- Provides structured logging (queued_at, started_at, finished_at, attempt_count) for observability.

### 2. Pipeline Integration
Modify `backend/pipelines/daily_run.py`:
- Instantiate an executor per event group (`executor = LLMTaskExecutor(context=pipeline_context)`), reused between research and forecast stages to share concurrency budget.
- Update `_execute_research_bundles` to:
  - For each active bundle, submit a single callable that invokes `strategy.run(group, context)` (using `functools.partial`).
  - Await executor results, map successful outputs back to `ResearchExecutionRecord`s, and handle exceptions by marking meta failures.
- Update `_execute_forecast_stage` to:
  - For each suite + market, submit tasks that call `strategy.run_single_market(...)` (see strategy updates below).
  - Await results, populate `ForecastExecutionRecord`s, and mark meta states accordingly.
- Ensure the executor is closed after processing each event group via `executor.close()` in a `finally` block.
- Record retry/failure metadata into `ExperimentRunMeta.error_messages` and pipeline summary.

### 3. Strategy Interface Updates
- Introduce `ForecastStrategy.run_single_market(...)` default implementation that leverages existing `run` logic. Default implementation simply calls `run` and filters the matching market. Override in `GPT5ForecastStrategy` to avoid redundant filtering.
- Modify `GPT5ForecastStrategy` (`backend/pipelines/experiments/openai/forecast_gpt5.py`) to expose an internal `_forecast_market(market, research_artifacts, context)` helper returning a single `ForecastOutput`. The executor submits this helper per market.
- Similar extraction for research strategies is unnecessary; their current `run` signature already returns one payload.

### 4. Retry & Error Semantics
- Wrap task callable with retry policy: configuration knobs (`llm_retry_attempts`, `llm_retry_backoff_seconds`) added to `Settings` and `.env.example`.
- Retry on subclasses of `ExperimentExecutionError` flagged as retriable, HTTP 429/5xx from provider SDKs, and network errors. Non-retriable exceptions immediately propagate.
- Record each attempt’s exception chain in diagnostics. Final failure triggers `meta.mark_failed()` and summary entry `reason="experiment_failed"` (existing behavior).

### 5. Token Metrics Aggregation
- Extend `LLMRequestSpec.diagnostics()` to include raw usage dictionaries (`prompt_tokens`, `completion_tokens`, `total_tokens`, cost if exposed).
- Create `TokenUsageAggregator` (e.g., `backend/pipelines/experiments/metrics.py`):
  - Methods `record(stage, provider, usage)` and `snapshot()` returning totals per stage/provider and grand totals.
  - Attach aggregator to `PipelineContext` for easy access in strategies; executor records usage after each successful task.
- Update pipeline summary:
  - Add `summary.token_usage = aggregator.snapshot()` and persist to JSON summary.
  - Emit log line after run: `Token usage: research.prompt=..., forecast.prompt=...`.
- Include token metrics in `_dump_debug_artifacts` (under `_diagnostics.token_usage`).

### 6. Settings & Configuration
- Update `Settings` (`app/core/config.py`) to expose:
  - `llm_max_concurrency` (default 4), `llm_retry_attempts` (default 3), `llm_retry_backoff_seconds` (default 2.0), optional per-provider overrides (`openai_max_concurrency`).
- Update `.env.example` and docs (`AGENTS.md` checklist) to note new knobs.

### 7. Observability Enhancements
- Add structured logging around executor start/finish with run_id, suite_id, strategy_name, market_id, attempt, duration.
- Emit per-task metrics to StatsD/Prometheus interface if available (hook behind `PipelineContext.metrics_client`).
- Ensure pipeline summary includes counts of succeeded, skipped, failed tasks per stage (extracted from executor results).

### 8. Testing Plan
- Unit tests for `LLMTaskExecutor` with fake callables to ensure concurrency limits, retries, and result ordering (`backend/tests/unit/pipelines/test_llm_executor.py`).
- Integration test for `_execute_research_bundles` using stub strategies that sleep to validate parallel speedup.
- Dry-run pipeline invoking mock providers that record token usage metrics, verifying summary output.
- Manual verification: run `uv run python -m pipelines.daily_run --dry-run --limit 5` with debug logs enabled; inspect token usage totals and ensure failures are retried.

### 9. Rollout Steps
1. Implement executor + strategy refactors with sequential fallbacks removed (new baseline).
2. Backfill documentation (.env example, AGENTS.md) and ensure team inherits new retry knobs.
3. Ship to staging; monitor OpenAI telemetry for rate-limit responses and retry counts.
4. Once stable, merge to main. CI daily workflow benefits automatically.

## Open Questions
- Should we persist per-strategy token usage in the database for long-term analytics? (Out of scope but easy once aggregator is in place.)
- Do we need dynamic concurrency adaptation based on observed 429s? Could be future enhancement.
- How should we handle provider-specific cost fields (USD) if exposed? Currently we aggregate tokens only.

