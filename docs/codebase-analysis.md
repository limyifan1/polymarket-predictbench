# PredictBench Codebase Analysis

## Architecture Overview
- **Pipeline orchestration** – `pipelines.daily_run` resolves the target close window, streams Polymarket markets, groups them by event, executes every registered experiment suite, and persists both processed payloads and experiment metadata. Its CLI exposes precise knobs for suite selection, stage gating, variant filters, debug dumps, and manifest inspection so each run can be replicated deterministically.【F:backend/pipelines/daily_run.py†L184-L260】【F:backend/pipelines/daily_run.py†L640-L749】
- **Experiment composition** – Suites are defined in code via `BaseExperimentSuite`, which materialises research and forecast strategies, validates dependency wiring, and assigns deterministic experiment identifiers. Declarative helpers allow prompt/suite tweaks without extra configuration formats.【F:backend/pipelines/experiments/suites.py†L80-L200】
- **API surface** – The FastAPI layer wires `MarketService` into `/events`, `/markets`, and `/markets/{id}` endpoints, providing grouped event views and raw market listings consumed by downstream tools and the dashboard.【F:backend/app/main.py†L1-L110】【F:backend/app/services/market_service.py†L15-L106】
- **Frontend** – The Next.js home page renders aggregated volume/liquidity metrics and a filterable event table backed by API queries, keeping analysis accessible once the pipeline has populated the database.【F:frontend/app/page.tsx†L1-L82】

## Experimentation & Ablation Capabilities
- **Variant controls** – The CLI accepts suite filters, stage toggles, and explicit research/forecast variant includes, enabling targeted ablation sweeps without editing code.【F:backend/pipelines/daily_run.py†L217-L259】
- **Manifest export** – `--list-experiments` now emits a JSON manifest describing the active suites, their strategies, dependency requirements, and whether each variant will execute under the current filters. This runs without touching the database, making it ideal for planning ablations offline.【F:backend/pipelines/daily_run.py†L658-L672】【F:backend/pipelines/experiments/manifest.py†L1-L99】
- **Run bookkeeping** – `ExperimentRunMeta` tracks per-strategy success, skip, and failure counts across every event bucket, and the pipeline summary aggregates those counts per suite/stage in a machine-readable map. This gives immediate visibility into which components executed during an ablation run and where failures accumulated.【F:backend/pipelines/daily_run.py†L48-L175】【F:backend/pipelines/daily_run.py†L142-L175】
- **Remaining gaps** – Ablations still run inline with the ingestion loop; there is no standalone replay runner to recompute forecasts from stored research artifacts, so true offline sweeps require rerunning the full pipeline.

## Robustness Assessment
- **Error isolation** – Normalisation failures, experiment exceptions, and missing forecasts each increment run-level failure counts, record structured reasons, and optionally persist retriable flags for reprocessing, preventing silent data corruption.【F:backend/pipelines/daily_run.py†L760-L881】
- **Strategy safeguards** – Suite execution wraps each strategy invocation, downgrading skips, capturing unexpected exceptions, and preserving dependency ordering so faulty research blocks dependent forecasts rather than producing inconsistent outputs.【F:backend/pipelines/daily_run.py†L505-L620】
- **Diagnostics** – Debug dumps and per-run metadata (IDs, timestamps, variant descriptions) ensure every persisted artifact is attributable and auditable, supporting forensics when LLM calls or external APIs misbehave.【F:backend/pipelines/daily_run.py†L394-L456】【F:backend/pipelines/daily_run.py†L690-L748】

Overall the pipeline is resilient to individual market failures and emphasises traceability, but retries remain manual and long-running LLM calls are executed sequentially without timeouts, leaving room for additional guardrails.

## Efficiency Considerations
- **Single-process execution** – Markets are fetched and processed sequentially per event bucket, and every strategy runs synchronously, which keeps control flow simple but limits throughput as experiment suites grow.【F:backend/pipelines/daily_run.py†L755-L823】
- **LLM usage** – Research and forecast strategies call external models one market group at a time; without batching, caching, or concurrency, large windows or high-volume suites will accrue latency and cost.
- **Data access** – The repositories lean on SQLAlchemy ORM facades and reuse a single session per run, which is sufficient for current scale but could become a bottleneck if parallelism is introduced.【F:backend/app/services/market_service.py†L40-L106】

## Iterative Development Experience
- **Introspection** – The manifest export and suite/stage stats make it easy to verify configuration before a run and to confirm what executed afterwards, dramatically improving the feedback loop for iterative prompt tuning.【F:backend/pipelines/daily_run.py†L142-L175】【F:backend/pipelines/daily_run.py†L658-L672】
- **Debug tooling** – CLI flags for dry runs, stage gating, debug dumps, and market limits let developers test narrow slices without risking the database, and the frontend immediately reflects processed data for visual QA.【F:backend/pipelines/daily_run.py†L184-L259】【F:frontend/app/page.tsx†L1-L82】
- **Collaboration** – Code-first suite configuration keeps complex wiring under version control, and the FastAPI/Next.js split cleanly separates ingestion logic from presentation, supporting parallel iteration across teams.【F:backend/pipelines/experiments/suites.py†L80-L200】【F:backend/app/main.py†L1-L110】

## Implementation Checklist
- [x] Added a manifest generator (`--list-experiments`) so ablation plans can be inspected without executing the pipeline.【F:backend/pipelines/daily_run.py†L658-L672】【F:backend/pipelines/experiments/manifest.py†L1-L99】
- [x] Captured per-suite stage statistics in the pipeline summary, enabling post-run audits of executed vs. skipped strategies.【F:backend/pipelines/daily_run.py†L142-L175】【F:backend/pipelines/daily_run.py†L1029-L1031】

## Future Opportunities
- Build a replay runner that reuses stored research artifacts to benchmark forecast variants offline, reducing ingestion load during ablation sweeps.
- Introduce parallelism or batching for expensive strategies once reliability monitoring is in place, balancing throughput with external rate limits.
