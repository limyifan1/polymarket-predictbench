# Polymarket PredictBench

An experimental platform for running large language model forecasting experiments on Polymarket data. The pipeline ingests open markets that close within a configurable window, stores them in a relational database, exposes a FastAPI backend that groups markets by event, and renders a Next.js dashboard with filtering and sorting by close date, volume, and liquidity.

## Repository Layout

- `backend/` – FastAPI application, SQLAlchemy models, and ingestion jobs.
- `frontend/` – Next.js (App Router) client for exploring markets.
- `docs/` – Architecture and planning notes.
- `data/` – Default location for the SQLite database used in development.

## Prerequisites

- Python 3.11+
- Node.js 18+
- (Optional) PostgreSQL 14+ if running against Postgres instead of the default SQLite database.

## Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env  # update values as needed
export PYTHONPATH=$(pwd):$PYTHONPATH
uvicorn app.main:app --reload --port 8000
```

### Using uv (optional)

If you prefer [uv](https://github.com/astral-sh/uv) over `virtualenv` + `pip`, you can manage the backend dependencies with it instead.

```bash
cd backend
uv venv  # creates .venv managed by uv
uv pip install -r requirements.txt
cp ../.env.example ../.env  # update values as needed
uv run uvicorn app.main:app --reload --port 8000
```

`uv run` executes the command inside the managed environment, so you can skip manual activation.

## Common Local Workflows

All commands assume you are inside the `backend/` directory with a virtual environment (or `uv`) activated.

| Goal | Command | Notes |
| --- | --- | --- |
| Sanity-check ingestion + experiments without writes | `uv run python -m pipelines.daily_run --dry-run` | Streams markets, runs the registered suites, and prints a run summary without mutating the database. |
| Run the full pipeline against your configured database | `uv run python -m pipelines.daily_run` | Persists processed events, experiment results, and failures using the database defined in `.env`. |
| Inspect which suites/variants would run | `uv run python -m pipelines.daily_run --list-experiments` | Emits a JSON manifest respecting any additional CLI filters; no network calls are made. |
| Test only specific suites or stages | `uv run python -m pipelines.daily_run --suite baseline --stage research --dry-run` | Repeat `--suite` to include multiple suites; combine with `--include-research` / `--include-forecast` for fine-grained ablations. |
| Limit scope for debugging | `uv run python -m pipelines.daily_run --limit 5 --dry-run` | Stops after five markets to keep feedback loops fast. |
| Capture request/response payloads | `uv run python -m pipelines.daily_run --dry-run --debug-dump-dir ../debug-dumps` | Useful when adjusting prompts or the Polymarket client; disable via `--no-debug-dump`. |
| Launch the FastAPI server | `uv run uvicorn app.main:app --reload --port 8000` | Visit `http://localhost:8000/docs` for Swagger UI and hit `/healthz` for a quick readiness probe. |
| Start the Next.js dashboard | `cd ../frontend && npm install && npm run dev` | Expects the API at `http://localhost:8000`; override with `NEXT_PUBLIC_API_BASE_URL`. |

Quick checks before committing changes:

```bash
uv run python -m pipelines.daily_run --dry-run --limit 5
curl "http://localhost:8000/healthz"
cd ../frontend && npm run lint
```

### Pipeline Deep Dive

The ingestion + processing pipeline lives under `backend/pipelines/daily_run.py`. It fetches markets closing within a configurable horizon (default seven days ahead), groups them by event, runs the registered experiment suites, persists successful results, and records structured run metadata. See [`docs/polymarket-open-markets.md`](docs/polymarket-open-markets.md) for a full walkthrough of each stage.

Key CLI knobs:

- `--window-days <int>`: change the forward-looking close-date horizon.
- `--target-date YYYY-MM-DD`: process a specific close date instead of a rolling window.
- `--suite <id>` / `--stage {research,forecast,both}` / `--include-research` / `--include-forecast`: narrow the experiment surface for ablation runs.
- `--summary-path <path>`: write a machine-readable run summary (handy for CI artifacts and regression tracking).
- `--debug-dump-dir <path>` / `--no-debug-dump`: control JSON payload dumps.
- `--limit <int>`: cap the number of markets processed during smoke tests.

#### How Polymarket events are retrieved
- The pipeline wraps `https://gamma-api.polymarket.com/markets` via `ingestion.client.PolymarketClient`, which serializes query parameters and paginates with the configured `ingestion_page_size` (default 200).
- Each run enforces `closed=false` and derives `end_date_min`/`end_date_max` from the target date window so only markets closing on that day are returned.
- Responses are normalized in `ingestion.normalize.normalize_market`, enforcing required fields (IDs, question text, close time, contracts). Invalid payloads are logged and skipped.
- Suites returned by `pipelines.experiments.registry.load_suites()` run sequentially per market event. Only markets where required strategies succeed are persisted.
- Successful markets are written to the `processed_*` tables, experiment results are captured per market, and `crud.upsert_market` keeps the legacy `markets` table in sync for the API.
- Pagination continues until Polymarket stops returning results. Cursor-based pagination is supported when the upstream response includes `nextCursor`; otherwise we fall back to numeric offsets.
- For ad-hoc investigations, the legacy `python -m scripts.ingest_markets` command still works but bypasses the processing safeguards; prefer the pipeline for routine runs.

