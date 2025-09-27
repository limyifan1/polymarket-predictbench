# Polymarket PredictBench Daily Pipeline

This document describes the ingestion + processing pipeline, the experiment framework, and how results are persisted.

## 1. Objectives
- Run the Polymarket processing pipeline once per day at a predictable UTC time via GitHub Actions, with manual reruns when needed.
- Collect markets that close within a configurable window (default seven days ahead) and skip everything else.
- Execute configurable experiment suites composed of research and forecast strategies, persisting results only when required stages succeed.
- Keep production writes pointed at Supabase Postgres while allowing local development to default to SQLite (or any override supplied via `DATABASE_URL`).
- Record auditable metadata for each run (processed counts, failures, Git SHA) and publish a machine-readable summary artifact.

## 2. End-to-End Flow
1. **Scheduler** – `.github/workflows/daily-pipeline.yml` triggers at `0 7 * * *` UTC or by manual dispatch.
2. **Orchestrator** – `python -m pipelines.daily_run` resolves the target close-date window, builds Polymarket API filters, and initializes the database session + run metadata.
3. **Ingestion** – `PolymarketClient` fetches markets with `closed=false`, `end_date_min`, and `end_date_max` bounds; payloads are normalized via `ingestion.normalize.normalize_market`.
4. **Experiments** – `load_suites` materializes the configured experiment suites. Each suite coordinates research strategies (context gathering) and forecast strategies (probability generation) against shared `EventMarketGroup` objects.
5. **Persistence** – successful markets are written to `processed_events` / `processed_markets`, research artifacts are stored in `research_artifacts`, and forecast outputs land in `experiment_results`. `crud.upsert_market` keeps the legacy `markets`/`contracts` tables in sync for the API.
6. **Reporting** – the run summary (`PipelineSummary`) tracks totals and failure reasons; when `--summary-path` is provided the JSON payload is written to disk and uploaded as a GitHub Actions artifact.

```
GitHub Actions (cron/dispatch)
        |
        v
pipelines.daily_run (CLI)
        |
        v
 +--------------+    +---------------------+    +-------------------+
 | Ingestion    | -> | Research + Forecast | -> | Persistence       |
 +--------------+    +---------------------+    +-------------------+
        |
        v
   Logs & Summary Artifact
```

## 3. Scheduling & GitHub Actions
- **Triggers**: scheduled daily run plus `workflow_dispatch` inputs (`window_days`, `target_date`, `dry_run`). Blank inputs allow the CLI defaults to take effect.
- **Steps**: checkout repository, install Python 3.11 dependencies from `backend/requirements.txt`, verify `SUPABASE_DB_URL` is present, execute the CLI, and upload `artifacts/pipeline-summary.json` if produced.
- **Runtime environment**: the job sets `ENVIRONMENT=production` so settings insist on a Supabase connection. `PYTHONPATH` points at `backend` so imports like `app` resolve correctly.
- **Secrets**: `SUPABASE_DB_URL` (pooled Postgres string) and `SUPABASE_SERVICE_ROLE_KEY` must be configured. Supply the `postgresql://` DSN from Supabase; settings upgrade it to `postgresql+psycopg://` and enforce `sslmode=require` / `target_session_attrs=read-write` for psycopg3 + PgBouncer.
- **Overrides**: manual dispatches can change the processing horizon (`window_days`), target date (`target_date`), or toggle `dry_run`. The workflow leaves `--limit` unset; use it locally for ad-hoc debugging.
- **Artifacts**: run logs stream via Loguru; when `--summary-path` is provided the JSON summary contains `run_id`, `run_date`, `target_date`, `window_days`, totals, and failure details.

## 4. Pipeline CLI Behaviour
- `pipelines.daily_run` arguments:
  - `--window-days <int>`: number of days ahead from the run date. Defaults to `Settings.target_close_window_days`.
  - `--target-date YYYY-MM-DD`: explicit date; overrides `--window-days` after validating that the target is not in the past.
  - `--dry-run`: bypasses all database writes while still counting processed/failed markets.
  - `--limit <int>`: stop after processing the specified number of markets (useful for smoke tests).
  - `--summary-path <path>`: write a formatted JSON summary. The helper creates parent directories automatically.
  - `--suite <id>` (repeatable): restrict execution to specific suites registered in `pipelines.experiments.registry`.
  - `--stage {research,forecast,both}`: execute only the selected stages (default `both`).
  - `--include-research` / `--include-forecast`: comma-separated variant names (or `suite_id:variant`) to run.
  - `--debug-dump-dir <path>`: write per-event JSON dumps of research/forecast payloads (defaults to `PIPELINE_DEBUG_DUMP_DIR`); pass `--no-debug-dump` to skip.
