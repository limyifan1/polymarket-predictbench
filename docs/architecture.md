# Architecture Overview

Polymarket PredictBench ingests open markets from Polymarket, enriches them
with LLM-driven research and forecasts, persists the results, and exposes a
FastAPI backend plus a Next.js dashboard. The codebase is organised so that
each concern is isolated but still easy to compose during a pipeline run.

## Component map

```
Polymarket API  ─┐
                 │  ingestion/client.py → ingestion/normalize.py
LLM providers  ──┼→ pipelines/experiments → repositories + models
                 │
SQLite/Postgres ─┘→ FastAPI (app/) → Next.js dashboard (frontend/)
```

### Backend (`backend/app`)
- **Configuration** – `app.core.config.Settings` centralises environment
  variables and exposes helper flags such as `ENVIRONMENT`, database URLs, and
  experiment overrides.
- **Database access** – SQLAlchemy models in `app/models.py` describe the
  processing tables (runs, events, markets, research artifacts, experiment
  results). Repository classes under `app/repositories/` provide typed insert
  helpers so the pipeline never deals with raw SQL.
- **API** – `app/main.py` wires up the FastAPI application. CRUD functions in
  `app/crud.py` compose with Pydantic schemas from `app/schemas.py` to expose
  processed markets grouped by event, plus health checks and configuration
  metadata for the dashboard.

### Ingestion layer (`backend/ingestion`)
- `PolymarketClient` handles pagination and filtering against the Polymarket
  REST API.
- `normalize_market` validates upstream payloads into strongly typed
  `NormalizedMarket` / `NormalizedEvent` instances.
- `session_scope()` yields SQLAlchemy sessions with automatic commit/rollback,
  allowing the pipeline to batch writes per run.

### Experiment pipeline (`backend/pipelines`)
- `pipelines/daily_run.py` is the orchestration entry point. It loads settings,
  resolves the target close-date window, builds experiment suites, streams
  markets, executes research and forecast strategies, persists results, and
  records summary metadata.
- Experiment strategies live in `pipelines/experiments/`. `ResearchStrategy`
  and `ForecastStrategy` define the contracts for producing `ResearchOutput`
  artifacts and `ForecastOutput` probability distributions. Suites combine
  strategy variants and enforce dependency ordering.
- Providers in `app/services/llm/` abstract OpenAI, Gemini, and future LLM
  integrations behind a uniform request interface.

### Persistence model
- Processing runs (`processing_runs`) record metadata such as run IDs, target
  dates, and aggregated counts.
- `processed_events`, `processed_markets`, and `processed_contracts` snapshot
  the normalized Polymarket payloads for auditability.
- `research_artifacts` store structured JSON emitted by research strategies
  alongside provenance fields (hash, URI, related experiment run).
- `experiment_results` capture forecast probabilities and research payloads per
  strategy variant.
- Legacy tables (`markets`, `contracts`) stay synchronised via
  `crud.upsert_market` so the API can continue serving historical snapshots.

### Frontend (`frontend/`)
- Next.js (App Router) dashboard built with TypeScript. It fetches grouped
  markets from the API, surfaces filtering and sorting by close date, volume,
  and liquidity, and links to raw research artifacts.
- Shared utilities live in `frontend/lib/` and shared types in
  `frontend/types/`. Environment configuration uses `NEXT_PUBLIC_API_BASE_URL`
  to point at the FastAPI instance.

### Data artifacts (`data/`)
- Local runs default to `data/predictbench.db` (SQLite). The path is ignored by
  Git so transient data never pollutes commits.
- Production runs (GitHub Actions, Supabase deployments) use `SUPABASE_DB_URL`
  and enforce SSL parameters suitable for PgBouncer.

## How requests flow
1. **Pipeline** fetches markets, executes suites, and writes rows to the
   processing tables.
2. **FastAPI** queries the processed tables, joins experiment runs/artifacts,
   and exposes JSON endpoints for the dashboard.
3. **Frontend** renders events, research context, and forecast outputs for
   operators to review.

Each layer can run independently: the pipeline writes to the database without
starting the API, the API serves historic data without triggering experiments,
and the frontend talks to any reachable API endpoint.