Need a quick readout of open markets without another ingest run? Query the FastAPI layer after it syncs: `curl "http://localhost:8000/markets?status=open"`.

- Full parameter reference (per [Polymarket docs](https://docs.polymarket.com/api-reference/markets/list-markets)):

  | Param | Type | Notes |
  | --- | --- | --- |
  | `limit` | integer ≥0 | Page size |
  | `offset` | integer ≥0 | Offset pagination |
  | `order` | string | Comma-separated sort fields |
  | `ascending` | boolean | Applies to `order` fields |
  | `id` | array[int] | Market IDs |
  | `slug` | array[string] | Market slugs |
  | `clob_token_ids` | array[string] | Token identifiers |
  | `condition_ids` | array[string] | Conditional token IDs |
  | `market_maker_address` | array[string] | Market maker wallets |
  | `liquidity_num_min` / `liquidity_num_max` | number | Liquidity bounds |
  | `volume_num_min` / `volume_num_max` | number | Volume bounds |
  | `start_date_min` / `start_date_max` | ISO datetime | Market open window |
  | `end_date_min` / `end_date_max` | ISO datetime | Market close window |
  | `tag_id` | integer | Filter by tag ID |
  | `related_tags` | boolean | Include related tags |
  | `cyom` | boolean | Create-your-own markets |
  | `uma_resolution_status` | string | UMA adapter status |
  | `game_id` | string | Sports game identifier |
  | `sports_market_types` | array[string] | Sports-specific types |
  | `rewards_min_size` | number | Minimum rewards size |
  | `question_ids` | array[string] | Question IDs |
  | `include_tag` | boolean | Return tag metadata |
  | `closed` | boolean | Close state gate |

  Arrays should be provided as JSON lists when using the CLI or `.env`, e.g. `--filter slug=["market-one","market-two"]`, which the client serializes as `slug=market-one,market-two` for the Polymarket API.

  Environment variables in `.env` control pagination, base URLs, and database connection strings. The default configuration stores data in `data/predictbench.db`.

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

The dashboard expects the backend API at `http://localhost:8000`. Adjust `NEXT_PUBLIC_API_BASE_URL` in `.env` if the backend runs elsewhere.

## Daily Automation (GitHub Actions)

- **What runs**: `.github/workflows/daily-pipeline.yml` executes `python -m pipelines.daily_run` every day at 07:00 UTC and whenever you trigger the workflow manually.
- **Secrets and variables**: configure `SUPABASE_DB_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and optionally `OPENAI_API_KEY` in the repository secrets. Provide `INGESTION_FILTERS` / `INGESTION_PAGE_SIZE` as repository variables to keep pagination consistent with local runs.
- **Arguments**: manual dispatch lets you override the processing horizon (`window_days`), target date (`target_date`), or toggle a dry run. Leave inputs blank to inherit the CLI defaults. The workflow automatically writes a run summary to `artifacts/pipeline-summary.json` and uploads it for later inspection.
- **Tweaks**: edit the cron expression at the top of the workflow to change the schedule. Adjust the `ARGS` construction in the `Run daily pipeline` step to pass additional flags (e.g., `--suite` or `--limit`) or to point `--summary-path` somewhere else. Because the job sets `ENVIRONMENT=production`, the pipeline will abort early if the Supabase secrets are missing—ideal for catching misconfigurations.
- **Local parity**: run the same command locally (see table above) to reproduce GitHub Actions behaviour. The only differences are environment variables and the fact that GitHub persists the summary artifact automatically.

## Development Notes

- The ingestion pipeline normalizes markets/outcomes and upserts them into the relational schema. Contract lists are synced on each ingest.
- Both markets and contracts now retain the raw Polymarket payload (`markets.raw_data` / `contracts.raw_data`) so downstream tooling can reference the exact upstream response.
- API endpoints:
  - `GET /healthz` – Simple readiness probe used by orchestrators and deployment checks.
  - `GET /events` – Event-level aggregation with nested markets, respecting the same filter/sort options.
  - `GET /markets` – Paginated listing with filters for status, close window, min volume, and ordering.
  - `GET /markets/{market_id}` – Detailed market payload with nested contracts.
- Frontend filters submit as query-string parameters so the UI is shareable and stateless.

## Next Steps

1. Add background scheduling (e.g., Prefect or APScheduler) for recurring ingestion.
2. Implement LLM experiment orchestration and surface predictions in the API/UX.
