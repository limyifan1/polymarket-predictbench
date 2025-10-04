# Research/Forecast Separation Plan

## Goals
- Treat research generation as an independent pipeline stage with its own execution records.
- Allow forecasts to reference any compatible research artifacts that already exist for an event, regardless of when they were produced.
- Preserve historical data while restructuring the persistence layer and API contract to highlight the separation between research and forecast artifacts.

## Proposed Changes

### Database & ORM schema
1. Introduce a new `ResearchRunRecord` model/table to capture research execution metadata (processing run linkage, suite/strategy identity, status timestamps, etc.).
2. Update `ResearchArtifactRecord` so it references `ResearchRunRecord` (via `research_run_id`) instead of `ExperimentRunRecord`. Remove the direct relationship from `ExperimentRunRecord` to research artifacts.
3. Limit `ExperimentRunRecord`/`ExperimentResultRecord` to forecast runs; remove `ExperimentStage.RESEARCH` usage from forecast tables.
4. Replace the single `source_artifact_id` field on `ExperimentResultRecord` with a join table (`ForecastResearchLink`) so forecasts can reference multiple research artifacts.

### Pipeline adjustments
1. When a research variant executes, persist a `ResearchRunRecord` and link all produced artifacts to it. Stop inserting "research" rows into `ExperimentResultRecord`.
2. Forecast execution should load eligible research artifacts for the processed event from the database (including artifacts produced in the same transaction) and select the required subset based on dependency names.
3. Persist selected dependencies via the new `ForecastResearchLink` table when recording forecast results.

### Repository & API updates
1. Extend `ProcessingRepository`/`ExperimentRepository` helpers to read/write `ResearchRunRecord` and the forecast/research link data.
2. Update the API services (`MarketService`, etc.) to adapt the new structures, ensuring research payloads include research run metadata and forecasts expose linked research artifact descriptors.
3. Adjust frontend DTO typings if necessary to account for the richer linkage metadata (while keeping the UI contract stable where possible).

### Migration considerations
- Provide an Alembic migration (or document manual steps) that backfills existing research runs and forecast links using historic `ExperimentRunRecord` data.
- Confirm that the migration keeps referential integrity even if some historical forecasts lack explicit dependencies.

### Testing & Validation
- Run the daily pipeline in research-only, forecast-only, and combined modes to ensure no regressions.
- Smoke-test API endpoints that surface research and forecast data (`/events`, `/markets`).
