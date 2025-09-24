# Polymarket Forecasting Platform Technical Plan

## 1. Goals
- Collect all open Polymarket markets and keep them up to date in local storage for experimentation.
- Run multiple large language model (LLM) forecasting experiments against the collected markets.
- Surface both raw market data and experiment outputs on a web application with support for filtering and sorting (initially by close date and volume).
- Provide an extensible architecture that can add additional experiments, metrics, and visualizations without large refactors.

## 2. High-Level Architecture Overview
1. **Ingestion Service** pulls open markets from Polymarket on a schedule, normalizes them, and writes to a database.
2. **Data Store** (PostgreSQL) houses market metadata, price history snapshots, and experiment results. Time-series data can be sharded into a separate table for scale.
3. **Experiment Orchestrator** (e.g., Prefect, Dagster, or in-house scheduler) fetches market snapshots, generates prompts, calls LLM providers, records predictions, and computes evaluation metrics.
4. **API Layer** (FastAPI or Next.js API route) exposes REST/GraphQL endpoints for the web client to retrieve markets and experiment outputs.
5. **Web Client** (Next.js/React) renders tables and charts, allowing users to filter/sort open markets and drill into experiment comparisons. Uses client-side caching and incremental static regeneration for responsiveness.

```
Polymarket API -> Ingestion Workers -> PostgreSQL <- Experiment Orchestrator -> LLM Providers
                                                  -> API Layer -> Web Client
```

## 3. Polymarket Data Acquisition

### 3.1 API Surface
- Primary source: Polymarket offers a GraphQL endpoint (`https://gamma-api.polymarket.com/graphql`) and a REST-ish markets endpoint (`https://gamma-api.polymarket.com/markets`). Public markets carry metadata such as question, outcomes, closing date, volume, liquidity, and current prices.
- Rate limiting: empirical reports indicate 5-10 requests/second are tolerated. Use client-side rate limiting to avoid bans.
- Authentication: The open endpoints do not require authentication, but adding headers (`Origin`, `Referer`) to mimic browser traffic can improve reliability.

### 3.2 Data Model
For each market, capture:
- Market identifiers: `id`, `slug`, `question`, `category`, `subCategory`.
- Temporal info: `openTime`, `closeTime`, resolution deadlines.
- Liquidity metrics: `volume`, `liquidity`, `fee`, `spread`.
- Outcomes: list of contracts with `id`, `name`, `price`, `confidence`, `outcomeType`.
- Auxiliary: `icon`, `image`, `description`, `tags`.
- (Optional) price history: either via `/markets/:id/trades` or external price snapshot service.

### 3.3 Ingestion Implementation
1. **Connector**: Create a small Python module using `httpx` or `requests` to pull open markets. Support pagination via `cursor` or `limit/offset` parameters.
2. **Normalization**: Map raw JSON into a Pydantic (or dataclass) schema to enforce types. Convert timestamps to UTC `datetime` objects.
3. **Persistence**: Upsert markets into PostgreSQL using SQLAlchemy or Prisma. Maintain `markets` and `contracts` tables with unique constraints on `id`.
4. **Scheduling**: Trigger ingestion every 5 minutes with Prefect, APScheduler, or GitHub Actions (if running in the cloud). Store job metadata in a `ingestion_runs` table for observability.
5. **Change detection**: Track `updated_at` and `hash` fields to detect field changes and avoid redundant writes.

## 4. Database Schema (Initial)

### 4.1 Tables
- `markets`
  - `market_id` (PK, text)
  - `slug`, `question`, `category`, `sub_category`
  - `close_time` (timestamptz), `open_time`
  - `volume_usd` (numeric), `liquidity_usd`, `fee_bps`
  - `status` (`open`, `closed`, `resolved`)
  - `last_synced_at`
- `contracts`
  - `contract_id` (PK)
  - `market_id` (FK -> `markets`)
  - `name`, `current_price`, `payout`, `confidence`
  - `implied_probability`
- `price_snapshots`
  - `snapshot_id` (PK)
  - `market_id`
  - `contract_id`
  - `timestamp`
  - `price`
- `experiments`
  - `experiment_id` (PK)
  - `name`, `description`, `llm_provider`, `hyperparameters` (JSONB)
  - `created_at`
- `experiment_runs`
  - `run_id` (PK)
  - `experiment_id` (FK)
  - `executed_at`
  - `prompt_template_version`
  - `status`
- `predictions`
  - `prediction_id` (PK)
  - `run_id`
  - `market_id`
  - `contract_id`
  - `prediction_probability`
  - `confidence`
  - `raw_response` (JSONB)
- `evaluation_metrics`
  - `metric_id`
  - `run_id`
  - `market_id`
  - `metric_name`
  - `metric_value`
  - `computed_at`

### 4.2 Indexing
- Index `markets.close_time` and `markets.volume_usd` for fast sorting and filtering.
- Composite index on `contracts.market_id, contracts.name`.
- Time-series indexes on `price_snapshots.market_id, timestamp` for charting.

## 5. Experimentation Framework

