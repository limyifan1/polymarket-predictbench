# Polymarket Predictbench Daily Processing Plan

## 1. Updated Objectives
- Run a single ingestion + processing pipeline once per day at a predictable UTC time via GitHub Actions.
- Collect only Polymarket markets that close exactly *N* days from the run date (default `N = 7`) and discard all other markets.
- Execute a modular data-processing stage that can host multiple experiments without rewriting the ingestion flow.
- Persist outputs only for markets that completed processing; avoid storing unprocessed/raw markets in the database.
- Use Supabase (managed Postgres) in production and a local developer database in non-production environments, controlled by configuration.
- Keep the architecture observable, testable, and easy to extend as new experiments are added.

## 2. End-to-End Flow Overview
1. **Scheduler** (GitHub Actions) triggers the pipeline every day at the configured UTC time, and can also be invoked manually.
2. **Orchestrator CLI** (new `python -m pipelines.daily_run`) determines the target close date window, pulls the relevant markets, and coordinates downstream stages.
3. **Ingestion Stage** fetches only markets closing within the target window, normalizes them, and performs lightweight validation.
4. **Processing Stage** runs a configurable list of experiments against each market, producing structured outputs and metadata.
5. **Persistence Stage** writes processed markets and experiment results to the configured database inside a single transaction per market; failed markets are skipped and reported.
6. **Reporting Stage** emits logs/metrics and uploads a JSON summary artifact for GitHub Actions (processed count, failures, runtime).

```
GitHub Actions (cron/manual)
        |
        v
pipelines.daily_run (Python CLI)
        |
        v
 +--------------+    +--------------------+    +-------------------+
 | Ingestion    | -> | Experiment Pipeline | -> | Persistence Layer |
 +--------------+    +--------------------+    +-------------------+
        |
        v
   Monitoring & Artifacts (logs, summary JSON)
```

## 3. Scheduling & Orchestration
- **Workflow cadence**: run at 07:00 UTC daily. Cron expression: `0 7 * * *`.
- **GitHub Action workflow**:
  - Trigger types: `schedule` + `workflow_dispatch` for manual reruns.
  - Steps: checkout repo, set up Python, install deps (reuse caching), load secrets, run CLI, upload summary artifact, notify on failure.
  - Secrets required:
    - `SUPABASE_DB_URL` (pooled Postgres connection string for the daily run).
    - `SUPABASE_SERVICE_ROLE_KEY` (admin token for migrations and transactional writes).
    - `POLYMARKET_API_KEY` (only if Polymarket introduces auth; optional for now).
  - The GitHub Actions workflow lives at `.github/workflows/daily-pipeline.yml`; it errors immediately if `SUPABASE_DB_URL` is missing so production runs never fall back to SQLite. Paste the pooled Postgres **connection string** from Supabase (`Database` → `Connection string` → `psql`), which starts with `postgresql://`; the settings layer rewrites this to `postgresql+psycopg://` automatically so SQLAlchemy uses psycopg3.
  - Environment variables: `TARGET_CLOSE_WINDOW_DAYS=7`, `PIPELINE_RUN_AT_UTC=07:00`, `ENVIRONMENT=production`, `SUPABASE_PROJECT_REF=<supabase-ref>`.
  - For manual dispatch, allow overriding `TARGET_CLOSE_WINDOW_DAYS` to backfill other horizons.
- **Idempotency**: CLI should record a `processing_runs` entry keyed by `run_date` and `window_days`. If a rerun exists, force either an update or skip to prevent double writes (design choice captured in schema section).

## 4. Ingestion Stage Design
- **Target window calculation**:
  - Determine `target_date = (today_utc + window_days)`.
  - Define `[start, end)` bounds as midnight to midnight UTC of `target_date`.
  - Pass bounds using Polymarket filters: `end_date_min=start`, `end_date_max=end`.
- **API interactions**:
  - Reuse `PolymarketClient` with new helper to set `closed=false`, `end_date_min`, `end_date_max`, and `page_size`.
  - Add instrumentation logs indicating number of pages requested and rate limiting (sleep if needed).
