# Market & Event Resolution Pipeline Plan

## Objectives
- Detect the resolution status of every tracked Polymarket event and underlying market.
- Persist the resolved flag, resolved timestamp, winning outcome, and settlement metadata so downstream analytics and the dashboard can surface final results.
- Deliver the new resolution sweep as a standalone pipeline that can run independently from the daily ingestion job while reusing shared clients and repository primitives.

## Existing Data Flow Recap
- `pipelines/daily_run.py` coordinates ingestion using the `PolymarketClient` REST integration and writes normalized snapshots through SQLAlchemy repositories in `app/crud.py` and models defined in `app/models.py`.
- Core relational entities:
  - **Event** (`events`): represents a Polymarket "collection" (fields include `id`, `slug`, `question`, `close_date`, `source_last_modified`).
  - **Market** (`markets`): individual outcome markets linked to an event (fields include `id`, `event_id`, `title`, `status`, `liquidity`, `volume`, `last_price`, `close_date`).
  - **ProcessedSnapshot** (`processed_snapshots`): pipeline outputs per market and experiment variant.
- Repositories expose `upsert_events`, `upsert_markets`, and `upsert_processed_snapshots`. Resolution data must slot into this pattern.

## External Data Sources
- **Polymarket REST API** (existing client): add pagination over `/markets` with `status=closed` and `resolved` flag fields. Key fields include `event_id`, `outcome`, `condition.resolution`, and `condition.question_outcome_win_prob`. The REST payload already returns the `winning_outcome` string and `resolution_time`, so it can provide the minimal dataset required to mark a market or event as resolved.
- **Polymarket GraphQL API** (optional follow-up): query `market(id)` to capture `resolutionSource`, `winningOutcome`, and `resolutionTime` when additional validation is desired. The production sweep relies solely on the REST feed because it already publishes the winning outcome and timestamps; GraphQL can be revisited later if discrepancies surface.
- **UMA on-chain data (follow-up)**: UMA oracle data from `https://api.thegraph.com/subgraphs/name/polymarket/matic-markets` is only necessary when we want to display on-chain settlement hashes or monitor UMA disputes. For the initial sweep we can defer UMA ingestion—`resolution_source` will surface whether a market resolved on-chain, and we can backfill UMA artifacts later without blocking the primary resolution status update.

## Database Schema Changes
Extend existing models and add a supplemental table for UMA resolution events.

### `events` table additions
| Column | Type | Notes |
| --- | --- | --- |
| `is_resolved` | `Boolean`, default `False` | High-level event resolution flag (true if all linked markets resolved). |
| `resolved_at` | `DateTime` | Timestamp derived from the latest market resolution among children. |
| `resolution_source` | `String(50)` | Copy of the dominant resolution channel (`platform`, `on_chain`, `disputed`). |

### `markets` table additions
| Column | Type | Notes |
| --- | --- | --- |
| `is_resolved` | `Boolean`, default `False` | Mirrors Polymarket `market.resolved`. |
| `resolved_at` | `DateTime` | UTC timestamp of resolution. |
| `winning_outcome` | `String(255)` | Text label (e.g., "Yes", "No", multi-outcome slug). |
| `payout_token` | `String(20)` | Token used for settlement (`USDC`, etc.). |
| `resolution_tx_hash` | `String(66)` | Optional on-chain transaction reference. |
| `resolution_notes` | `Text` | Free-form notes for manual overrides or Polymarket announcements. |

Add indexes on `is_resolved` and `(event_id, is_resolved)` to accelerate resolution-specific dashboards.

### New table: `uma_resolution_events`
| Column | Type | Notes |
| --- | --- | --- |
| `id` | `UUID` (PK) | Generated in application. |
| `market_id` | `UUID` (FK to markets.id) | Links UMA decision to market. |
| `assertion_tx_hash` | `String(66)` | UMA assertion transaction. |
| `resolution_tx_hash` | `String(66)` | Final settlement transaction hash. |
| `uma_outcome` | `String(255)` | Outcome submitted on UMA. |
| `resolved_at` | `DateTime` | UMA resolution timestamp. |
| `created_at`/`updated_at` | `DateTime` | Standard audit fields. |

## Application Layer Updates
1. **Models & CRUD**
   - Update `app/models.py` to add the new columns on `Event` and `Market` plus the `UMAResolutionEvent` SQLAlchemy model.
   - Extend `app/schemas.py` (Pydantic) and `app/crud.py` with matching fields, including `upsert_uma_resolution_events` that deduplicates based on `(market_id, assertion_tx_hash)`.
   - Adjust `app/api/v1/endpoints/markets.py` and `events.py` responses to include resolution metadata.

