# Polymarket PredictBench

An experimental platform for running large language model forecasting experiments on Polymarket data. The stack collects all open markets, stores them in a relational database, exposes a FastAPI backend, and renders a Next.js dashboard with filtering and sorting by close date and volume.

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

### Daily Pipeline (recommended)

The ingestion + processing pipeline now lives under `backend/pipelines/daily_run.py`. It fetches only markets closing a fixed number of days in the future (defaults to 7), executes registered experiments, persists successful results, and records metadata about the run.

```bash
cd backend
uv run python -m pipelines.daily_run --dry-run             # fetch + process without writes
uv run python -m pipelines.daily_run                       # full run, writes to the configured DB
uv run python -m pipelines.daily_run --window-days 3       # change close-date horizon
uv run python -m pipelines.daily_run --target-date 2025-03-01  # explicit processing window
uv run python -m pipelines.daily_run --summary-path ../summary.json
```

- Daily GitHub Actions should set `TARGET_CLOSE_WINDOW_DAYS` (defaults to 7) and supply Supabase credentials via `SUPABASE_DB_URL` / `SUPABASE_SERVICE_ROLE_KEY`.
- `--dry-run` is useful locally to confirm API reachability without mutating the database.
- `--summary-path` writes a JSON artifact (`processed`, `failed`, timing, etc.) to help CI notifications.
- When the pipeline runs against production, `environment=production` and the presence of `SUPABASE_DB_URL` make the backend connect to Supabase automatically.

#### How Polymarket events are retrieved
- The pipeline wraps `https://gamma-api.polymarket.com/markets` via `ingestion.client.PolymarketClient`, which serializes query parameters and paginates with the configured `ingestion_page_size` (default 200).
- Each run enforces `closed=false` and derives `end_date_min`/`end_date_max` from the target date window so only markets closing on that day are returned.
- Responses are normalized in `ingestion.normalize.normalize_market`, enforcing required fields (IDs, question text, close time, contracts). Invalid payloads are logged and skipped.
- Experiments declared in `processing_experiments` (see `app/core/config.py`) run sequentially per market. Only markets where every required experiment succeeds are persisted.
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

## Development Notes

- The ingestion pipeline normalizes markets/outcomes and upserts them into the relational schema. Contract lists are synced on each ingest.
- Both markets and contracts now retain the raw Polymarket payload (`markets.raw_data` / `contracts.raw_data`) so downstream tooling can reference the exact upstream response.
- API endpoints:
  - `GET /markets` – Paginated listing with filters for status, close window, min volume, and ordering.
  - `GET /markets/{market_id}` – Detailed market payload with nested contracts.
- Frontend filters submit as query-string parameters so the UI is shareable and stateless.

## Next Steps

1. Add background scheduling (e.g., Prefect or APScheduler) for recurring ingestion.
2. Capture historical price snapshots using the existing `price_snapshots` table.
3. Implement LLM experiment orchestration and surface predictions in the API/UX.