### 5.1 Experiment Lifecycle
1. **Selection**: Pick a subset of open markets (e.g., new markets, high volume) using SQL queries.
2. **Prompt Assembly**: Build context-rich prompts that include market question, historical price data, related news context (optional), and instructions for probability outputs.
3. **LLM Invocation**: Use an abstraction layer to call providers (OpenAI, Anthropic, local models). Track model version and temperature.
4. **Post-processing**: Parse responses into numeric probabilities per outcome. Validate they sum to 1 (or normalize).
5. **Storage**: Persist predictions to `predictions` table with references to markets, contracts, and run metadata.
6. **Evaluation**: Once markets resolve, compute Brier score, log-loss, calibration metrics. Automate evaluation jobs that run nightly.

### 5.2 Tooling Recommendations
- Use `langchain` or `llama_index` only if they simplify prompt templating; otherwise, a light custom abstraction may suffice.
- Implement retries and exponential backoff when calling APIs.
- Maintain experiment configurations in version-controlled YAML files for reproducibility.
- Include a dry-run mode that prints prompts and skip actual LLM calls for debugging.

## 6. Web Application

### 6.1 Functional Requirements
- Default view: table of all open markets with columns for `Question`, `Close Date`, `Volume`, `Liquidity`, `Latest Price`, `Experiment Signals` (if available).
- Filters: by closing date range, minimum volume, category, experiment availability.
- Sorting: by close date ascending/descending, volume descending.
- Detail page: show market description, price chart (from `price_snapshots`), list of experiment predictions, and evaluation once resolved.

### 6.2 Technical Stack
- **Frontend**: Next.js 14 (App Router) with React Query or SWR for data fetching. Use TanStack Table for performant virtualized tables. Deploy on Vercel or existing infra.
- **UI Components**: Tailwind CSS or Chakra UI for rapid styling; incorporate date pickers and numeric inputs for filters.
- **State Management**: Keep filter state in the URL query params for shareability; use `useSearchParams`.
- **Charts**: `recharts` or `nivo` for time-series probability visualization.

### 6.3 API Contract
- `GET /api/markets?status=open&close_before=2024-12-31&min_volume=10000&sort=closeTime&order=asc&limit=100`
  - Returns paginated markets with aggregated contract info and latest experiment predictions.
- `GET /api/markets/{market_id}`
  - Returns market detail, contracts, price history, experiment predictions, evaluation metrics.
- `GET /api/experiments`
  - Lists available experiment definitions and last run status.

### 6.4 Performance & Caching
- Use server-side caching (Redis) to store the latest open markets list for 30-60 seconds to shield the database from high read traffic.
- Enable incremental static regeneration (ISR) for the table page if traffic is mostly read-only.
- Prefetch detail pages when hovering table rows to improve interaction latency.

## 7. Initial Implementation Milestones

1. **M0 – Data Ingestion MVP**
   - Implement Polymarket market fetcher with retries.
   - Create PostgreSQL schema (`markets`, `contracts`).
   - Schedule ingestion job to refresh every 5 minutes.
   - Deliver CLI command `python -m ingest.run --markets open` for manual runs.

2. **M1 – Web Readout MVP**
   - Build Next.js page `/markets` showing open markets table.
   - Implement filters for close date (date range picker) and min volume slider.
   - Add server-side sorting by close date and volume using API parameters.
   - Deploy to preview environment; add monitoring (e.g., Vercel Analytics).

3. **M2 – Experimentation Scaffold**
   - Set up experiment registry table and configuration format.
   - Implement generic LLM call wrapper with provider support.
   - Add experiment runner that writes predictions into `predictions` table.
   - Render experiment signal column in UI (e.g., latest probability, last updated).

4. **M3 – Evaluation & Iteration**
   - Implement evaluation job triggered on market resolution.
   - Use dashboards to compare model performance (Brier score). Add charts to UI.
   - Add advanced analytics (calibration plots, time-weighted accuracy).

## 8. Deployment & Operations
- **Infrastructure**: Consider using Render/Heroku for API and ingestion workers (simple) or Kubernetes if scale demands.
- **Secrets Management**: Store LLM API keys in environment variables managed via Doppler or Vault.
- **Monitoring**: Use Grafana/Prometheus or hosted alternatives (Datadog) to watch ingestion latency, job failures, API error rates.
- **Alerting**: On ingestion failure or LLM quota exhaustion, send alerts via Slack/Webhooks.
- **Cost Tracking**: Log LLM usage per run to manage spend; optionally integrate with OpenAI Usage API.

## 9. Future Enhancements
- Integrate Polymarket on-chain data (AMM state) for deeper analytics.
- Add auto-generated news context (RAG) to improve LLM forecasts.
- Support multi-outcome markets and liquidity curves.
- Publish experiment leaderboards and allow interactive prompt tweaking.
- Explore model ensembling and Bayesian calibration for improved accuracy.

## 10. Risks & Mitigations
- **API Changes**: Polymarket endpoints may shift; mitigate by wrapping calls and adding integration tests.
- **Rate Limits/Blocks**: Introduce caching, exponential backoff, rotating proxies if necessary.
- **LLM Drift**: Version prompts and models; re-run calibration periodically.
- **Data Quality**: Validate schema and write tests to catch missing outcomes or zero-sum probabilities.
- **Cost Overruns**: Enforce per-run budgets and implement alerting when approaching spend caps.

## 11. Immediate Next Steps
1. Prototype the Polymarket API client in Python and confirm schema coverage.
2. Stand up PostgreSQL locally (Docker) and create schema migrations.
3. Implement the initial Next.js markets table with static mocked data to validate UX.
4. Once ingestion is stable, connect the API layer and replace mocks.
