# Pipeline Runbook

This guide covers the daily ingestion and experiment pipeline implemented in
`backend/pipelines/daily_run.py`. Use it as both a quick-start reference and a
troubleshooting companion when runs fail.

## When to run it
- Populate a fresh database after setting up the project locally.
- Rebuild market snapshots before shipping experiments or API changes.
- Investigate failed GitHub Actions runs by reproducing the command locally.
- Generate research/forecast outputs for a specific close date window.

## Core workflow
1. Resolve settings (`Settings`) and determine the target close-date window.
2. Build experiment suites via `pipelines.experiments.registry.load_suites()`.
3. Stream Polymarket markets using `ingestion.client.PolymarketClient` with
   `closed=false` and the configured window.
4. Group markets by event (`EventMarketGroup`).
5. Execute research strategies, persist artifacts, and fan out to forecast
   strategies once their dependencies succeed. Each experiment result is written
   to the database immediately after the corresponding LLM completes (still
   wrapped in the per-event transaction) so successful work survives pipeline
   crashes.
6. Write processed payloads, experiment runs, research artifacts, forecast
   results, and processing failures via repository helpers. Completed events are
   tagged with a deterministic `event_key`, allowing future runs to skip them.
7. Emit a structured `PipelineSummary` (printed to stdout and optionally saved
   as JSON via `--summary-path`).

## Frequently used commands
All commands assume you are inside `backend/` with dependencies installed and
`PYTHONPATH` pointing at the directory (or you are using `uv run`).

| Goal | Command | Notes |
| --- | --- | --- |
| Dry run with minimal scope | `uv run python -m pipelines.daily_run --dry-run --limit 5` | Fetches a handful of markets, runs suites, prints summary, skips writes. |
| Inspect suite manifest | `uv run python -m pipelines.daily_run --list-experiments` | No network or database access; useful for verifying CLI filters. |
| Run only specific suites | `uv run python -m pipelines.daily_run --suite baseline --suite openai` | Repeat `--suite` for multiple entries. |
| Stage-specific runs | `uv run python -m pipelines.daily_run --stage research --dry-run` | `research`, `forecast`, or `both` (default). |
| Focus on variants | `uv run python -m pipelines.daily_run --include-forecast gpt5` | Accepts comma-separated variant names or `suite:variant` identifiers. |
| Generate summary artifact | `uv run python -m pipelines.daily_run --summary-path ../summary.json` | Writes JSON with counts, failures, and per-suite stats. |
| Capture payload dumps | `uv run python -m pipelines.daily_run --debug-dump-dir ../debug-dumps` | Stores research/forecast request-response JSON per event. |
| Batch events concurrently | `uv run python -m pipelines.daily_run --event-batch-size 8` | Overrides `PIPELINE_EVENT_BATCH_SIZE` (default 4). |

## Key CLI flags
- `--window-days <int>` – forward-looking horizon for market close dates.
- `--target-date YYYY-MM-DD` – exact date to process (mutually exclusive with
  `--window-days`).
- `--limit <int>` – stop after processing the given number of markets.
- `--suite <id>` – run only the specified suites (repeatable).
- `--stage {research,forecast,both}` – restrict execution to part of the
  pipeline.
- `--event-batch-size <int>` – number of event groups processed together (defaults to `PIPELINE_EVENT_BATCH_SIZE`).
- `--include-research` / `--include-forecast` – comma-separated variant names to
  whitelist.
- `--debug-dump-dir <path>` – override where JSON dumps land; use
  `--no-debug-dump` to disable dumps entirely.
- `--list-experiments` – print the suite manifest and exit without running.
- `--experiment-override <spec>` – apply a single experiment config override
  (repeatable).
- `--experiment-override-file <path>` – load overrides from a JSON file
  (repeatable).

## Overriding Experiment Configurations
For one-off tests or debugging, you can change experiment parameters without
modifying suite definitions. Overrides are applied in the following order (last
one wins):
1. Suite-level defaults (in `BaseExperimentSuite.experiment_overrides()`).
2. Overrides from files (`--experiment-override-file`).
3. Inline overrides (`--experiment-override`).

### Inline Overrides (`--experiment-override`)
The spec format is `experiment_name.key=value`, where `experiment_name` matches
the identifier from the `--list-experiments` manifest (e.g., `openai:research:openai_web_search`).

- **Example**: Change a model for a single run
  ```bash
  uv run python -m pipelines.daily_run --dry-run --limit 1 \
    --experiment-override openai:research:openai_web_search.model=gpt-4-turbo
  ```
- **Nested values**: Use dot notation for nested keys.
  ```bash
  uv run python -m pipelines.daily_run --dry-run --limit 1 \
    --experiment-override openai:research:openai_web_search.prompt_params.max_tokens=500
  ```
- **Types**: Values are parsed automatically (e.g., `true`, `123`, `null`).
  Wrap in quotes if the shell requires it.

