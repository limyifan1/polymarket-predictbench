# AGENTS.md — Polymarket PredictBench

## Repository Map
- `backend/` FastAPI app, ingestion clients, and the daily pipeline.
- `frontend/` Next.js dashboard (App Router) that reads from the API.
- `data/` Default SQLite artifacts (ignored by Git, but created at runtime).
- `docs/` Architecture notes (see `docs/polymarket-open-markets.md`).
- `.env.example` Template shared by backend and frontend settings.

## Backend (FastAPI + pipeline)
1. Python 3.11+ is required. Install [uv](https://github.com/astral-sh/uv) if you want faster env management.
2. Create a virtualenv (`uv venv` or `python -m venv .venv`) inside `backend/` and install deps:
   ```bash
   cd backend
   uv venv && uv pip install -r requirements.txt
   # or: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
   ```
3. Copy the root `.env.example` to `.env` and adjust values. The backend reads it via `pydantic-settings`.
4. Export `PYTHONPATH=$(pwd):$PYTHONPATH` (or rely on `uv run`) so module imports resolve.
5. Run the API locally with hot reload:
   ```bash
   uv run uvicorn app.main:app --reload --port 8000
   ```

### Database and environment
- Default dev DB: `sqlite:///../data/predictbench.db` relative to `backend/` (created automatically).
- Production runs (`ENVIRONMENT=production`) must provide `SUPABASE_DB_URL`; the config normalizes it to `postgresql+psycopg://` and enforces `sslmode=require`.
- Supabase's transaction pooler drops `PREPARE` calls, so the SQLAlchemy engine sets psycopg's `prepare_threshold=0` and `prepared_statement_cache_size=0`—leave these intact when adjusting database options.
- `SUPABASE_SERVICE_ROLE_KEY` is required for CI/automation when writing to Supabase.
- Extra Polymarket filters live in `INGESTION_FILTERS` (JSON string) and `INGESTION_PAGE_SIZE`.
- `GEMINI_ADDITIONAL_API_KEYS` accepts a comma-separated or JSON list of fallback Gemini API keys; the LLM service randomises the order per request and falls back if a key is rate-limited or errors.

### Daily pipeline
- Main entry point: `backend/pipelines/daily_run.py`.
- Typical runs:
  ```bash
  uv run python -m pipelines.daily_run --dry-run            # fetch + validate without writing
  uv run python -m pipelines.daily_run                      # full ingestion + experiments + persistence
  uv run python -m pipelines.daily_run --window-days 3      # adjust close-date horizon
  uv run python -m pipelines.daily_run --target-date 2025-03-01
  uv run python -m pipelines.daily_run --summary-path ../summary.json
  ```
- Flags:
  - `--dry-run` skips writes (use first when touching ingestion code).
  - `--window-days` / `--target-date` control the close-date window (mutually exclusive).
- `--summary-path` writes a JSON artifact with run metadata and failures.
- `--limit` is helpful when debugging a narrow slice of markets.
- `--event-batch-size` controls how many event groups execute in parallel (defaults to `PIPELINE_EVENT_BATCH_SIZE`, set to 4).
- Connection resiliency knobs: adjust `PIPELINE_DB_RETRY_ATTEMPTS` and `PIPELINE_DB_RETRY_BACKOFF_SECONDS` to tune retry counts/backoff when Supabase drops idle connections.
- `--suite` (repeatable) runs only selected suites from `PROCESSING_EXPERIMENT_SUITES`.
  - `--stage` controls which stages execute (`research`, `forecast`, or `both`).
  - `--include-research` / `--include-forecast` filter variants by name or `suite:variant`.
  - `--debug-dump-dir` points to a directory where JSON payload dumps are written (default comes from `PIPELINE_DEBUG_DUMP_DIR`); use `--no-debug-dump` to disable for a run.
- `--experiment-override` and `--experiment-override-file` can be used to
  change experiment parameters without editing suite definitions (see the
  [Pipeline Runbook](docs/pipeline-runbook.md) for details).
- Legacy script `python -m scripts.ingest_markets` exists but bypasses processing safeguards—prefer the pipeline.

## Frontend (Next.js)
1. Node.js 18+.
2. Install dependencies and start the dev server:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
3. The dashboard expects the API at `http://localhost:8000`; override via `NEXT_PUBLIC_API_BASE_URL`.
   Set `NEXT_PUBLIC_PROD_API_BASE_URL` and choose the production dataset in the
   UI filters to read from the Supabase-backed API.
4. Lint with `npm run lint` before committing UI changes.
5. Avoid `npm run build` during agent sessions if you rely on hot reload; restart `npm run dev` after dependency updates.

## Testing & QA expectations
- No formal pytest/Vitest suites live in the repo yet. Use the pipeline dry-run plus manual API smoke tests as the regression net.
- Recommended quick checks before submitting changes:
  - `uv run python -m pipelines.daily_run --dry-run`
  - `curl "http://localhost:8000/healthz"` (API responsiveness)
  - `curl "http://localhost:8000/markets?status=open" | jq '.items | length'` (basic data sanity)
  - `npm run lint` inside `frontend/`
- Add targeted scripts/tests when you introduce functionality with non-trivial logic—prefer colocating them next to the new code.

## CI & automation
- `.github/workflows/daily-pipeline.yml` runs every day at 07:00 UTC and on manual dispatch.
- Secrets required in GitHub: `SUPABASE_DB_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` (optionally `OPENAI_API_BASE`, `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID`, `GEMINI_ADDITIONAL_API_KEYS`).
- Repository variables: `INGESTION_FILTERS`, `INGESTION_PAGE_SIZE`.
- Workflow emits `artifacts/pipeline-summary.json`; keep that path stable if you touch the workflow so downstream tooling continues to find it.

## Coding conventions & review tips
- Python: keep modules type-annotated, prefer dependency injection via `app.core.config` settings, and log context with `loguru`.
- Database access flows through `backend/app/crud.py`; update schema definitions in `models.py` alongside migrations (Alembic is available).
- Frontend: use functional React components, colocate table helpers in `frontend/lib/`, and favor TypeScript for shared types (`frontend/types/`).
- When touching API contracts, update both FastAPI schemas (`backend/app/schemas.py`) and the frontend types.
- Keep documentation in sync (`README.md`, `docs/`, and this file) when workflows or commands change.

## Agent checklist before submitting changes
- [ ] Ran the daily pipeline with `--dry-run` and `--limit 1` if ingestion logic changed.
- [ ] Confirmed API + frontend dev servers start without errors.
- [ ] Executed `npm run lint` for UI changes and manual sanity checks for backend changes.
- [ ] Added/updated docs or comments for non-obvious logic.

## Debugging Playbooks
The playbooks below live in this guide until we decide on a permanent home. Quote them verbatim when reinforcing expectations; softening the language breaks the safeguards they encode.

### Systematic Debugging — Four-phase root cause framework
- Iron law: `NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST`. Move through Root Cause → Pattern → Hypothesis → Implementation in order; skipping a phase voids the process.
- Phase 1 demands reproducibility, review of recent changes, and boundary-by-boundary instrumentation so you know exactly where data fails.
- Phase 3 permits one hypothesis at a time. When a test fails, stop, return to Phase 1, and reformulate—never stack fixes.
- Phase 4 requires proving the bug before the fix (failing test or reproduction), applying a single change, and verifying afterward. Three failed fixes means the architecture is wrong: escalate instead of trying a fourth.
- Red-flag phrases—“should work”, “one more fix”, “seems fine”—are automatic stop signals. Call them out and rewind to Phase 1.
- Creation notes: The original authors hardened the language against pressure. If you feel tempted to weaken a rule, reread this section before editing.

### Root Cause Tracing — Call-chain forensics
- Principle: track symptoms backward until you identify the first bad input; never settle for treating the point where the error appears.
- Follow the loop: observe the symptom → identify the immediate cause → ask who called it with bad data → keep tracing upward until you reach the origin.
- When manual tracing stalls, instrument the suspect function (e.g., capture `new Error().stack`) and log directory, cwd, environment, timestamps.
- Use the decision diagrams in the original write-up as reminders: if you’re tempted to “fix at symptom,” you missed the real source.
- Companion to Systematic Debugging: tracing reveals the source so that Phase 4 can harden the entry point.

### Defense-in-Depth Validation — Layered protection
- Validate at every layer data passes through so bad inputs become structurally impossible.
- Layer 1 (entry): reject obviously invalid payloads at boundaries (API, CLI, ingestion request).
- Layer 2 (business logic): enforce operation-specific invariants before mutating state.
- Layer 3 (environment guards): block context-specific hazards (e.g., refuse `git init` outside temp dirs during tests, enforce Supabase SSL).
- Layer 4 (debug instrumentation): log directory, cwd, and stack before risky operations to aid post-mortems.
- Four-step remediation loop: trace the data flow, list checkpoints, add validation at each layer, and try to bypass each layer to confirm coverage.
- Apply analogous layers in pipeline changes—request filters, suite guards, environment safety rails, structured logging.

### Verification Before Completion — Evidence-first handshake
- Iron law: `NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE`. Every success statement must cite the command you just executed.
- Gate function: identify the proving command, run it, read the output end-to-end, verify it supports the claim, then communicate.
- Prior runs, partial checks, or “should pass” are invalid. Tiredness and deadlines are not exemptions.
- Tie this playbook to the agent checklist: never check an item until the verifying command has run in-session.

## Practice Drills
- **Academic quiz** — Ask the six questions from the original prompt (four phases, pre-fix requirements, failed hypothesis behavior, multiple-fix guidance, handling uncertainty, skipping for simple bugs). Answers must quote Systematic Debugging verbatim.
- **Pressure Test 1: Production outage** — Choose between rapid retries vs. full investigation; debrief against the Iron Law to reinforce why skipping Phase 1 is failure.
- **Pressure Test 2: Exhaustion and sunk cost** — Scenario highlights why “good enough” timeouts violate the process; use it to rehearse restarting from Phase 1 when the last fix fails.
- **Pressure Test 3: Authority pressure** — Practice pushing back when senior engineers prefer shortcuts. Reinforces quoting the playbooks rather than appealing to hierarchy.
- Encourage engineers to answer honestly, then review the decisions against the stop signals and Iron Laws above.
