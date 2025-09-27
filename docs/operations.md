# Operations & Development

This guide documents environment configuration, local workflows, automation,
and debugging practices for PredictBench.

## Environment configuration
- Copy `.env.example` to `.env` and update credentials. Settings are shared by
the backend, pipeline, and frontend via `pydantic-settings`.
- Core variables:
  - `DATABASE_URL` – overrides the default SQLite path when running locally.
  - `SUPABASE_DB_URL` / `SUPABASE_SERVICE_ROLE_KEY` – required for production
    runs and GitHub Actions (Postgres via Supabase).
  - `OPENAI_API_KEY`, optional `OPENAI_API_BASE`, `OPENAI_ORG_ID`,
    `OPENAI_PROJECT_ID` – OpenAI provider configuration.
  - `GEMINI_API_KEY` – enables the Gemini provider.
  - `LLM_DEFAULT_PROVIDER` – fallback provider (`openai` by default).
  - `INGESTION_FILTERS`, `INGESTION_PAGE_SIZE` – JSON filter blob and pagination
    size passed to the Polymarket client.
  - `PIPELINE_DEBUG_DUMP_DIR` – default directory for research/forecast payload
    dumps.
- Export `PYTHONPATH=$(pwd):$PYTHONPATH` inside `backend/` or run commands via
  `uv run` to ensure module imports resolve.

## Local development
1. **Backend**
   ```bash
   cd backend
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8000
   ```
   Or replace the virtualenv steps with `uv venv` / `uv run` for faster
   dependency management.

2. **Pipeline** – see the [pipeline runbook](pipeline-runbook.md) for common
   commands. Run the pipeline with `--dry-run` before committing ingestion or
   experiment changes.

3. **Frontend**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   The dashboard expects the API at `http://localhost:8000`. Override with
   `NEXT_PUBLIC_API_BASE_URL` when needed.

## Recommended pre-commit checks
- `uv run python -m pipelines.daily_run --dry-run --limit 5`
- `curl "http://localhost:8000/healthz"`
- `cd frontend && npm run lint`

## Database notes
- Development uses SQLite stored in `data/predictbench.db`. The path is ignored
  by Git, so feel free to remove the file when you want a clean slate.
- Production / CI runs set `ENVIRONMENT=production`, which enforces presence of
  `SUPABASE_DB_URL` and upgrades it to `postgresql+psycopg://` with
  `sslmode=require` for PgBouncer compatibility.
- Repository helpers in `app/repositories/` encapsulate insert logic. Avoid
  writing ad-hoc SQL in new code paths.

## Automation (GitHub Actions)
- `.github/workflows/daily-pipeline.yml` runs every day at 07:00 UTC and on
  manual dispatch.
- The job installs backend dependencies, runs `python -m pipelines.daily_run`
  with the supplied inputs, and uploads `artifacts/pipeline-summary.json` when
  the CLI writes one.
- Adjust the cron schedule or CLI flags by editing the workflow. Keep the
  summary artifact path stable for downstream tooling.

## Debugging tips
- Enable debug dumps (`--debug-dump-dir` CLI flag or `PIPELINE_DEBUG_DUMP_DIR`)
  to capture LLM request/response payloads for inspection.
- Query FastAPI endpoints directly:
  - `curl "http://localhost:8000/healthz"`
  - `curl "http://localhost:8000/markets?status=open" | jq '.items | length'`
- Inspect the `processing_failures` table to triage skipped/failed markets.
- Use `uv run python -m pipelines.daily_run --list-experiments` to confirm suite
  configuration without touching the database.

## Keeping docs in sync
Whenever you modify CLI flags, environment variables, or experiment wiring,
update the README and relevant guides in this directory. The
[`docs/README.md`](README.md) index lists each topic so contributors can find
what they need quickly.