### File Overrides (`--experiment-override-file`)
Provide a JSON file where keys are experiment names and values are config objects.
This is useful for managing complex or frequently used overrides.

- **Example `debug_overrides.json`**:
  ```json
  {
    "openai:research:openai_web_search": {
      "model": "gpt-4-turbo",
      "prompt_params": {
        "temperature": 0.5
      }
    },
    "gemini:forecast:gemini_simple": {
      "model": "gemini-2.5-flash"
    }
  }
  ```
- **Usage**:
  ```bash
  uv run python -m pipelines.daily_run --dry-run \
    --experiment-override-file debug_overrides.json
  ```

## What gets persisted
- `processing_runs` – high-level metadata (run ID, timestamps, target window,
  counts, Git SHA, environment).
- `processed_events` / `processed_markets` / `processed_contracts` – normalized
  Polymarket payloads for every processed event.
- `processed_events.event_key` – deterministic identifier (`event_id` or
  `market:<ids>`) used to de-duplicate runs.
- `research_artifacts` – JSON payloads + provenance for each research variant.
- `experiment_results` – forecast probabilities and research payloads tagged by
  suite/stage/variant.
- `processing_failures` – per-market error reasons with a retriable flag.

Writes occur only when `--dry-run` is omitted. Even in dry-run mode, the
pipeline still executes strategies so you can inspect logs, debug dumps, and the
printed summary.

## Failure handling
- **Normalization errors** – logged with context and recorded as retriable
  failures (when not in dry-run mode).
- **Research strategy errors** – mark the entire event bucket as failed for the
  strategy; dependent forecasts are skipped.
- **Forecast strategy errors** – recorded per strategy; the pipeline continues
  with other suites/variants.
- **Missing forecasts** – if all forecasts skip or fail, the run logs a
  `no_forecast_results` failure so downstream analysis can filter affected
  markets.
- **Previously processed events** – the run logs a skip message and continues
  without reissuing LLM calls when the `event_key` already exists. This makes
  reruns idempotent even after partial failures.
- **Duplicate commits during persistence** – if another run finishes between the
  lookup and the insert, the unique constraint on `processed_events.event_key`
  triggers and the event is treated as already processed. The retry helper does
  not re-run LLM work in that scenario.
- **Mid-run crashes** – every event group is committed in its own transaction,
  so research artifacts and forecasts that completed before the crash remain in
  the database and will be treated as already processed on the next run. Final
  run metadata uses the same retry/backoff wrapper, so status updates land once
  the per-event transactions finish.

`PipelineSummary.failures` captures a list of `{market_id, reason}` entries. The
JSON artifact mirrors the printed summary for automation and alerting.

## Troubleshooting checklist
1. Run with `--dry-run --limit 5` to reproduce quickly.
2. Inspect the debug dump JSON payloads (written automatically unless
   `--no-debug-dump` is passed).
3. Replay persisted artifacts with
   `uv run python -m pipelines.replay_debug_dump --run-id <run>` if the run
   died after LLM execution but before database writes.
4. Check `research_artifacts` / `experiment_runs` tables to confirm which
   variants succeeded.
5. Review log output for `ExperimentExecutionError` or missing dependencies.
6. Confirm environment variables (`OPENAI_API_KEY`, `GEMINI_API_KEY`,
   `SUPABASE_DB_URL`) are available when targeting production backends.

## Replaying debug dumps after DB errors
- `pipelines.replay_debug_dump` reuses the debug dump JSON to insert
  `processed_events`, markets, research artifacts, and forecasts without
  re-running LLM calls.
- Minimum invocation:
  ```bash
  uv run python -m pipelines.replay_debug_dump --run-id <run-id>
  ```
- Use `--dump-dir` when dumps live outside `PIPELINE_DEBUG_DUMP_DIR`; pass
  `--dry-run` to validate dumps without touching the database.
- The script reuses experiment run identifiers captured in the dumps; make sure
  the original pipeline run created the run metadata (the CLI does this before
  event processing).

## Scheduling (GitHub Actions)
- `.github/workflows/daily-pipeline.yml` triggers at 07:00 UTC and on manual
  dispatch.
- Secrets required: `SUPABASE_DB_URL`, `SUPABASE_SERVICE_ROLE_KEY`, optional
  `OPENAI_API_KEY`, and any other provider keys (e.g., `GEMINI_API_KEY`).
- Repository variables: `INGESTION_FILTERS`, `INGESTION_PAGE_SIZE` to keep
  pagination consistent with local runs.
- The workflow sets `ENVIRONMENT=production`, installs dependencies from
  `backend/requirements.txt`, runs the CLI, and uploads
  `artifacts/pipeline-summary.json` when present.
- Completed events are skipped on subsequent runs. The pipeline derives an
  `event_key` (the upstream event id, or `market:<sorted-market-ids>` when no
  event exists) and persists it alongside the event snapshot. When a new run
  streams markets it first queries the database for existing keys and marks the
  matching event group as skipped.