2. **Settings**
   - Add `POLYMARKET_GRAPHQL_URL` (default `https://www.polymarket.com/api/graphql`) and `UMA_SUBGRAPH_URL`. Wire them into `app/core/config.py`.
   - Introduce `PIPELINE_RESOLUTION_BATCH_SIZE` (default 100 markets) to tune sweep chunking.

3. **Pipeline Modules**
   - Create `pipelines/resolution_run.py` with a `ResolutionPipeline` class that follows the structure of `DailyRunPipeline`:
    1. Query the local database for unresolved events and their markets, then refetch those markets from the Polymarket REST API to confirm their latest status.
    2. Normalize data into new resolution DTOs.
    3. Persist updates using the extended repositories (markets, events, UMA resolution events).
    4. Emit a structured summary JSON (counts of newly resolved markets, discrepancies, failures).
   - Add a dedicated CLI entrypoint in `pipelines/__main__.py` (e.g., `python -m pipelines.resolution_run`) so operators and schedulers invoke the resolution sweep separately from the daily ingestion job. The shared scheduler can trigger both pipelines in sequence if desired, but they remain logically decoupled and can be retried or scaled independently.

### Daily Sweep Scope & Safeguards
- **Event selection**: Each run starts from our existing `events` table, selecting all rows where `is_resolved = false` or any joined market remains unresolved. This local query guarantees we revisit every open event regardless of when it last traded or closed. Operators can still supply overrides via `PIPELINE_RESOLUTION_FORCE_EVENT_IDS`, but the default behavior is to sweep the full unresolved inventory without making assumptions about recent close windows.
- **Market roll-up**: After loading the candidate events from the database, the pipeline evaluates every market under each event in a single transaction so multi-market events resolve atomically. Events that the database already marks as resolved are skipped unless new REST data indicates a status change, preventing redundant writes.
- **Data integrity**: Migrations add nullable columns with safe defaults (`False` booleans, `NULL` timestamps) and keep existing indexes intact. Existing rows with `NULL` resolution flags are backfilled to `false` so the sweep always revisits them. Upsert operations update only the new resolution fields and preserve existing pricing/liquidity data. All writes execute inside SQLAlchemy-managed transactions so a failure during resolution ingestion rolls back instead of partially mutating rows.
- **Backfill isolation**: The same logic powers both historical backfills and the daily sweep. Operators can limit scope via `--limit`, `--event-id`, or `--recent-hours` when seeding historical data, while steady-state runs continue to skip markets already marked resolved unless incoming data changes.

4. **Retry & Alerting**
   - Reuse existing `PolymarketClient` retry helpers; log and surface any REST discrepancies so we can decide whether optional GraphQL or UMA lookups are needed later.
   - Publish summary stats to the existing logging/alert sink (`loguru` + optional Slack webhook) when a market transitions to resolved.

## API & Frontend Exposure
- Backend endpoints: add query parameters `status=resolved` and `resolution_source` filters to `/markets` and `/events` endpoints; ensure serialization includes `resolved_at`, `winning_outcome`, and UMA data.
- Frontend: update dashboard resolution filters and detail panes (follow-up task; document includes backend contract changes to unblock UI work).

## Migration Strategy
1. Generate Alembic migration adding new columns and `uma_resolution_events` table (ensure SQLite compatibility, cast booleans to integers for SQLite).
2. Backfill historical data by running `pipelines.resolution_run --limit 500` repeatedly until all closed markets are processed.
3. Schedule the resolution sweep as its own recurring job (for example, a cron or GitHub Actions workflow invoking `pipelines.resolution_run`). Our GitHub Actions `daily-pipeline` workflow now launches the sweep right after the ingestion job so the production database stays in sync without manual intervention, while the logical separation ensures failures or retries in one pipeline never block the other.

## Documentation & Operations
- Update `docs/pipeline-runbook.md` with resolution sweep run instructions and troubleshooting tips.
- Extend `operations.md` with alert remediation steps (e.g., manual override path when Polymarket retracts a resolution).
- Provide a new dashboard panel showing "Markets awaiting resolution confirmation" driven by the new indexes.

## Open Questions & Follow-ups
- Confirm whether partial event resolutions (some markets resolved, others pending) should immediately flag the event as resolved or keep it `partial`—define business rule before final implementation.
- Determine retention for UMA resolution events; consider pruning entries after N days once reconciled.
- Align with frontend team on display format for multi-outcome `winning_outcome` strings (e.g., JSON vs. comma-separated labels).

