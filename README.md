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
python -m scripts.ingest_markets --limit 500
```

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
- API endpoints:
  - `GET /markets` – Paginated listing with filters for status, close window, min volume, and ordering.
  - `GET /markets/{market_id}` – Detailed market payload with nested contracts.
- Frontend filters submit as query-string parameters so the UI is shareable and stateless.

## Next Steps

1. Add background scheduling (e.g., Prefect or APScheduler) for recurring ingestion.
2. Capture historical price snapshots using the existing `price_snapshots` table.
3. Implement LLM experiment orchestration and surface predictions in the API/UX.
