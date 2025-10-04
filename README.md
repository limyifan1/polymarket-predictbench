# Polymarket PredictBench

Polymarket PredictBench ingests open Polymarket markets, runs LLM-powered
research + forecast experiments, and surfaces the results through a FastAPI API
and a Next.js dashboard. Use it to prototype strategies, compare suites, and
publish daily snapshots.

## At a glance
- **Backend** – FastAPI app with SQLAlchemy models and repository helpers in
  `backend/app/`.
- **Pipeline** – Daily ingestion + experiment runner (`backend/pipelines/`).
- **Ingestion** – Polymarket REST client, payload normalization, and session
  helpers in `backend/ingestion/`.
- **Frontend** – Next.js dashboard in `frontend/` that reads from the API.
- **Docs** – Task-focused guides in [`docs/`](docs/README.md).

## Prerequisites
- Python 3.11+
- Node.js 18+
- Optional: PostgreSQL 14+ (production deployments use Supabase Postgres; local
  runs default to SQLite)

## Quick start
1. **Clone the repo and copy environment variables**
   ```bash
   cp .env.example .env  # update API keys, database URLs, provider defaults
   ```

2. **Backend setup**
   ```bash
   cd backend
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   export PYTHONPATH=$(pwd):$PYTHONPATH  # or use `uv run` for commands below
   uvicorn app.main:app --reload --port 8000
   ```
   Prefer `uv`? Replace the virtualenv steps with `uv venv` + `uv pip install -r
   requirements.txt` and run commands via `uv run`.

3. **Pipeline smoke test**
   ```bash
   uv run python -m pipelines.daily_run --dry-run --limit 5
   ```
   See the [pipeline runbook](docs/pipeline-runbook.md) for full CLI coverage and
   troubleshooting tips.

4. **Frontend**
   ```bash
   cd ../frontend
   npm install
   npm run dev
   ```
   The dashboard expects the API at `http://localhost:8000`; override with
   `NEXT_PUBLIC_API_BASE_URL` when needed. To point a local UI at a production
   Supabase-backed API, set `NEXT_PUBLIC_PROD_API_BASE_URL` and pick
   **Production (Supabase)** from the dataset selector in the filter panel.

## Common workflows
| Task | Command |
| --- | --- |
| List registered experiment suites | `uv run python -m pipelines.daily_run --list-experiments` |
| Run pipeline for a specific date | `uv run python -m pipelines.daily_run --target-date 2025-01-15` |
| Restrict to certain suites | `uv run python -m pipelines.daily_run --suite baseline --suite openai` |
| Produce a summary artifact | `uv run python -m pipelines.daily_run --summary-path ../summary.json` |
| Tune event concurrency | `uv run python -m pipelines.daily_run --event-batch-size 8` (default `PIPELINE_EVENT_BATCH_SIZE`=4) |
| Launch FastAPI with reload | `uv run uvicorn app.main:app --reload --port 8000` |
| Start the dashboard | `cd frontend && npm run dev` |

## Data model highlights
- Processing runs + experiment runs track execution metadata and surfaced counts.
- Research artifacts capture structured JSON payloads with hashes and optional
  external URIs.
- Forecast results store outcome probabilities, reasoning, and provenance links
  back to research artifacts.
- Processed events now record an immutable `event_key` so the daily pipeline can
  skip events that already completed a research + forecast cycle. Each event
  group is persisted inside its own database transaction, and both event writes
  and run finalisation are wrapped in the same retry/backoff policy, so research
  and forecast results that finished before an unexpected shutdown remain
  stored. Reruns safely skip committed events and ignore duplicate writes that
  race in after the initial lookup.
- Legacy `markets`/`contracts` tables stay updated via `crud.upsert_market` so
  API consumers can rely on stable endpoints.

## Keeping quality high
Before opening a PR:
- `uv run python -m pipelines.daily_run --dry-run --limit 5`
- `curl "http://localhost:8000/healthz"`
- `cd frontend && npm run lint`

## Learn more
- [Architecture overview](docs/architecture.md)
- [Pipeline runbook](docs/pipeline-runbook.md)
- [Experiments guide](docs/experiments.md)
- [Operations & development](docs/operations.md)

Questions or gaps? File an issue and document the answer for the next run.
