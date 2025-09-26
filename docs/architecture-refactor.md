# PredictBench Architecture Refresh

This document captures the current refactor direction focused on clarity, separation of concerns, and ease of extension.

## Layered layout

- **Domain (`backend/app/domain/`)**
  - Pure data representations that normalisation + persistence share.
  - `NormalizedEvent`, `NormalizedMarket`, and `NormalizedContract` moved here to remove accidental coupling with persistence helpers.
- **Services (`backend/app/services/`)**
  - Stateless orchestrators that expose read/write workflows to entrypoints.
  - `MarketService` now fronts list/get logic for FastAPI handlers so the API no longer manipulates raw CRUD calls directly.
- **Persistence (`backend/app/repositories/` + `backend/app/crud.py`)**
  - `MarketRepository` and `ProcessingRepository` encapsulate database logic for read models and pipeline runs.
  - `app/crud.py` now delegates to these repositories so existing imports remain stable while callers benefit from the new structure.
- **Entrypoints (`backend/app/main.py`, `backend/pipelines/daily_run.py`)**
  - The API only depends on `MarketService`, which in turn uses repositories.
  - The daily pipeline reuses the repositories directly; a future iteration could still wrap the orchestration in a dedicated service for easier testing.

## Pending steps

1. Wrap the daily pipeline orchestration into a `DailyPipelineService` so the CLI simply handles CLI parsing and dependency wiring.
2. Align experiments around declarative manifests to simplify discovery and allow automated DAG construction.
3. Replace ad hoc logging with structured contexts (trace + run identifiers).
4. Update README/AGENTS docs after the next wave of refactors stabilises.

This staged plan keeps the system usable while steadily removing legacy coupling.
