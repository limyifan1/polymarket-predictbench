# Polymarket PredictBench Daily Pipeline

This document captures how the daily ingestion + processing pipeline is implemented today and how to extend it safely.

## 1. Objectives
- Run the Polymarket processing pipeline once per day at a predictable UTC time via GitHub Actions, with manual reruns when needed.
- Collect only markets that close on a configurable future window (defaults to seven days ahead) and skip everything else.
- Execute a configurable list of experiments for each market; persist outputs only when every experiment succeeds.
- Keep production writes pointed at Supabase Postgres while letting local development default to SQLite (or any override supplied via `DATABASE_URL`).
- Record auditable metadata for each run (processed counts, failures, Git SHA) and publish a machine-readable summary artifact for CI consumers.

## 2. End-to-End Flow
1. **Scheduler** – `.github/workflows/daily-pipeline.yml` triggers at `0 7 * * *` UTC or by manual dispatch.
2. **Orchestrator** – `python -m pipelines.daily_run` resolves the target close-date window, builds Polymarket API filters, and initializes the database session + run metadata.
3. **Ingestion** – `PolymarketClient` fetches markets with `closed=false`, `end_date_min`, and `end_date_max` bounds; payloads are normalized via `ingestion.normalize.normalize_market`.
4. **Experiments** – `load_experiments` instantiates the configured experiment classes; each experiment's `run` method receives the normalized market and a `PipelineContext`.
5. **Persistence** – successful markets are stored in `processed_*` tables alongside experiment runs/results while `crud.upsert_market` keeps the legacy `markets`/`contracts` tables in sync.
6. **Reporting** – the run summary (`PipelineSummary`) tracks totals and failure reasons; when `--summary-path` is provided the JSON payload is written to disk and uploaded as a GitHub Actions artifact.

```
GitHub Actions (cron/dispatch)
        |
        v
pipelines.daily_run (CLI)
        |
        v
 +--------------+    +-----------------+    +-------------------+
 | Ingestion    | -> | Experiments     | -> | Persistence       |
 +--------------+    +-----------------+    +-------------------+
        |
        v
   Logs & Summary Artifact
```

## 3. Scheduling & GitHub Actions
- **Triggers**: scheduled daily run plus `workflow_dispatch` inputs (`window_days`, `target_date`, `dry_run`). Blank inputs allow the CLI defaults to take effect.
- **Steps**: checkout repository, install Python 3.11 dependencies from `backend/requirements.txt`, verify `SUPABASE_DB_URL` is present, execute the CLI, and upload `artifacts/pipeline-summary.json` if produced.
- **Runtime environment**: the job sets `ENVIRONMENT=production` so the settings resolver insists on a Supabase connection. `PYTHONPATH` is pointed at `backend` so imports like `app` resolve correctly.
- **Secrets**: `SUPABASE_DB_URL` (pooled Postgres string) and `SUPABASE_SERVICE_ROLE_KEY` must be configured in the repository. Authentication to the Polymarket API is still optional; no key is required today. Supply the `postgresql://` DSN from Supabase (“Connection string” → “psql”); the settings layer promotes it to `postgresql+psycopg://` and enforces `sslmode=require` / `target_session_attrs=read-write` automatically so PgBouncer plays nicely with psycopg3.
- **Overrides**: manual dispatches can change the processing horizon (`window_days`), target date (`target_date`), or toggle `dry_run`. The CLI also accepts `--limit` for ad-hoc debugging; the workflow leaves it unset.
- **Artifacts**: the pipeline always logs to stdout via Loguru; when `--summary-path` is provided the JSON summary contains `run_id`, `run_date`, `target_date`, `window_days`, and failure details for downstream notifications.

## 4. Pipeline CLI Behaviour
- `pipelines.daily_run` arguments:
  - `--window-days <int>`: number of days ahead from the run date. Defaults to `Settings.target_close_window_days` (7 unless overridden by `TARGET_CLOSE_WINDOW_DAYS`).
  - `--target-date YYYY-MM-DD`: explicit date; overrides `--window-days` after validating that the target is not in the past.
  - `--dry-run`: bypasses all database writes while still counting processed/failed markets.
  - `--limit <int>`: stop after processing the specified number of markets (useful for local smoke tests).
  - `--summary-path <path>`: write a formatted JSON summary. The helper creates parent directories automatically.