- The CLI resolves start/end bounds for the target day in UTC (`00:00:00` inclusive to the next day's midnight exclusive) and injects them into the Polymarket filters.
- Suites are instantiated before ingestion. If no suites are configured the CLI aborts early so we never persist half-baked runs.
- Markets are bucketed by event before suites execute. Failures at either stage mark every market in that bucket and produce shared processed-event metadata for the API.
- When writes are enabled, the CLI records:
  - A `processing_runs` row with run metadata.
  - One `experiment_runs` row per strategy + suite combination, with final status derived after the run.
  - Research artifacts in `research_artifacts` (plus corresponding `experiment_results` entries tagged with `stage='research'`).
  - Forecast outputs in `experiment_results` (`stage='forecast'`) with provenance pointing back to research artifacts when available.

## 5. Experiments & Extensibility
- Strategies live in `backend/pipelines/experiments`. `ResearchStrategy` implements `run(group, context)` and returns `ResearchOutput`; `ForecastStrategy` implements `run(group, artifacts, context)` and returns `ForecastOutput` with optional scores or diagnostics.
- Suites typically subclass `DeclarativeExperimentSuite` (see `backend/pipelines/experiments/suites.py`) and declare `research_factories` / `forecast_factories` via the `strategy(...)` helper. Prefer the `suite(...)` convenience helper when no subclass-specific logic is required—it produces the same declarative suite without defining a class. The default `BaselineSnapshotSuite` still works as a plain `BaseExperimentSuite` for legacy behaviour. Code-first configuration happens in `backend/pipelines/experiments/registry.py` by editing `REGISTERED_SUITE_BUILDERS`.
- YAML suite files remain supported via `pipelines.experiments.configuration.load_yaml_suites`, but they duplicate the Python configuration, lack static validation, and cannot express dynamic wiring (shared helpers, conditionals). Use them only when non-engineers must tweak experiments without touching the repository; otherwise prefer editing the registry module directly.
- Every research strategy listed in a suite runs for each event bucket. Forecast strategies execute for the same events once all dependencies named in their `requires` tuple have succeeded; missing dependencies raise during suite construction. Define a new suite when you need a different bundle of strategies (e.g., production vs. experimental) and new strategies when you change prompts, tooling, or output schemas.
- To add a suite, implement the strategies, wire them up with `strategy(...)` (or override the `_build_*` hooks directly), and append a builder callable to `REGISTERED_SUITE_BUILDERS` in `pipelines.experiments.registry`. The pipeline imports that tuple directly—no environment variables required.
- Strategies may raise `ExperimentSkip` to opt out per event. Any other exception bubbles up as `ExperimentExecutionError`, marking the event as failed and recording a retriable processing failure when writes are enabled.

## 6. Persistence Model
- `session_scope()` (`backend/ingestion/service.py`) manages a SQLAlchemy session with commit/rollback semantics. The pipeline holds one session for the full run so partial work stays isolated until completion.
- Key tables (`backend/app/models.py`):
  - `processing_runs`: top-level metadata (run IDs, target windows, counts, status, Git SHA, environment).
  - `processed_events` / `processed_markets` / `processed_contracts`: run-scoped snapshots of normalized payloads and contracts.
  - `research_artifacts`: research outputs linked to `experiment_runs` and processed events, with payloads, hashes, and optional URIs.
  - `experiment_runs`: per-strategy execution metadata (`stage`, timings, status, error messages).
  - `experiment_results`: structured outputs for both research and forecast stages (payload, score, artifact URI, provenance).
  - `processing_failures`: reasons + retriable flag for markets that did not persist.
  - `markets` / `contracts`: canonical tables kept in sync via `crud.upsert_market`.
- SQLite remains the default (`sqlite:///../data/predictbench.db`); `ENVIRONMENT=production` forces `SUPABASE_DB_URL` to be set so GitHub Actions never falls back to SQLite.

## 7. Failure Handling & Reporting
- **Normalization errors**: caught during payload parsing, logged with stack traces, stored as retriable failures (unless dry-run).
- **Research/forecast errors**: unexpected exceptions mark the entire event bucket as failed. Research skips prevent dependent forecasts from running; missing forecasts trigger a `no_forecast_results` failure unless the forecast stage is disabled.
- **Summary artifact**: records totals plus per-market reasons. Useful for alerting and downstream QA.

## 8. Troubleshooting Tips
- `uv run python -m pipelines.daily_run --dry-run --limit 5` confirms ingestion and suite wiring without touching the database.
- `uv run python -m pipelines.daily_run --stage research --suite baseline --dry-run` exercises only the research stage for targeted debugging.
- Check `processing_failures` for retriable errors and `experiment_runs` for per-strategy statuses.

## 9. Next Steps
- Add a standalone experiments runner that replays forecasts against stored research artifacts for offline ablations.
- Surface per-suite success counts and latency metrics in the summary artifact.
- Explore caching for expensive research variants shared across suites.