- **Normalization & validation**:
  - Reuse `normalize_market` to map raw payloads into typed objects.
  - Validate mandatory fields (`id`, `question`, `closeTime`, outcome data). Fail fast if missing or inconsistent.
- **In-memory staging**:
  - Accumulate normalized markets in memory (list of dataclasses) instead of persisting.
  - Optionally emit a staging JSON artifact for debugging (guarded by `--debug-artifacts`).

## 5. Processing Pipeline Architecture
- **Pipeline entry point**: `pipelines.daily_run` constructs a `PipelineContext` (contains run metadata, db handle, config) and iterates through markets.
- **Experiment registry**:
  - Define `Experiment` protocol with `name`, `version`, `requires`, and `run(market, context)` returning `ExperimentResult` (structured dataclass + optional artifacts).
  - Implement registry loader driven by configuration (list of experiment module paths in settings).
  - Support simple dependency ordering via `requires` list.
- **Execution semantics**:
  - For each market, run experiments sequentially (initial baseline). Future improvement: concurrency with async workers.
  - If any experiment raises a non-recoverable exception, mark the market as failed and exclude from persistence while logging the failure reason.
  - Allow experiments to short-circuit with `ExperimentSkip` to opt out gracefully.
- **Default experiment**:
  - Provide a placeholder `BaselineSnapshotExperiment` that records market metadata and acts as a template.
  - Additional experiments (LLM prompts, pricing models) can be appended by registering new classes.
- **Result packaging**:
  - Aggregate experiment outputs into a `ProcessedMarketPayload` (includes market metadata, experiment results array, run-level metadata, optional derived metrics).
  - Include raw market snapshot JSON for traceability, but only inside the processed record that passes all experiments.

## 6. Persistence Strategy
- **Environments**:
  - *Production*: Supabase managed Postgres. Primary connection uses the pooled `SUPABASE_DB_URL` secret; migrations and admin tasks use the `SUPABASE_SERVICE_ROLE_KEY`.
  - *Development*: Dockerized Postgres defined in `docker-compose.dev.yml` or local container. Default `dev` `.env` points to `postgresql://predictbench:predictbench@localhost:5432/predictbench`.
- **Write semantics**:
  - Wrap each market save inside a DB transaction to guarantee atomicity between market metadata and experiment outputs.
  - Only commit if every mandatory experiment succeeded; otherwise roll back and mark as failure in `processing_failures` table.
  - Upsert behavior: if a market already exists for the same `run_id`, update the record (keep latest experiment versions) to support reruns.
- **Schema (new/updated tables)**:
  - `processing_runs`: `run_id` (UUID), `run_date`, `window_days`, `target_date`, `started_at`, `finished_at`, `status`, `total_markets`, `processed_markets`, `failed_markets`, `git_sha`.
  - `processed_markets`: `processed_market_id` (UUID), `run_id` (FK), `market_id`, `market_slug`, `question`, `close_time`, `raw_snapshot` (JSONB), `processed_at`.
  - `processed_contracts`: `processed_contract_id`, `processed_market_id` (FK), `contract_id`, `name`, `price`, `metadata` (JSONB).
  - `experiments`: `experiment_id`, `name`, `version`, `description`, `is_active`.
  - `experiment_runs`: `experiment_run_id`, `run_id`, `experiment_id`, `status`, `started_at`, `finished_at`, `error_message`.
  - `experiment_results`: `experiment_result_id`, `experiment_run_id`, `processed_market_id`, `payload` (JSONB), `score` (optional numeric), `artifact_uri`.
  - `processing_failures`: `failure_id`, `run_id`, `market_id`, `reason`, `logged_at`, `retriable`.
- **Access patterns**:
  - Index `processed_markets.run_id` and `processed_markets.close_time` for reporting.
  - Use materialized views or SQL queries to surface latest experiments per market for the frontend API.