- The CLI resolves the start/end bounds for the target day in UTC (`00:00:00` inclusive to the next day's midnight exclusive) and injects them into the Polymarket filters.
- Experiments are loaded before ingestion starts. If no experiments are configured the CLI aborts early so we never persist half-baked runs.
- When running with writes enabled, the CLI records:
  - A `processing_runs` row with run metadata and the Git SHA (if supplied via `GITHUB_SHA`).
  - An `experiment_runs` record for each registered experiment with status transitions (`running` → `completed`/`failed`).
  - For each processed market: entries in `processed_markets`, `processed_contracts`, and associated `experiment_results` rows.
  - Failures captured via `processing_failures` with a `retriable` flag.
- Dry-run mode still loads experiments and executes them; it simply skips persistence and leaves the database untouched.

## 5. Experiments & Extensibility
- The `Experiment` protocol (see `backend/pipelines/experiments/base.py`) defines `name`, `version`, `description`, and a synchronous `run(market, context)` method returning an `ExperimentResult` payload, optional score, and artifact URI.
- `backend/pipelines/registry.py` reads dotted paths from `Settings.processing_experiments`, imports each module, instantiates the class, and logs any load failures.
- Experiments execute sequentially per market. `ExperimentSkip` lets an experiment opt out gracefully; `ExperimentExecutionError` (or any unexpected exception) marks the market as failed and records the error message.
- The default `BaselineSnapshotExperiment` (`backend/pipelines/experiments/baseline.py`) captures the normalized market plus contract snapshots so downstream systems can audit the exact data that was evaluated.
- To add a new experiment, implement the protocol, expose it via `module:ClassName`, and append the import string to `PROCESSING_EXPERIMENTS` in `.env` or the GitHub Actions environment.

## 6. Persistence Model
- `session_scope()` (in `backend/ingestion/service.py`) manages a SQLAlchemy session with commit/rollback semantics. The daily pipeline holds one session for the full run so partially processed markets stay isolated until the run completes.
- Key tables touched by the pipeline (`backend/app/models.py`):
  - `processing_runs`: top-level run metadata (`run_id`, `run_date`, `window_days`, `target_date`, counts, status, Git SHA, environment).
  - `processed_markets`: run-scoped market snapshots (`processed_market_id`, `run_id`, `market_id`, `question`, `close_time`, `raw_snapshot`). A unique constraint on (`run_id`, `market_id`) prevents duplicates inside a run.
  - `processed_contracts`: contracts nested under a processed market with stored attributes (`price`, `attributes`).
  - `experiments` / `experiment_runs` / `experiment_results`: definitions, per-run execution metadata, and structured outputs respectively.
  - `processing_failures`: reasons and retriability flags for markets that did not persist.
  - `markets` / `contracts`: the legacy canonical tables kept in sync via `crud.upsert_market`.
- SQLite is the default (`sqlite:///../data/predictbench.db`), but `ENVIRONMENT=production` forces `SUPABASE_DB_URL` to be present so GitHub Actions never writes to SQLite by mistake.

## 7. Failure Handling & Reporting
- **Normalization errors**: any exception raised while parsing a market increments `failed_markets`, appends a `normalization_failed` entry to the summary, and records a retriable failure when not in dry-run mode.
- **Experiment failures**: unexpected exceptions from an experiment mark the market as failed, log the stack trace, and capture a `experiment_failed` record. Experiment skips simply continue to the next experiment.
- **Empty result guard**: if every experiment completes but no result payloads are returned, the pipeline treats the market as failed (`no_experiment_results`) and records a non-retriable failure.
- **Summary artifact**: the JSON structure produced by `_write_summary` includes `total_markets`, `processed_markets`, `failed_markets`, and an array of `{market_id, reason}` pairs for fast triage. GitHub Actions uploads the artifact so chatops/notifications can re-use it.
- **Logging**: Loguru logs include the run ID in contextual messages (e.g., `Starting pipeline run ...`, failure traces) to make GH Actions output searchable.

## 8. Configuration & Secrets
- Primary settings live in `backend/app/core/config.py` and derive from environment variables:
  - `DEBUG`, `ENVIRONMENT`, `DATABASE_URL`, `SUPABASE_DB_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
  - Polymarket client knobs: `POLYMARKET_BASE_URL`, `POLYMARKET_MARKETS_PATH`, `INGESTION_PAGE_SIZE`, and arbitrary `INGESTION_FILTERS` (parsed as JSON).
  - Pipeline settings: `TARGET_CLOSE_WINDOW_DAYS`, `PIPELINE_RUN_TIME_UTC`, and `PROCESSING_EXPERIMENTS`.
- `ENVIRONMENT=production` enforces that `SUPABASE_DB_URL` is supplied and automatically upgrades pooled connection strings to the `postgresql+psycopg://` SQLAlchemy dialect.
- `.env.example` documents the most common overrides; `backend/.env` is used for local development and checked into `.gitignore`.
- For GitHub Actions, set environment variables in the workflow or repository secrets; no code changes are required because `pydantic-settings` reads from the process environment.

## 9. Testing & Future Enhancements
- **Suggested tests**: window calculation helpers, experiment registry loading, CRUD persistence flows (possibly with a temporary Postgres container), and Polymarket client contract tests using recorded fixtures.
- **Operational improvements** to consider next:
  1. Wire Slack/webhook notifications that consume the summary artifact.
  2. Add structured logging or metrics exporters when running outside GitHub Actions.
  3. Introduce retention or archiving policies for large `raw_snapshot` payloads.
  4. Explore concurrency or batching for experiments once multiple heavy models are introduced.
- Track these enhancements separately so this document stays a source of truth for the implementation that ships today.
