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

### Ingest Polymarket Markets

Use the CLI script to hydrate or refresh the database. The script defaults to open markets, 200 per page.

```bash
cd backend
uv run python -m scripts.ingest_markets --limit 500 --force-close-after-now
```

You can refine the upstream API request with environment-based defaults (`INGESTION_FILTERS` in `.env`) or ad-hoc CLI flags: `python -m scripts.ingest_markets --filter closed=false --filter order=volume_num --filter ascending=false`. Filters are forwarded to `https://gamma-api.polymarket.com/markets` and must match the documented query parameters.

- Practical recipes:
  - `closed=false` ingests only open markets (replacement for the old `status=open` flag).
  - `order=volume_num` + `ascending=false` returns the highest-volume markets first.
  - `slug=["fed-rate-hike-in-2025","new-york-city-mayoral-election"]` targets specific markets (arrays are supplied as JSON and serialized to comma-separated lists).
  - `start_date_min=2025-01-01T00:00:00Z` narrows ingestion to markets created after a given date.
  - `--force-close-after-now` adds an `end_date_min` filter set to the current UTC time so only markets closing in the future are fetched.

When upgrading an existing workspace, make sure the database schema includes the new `markets.raw_data` column (drop the local SQLite file or apply an equivalent migration).

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