### 6.1 Supabase Integration Notes
- **Project layout**: create `prod` and `staging` Supabase projects or branches; align environments with GitHub Action contexts.
- **Connection pooling**: rely on Supabase's pooled connection string for the GitHub Action run to avoid exceeding connection limits; expose pool size via `DB_POOL_MAX_SIZE`.
- **Secrets management**: store `SUPABASE_DB_URL` (pooled), `SUPABASE_SERVICE_ROLE_KEY`, and `SUPABASE_PROJECT_REF` in GitHub Actions. Only the backend has access to the service-role key.
- **Auth & RLS**: keep row-level security disabled for ingestion tables; future frontend access should go through a service API so the Next.js app never uses service-role credentials.
- **Monitoring**: enable Supabase's database observability (logs, query stats) and configure automated daily backups with point-in-time recovery.
- **Local dev parity**: provide a `seed_supabase.sql` generated from migrations so developers can mirror schema locally when needed.

## 7. Configuration & Secrets
- Centralize settings in `app/core/config.py`:
  - `PIPELINE_RUN_TIME_UTC`, `TARGET_CLOSE_WINDOW_DAYS`, `PROCESSING_EXPERIMENTS` (comma-separated module path list), `DATABASE_URL`, `ENVIRONMENT`.
  - Provide `.env.example` entries for local usage; instruct developers to copy into `backend/.env`.
- Extend `get_settings()` to read GitHub Actions secrets (via environment variables) with no code changes in CI.
- Map production `DATABASE_URL` to the Supabase pooled connection string (`SUPABASE_DB_URL`) injected by GitHub Actions; expose the service-role key only to backend jobs.
- Backend settings now enforce that `SUPABASE_DB_URL` is present whenever `ENVIRONMENT=production`, preventing accidental writes to SQLite in CI/CD.
- Allow overriding `TARGET_CLOSE_WINDOW_DAYS` at runtime via CLI flag (`--window-days`) for backfills.

## 8. Observability & Quality Gates
- **Logging**: Structured JSON logs (Loguru formatter) with `run_id`, `process_stage`, `market_id` to simplify GH Actions log filtering.
- **Metrics**: Emit Prometheus-friendly counters/histograms when running outside GH Actions. Inside the action, include summary JSON (counts, durations) as artifact.
- **Alerting**: Configure GitHub Actions to notify via Slack/Webhook on workflow failure. Optional: send summary to Slack using repository secret.
- **Testing**:
  - Unit tests for window calculation logic, experiment registry, and persistence transaction behavior.
  - Integration test that spins up test Postgres (via pytest fixture) and runs pipeline against fixture API responses.
  - Contract test for Polymarket client using recorded responses (VCR.py) to guard against API changes.
  - Dry-run mode (`--dry-run`) for safe experimentation; prints would-be writes without touching the DB.

## 9. Implementation Milestones
1. **Migrate configuration**: Introduce new settings keys, document environment overrides, and stub CLI entrypoint.
2. **Build pipeline CLI**: Implement window calculation, Polymarket fetch with new filters, and dry-run support.
3. **Design persistence layer**: Create migrations for new tables, transactional save helpers, and failure logging.
4. **Implement experiment framework**: Add registry, base experiment protocol, and placeholder experiment.
5. **Integrate pipeline stages**: Wire ingestion, experiments, and persistence in the CLI; add summary reporting.
6. **Author GitHub Actions workflow**: Schedule daily run, parameterize secrets, upload artifacts, and add notifications.
7. **Add testing & documentation**: Cover unit/integration tests, update README, and document local dev setup.
8. **Pilot run**: Execute workflow manually against staging database, review artifacts/logs, and adjust instrumentation before enabling daily cron.

## 10. Open Questions & Follow-Up
- Validate Supabase project tier requirements (e.g., pro vs. team) and whether read replicas or edge functions are needed.
- Decide on retention policy for `raw_snapshot` JSON (possible pruning after X days to reduce storage).
- Determine whether processed data should be pushed to downstream analytics buckets (S3, BigQuery) in future iterations.
- Clarify experiment SLAs (are partial failures acceptable if core baseline passes?).
