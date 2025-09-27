# Daily Pipeline Test Plan

## Goal
Establish a reliable automated test suite that exercises the Polymarket ingestion pipeline end-to-end and guards core invariants so regressions are surfaced quickly.

## Scope
- Modules under `backend/ingestion`, `backend/pipelines`, and supporting repositories/services used by the daily pipeline.
- Primary execution path of `pipelines.daily_run.main` with representative configuration (dry run to avoid writes when possible).
- Polymarket API integration: at least one test must make a live call to ensure compatibility with the public interface.

Out of scope for this test pass:
- Frontend dashboards (covered separately by Next.js tests).
- Supabase persistence (requires credentials) beyond verifying ORM-layer calls are issued; these will be mocked.

## Proposed Tests

### 1. PolymarketClient pagination integration test
- Instantiate `PolymarketClient` with default settings and invoke `iter_markets()`.
- Assert that:
  - The generator yields at least one market.
  - Each market contains required keys (`id`, `slug`, `question`, `outcomes`, etc.) based on normalization expectations.
  - Pagination cursor logic advances (simulate by limiting to multiple pages using a small `page_size`).
- This test hits the live Polymarket API.

### 2. Normalization pipeline unit test
- Use a small fixture derived from a real market payload.
- Feed it through `ingestion.normalize.normalize_market`.
- Assert that normalized structure contains expected attributes and that optional fields are handled gracefully.

### 3. Daily pipeline dry-run integration
- Patch repositories (`MarketRepository`, `ProcessingRepository`) to avoid DB writes.
- Patch experiment suites to a no-op stub to isolate ingestion+grouping logic.
- Execute `pipelines.daily_run.run_pipeline` (or CLI entry) with `--dry-run`.
- Use `PolymarketClient` stub that feeds deterministic fixture markets to avoid live call during this test.
- Assert pipeline summary counts align with fixture (e.g., processed markets equals fixture count, failures zero).

### 4. Experiment manifest wiring test
- Load experiment suites via `pipelines.experiments.registry.load_suites` using stubs.
- Ensure manifest integrates with pipeline context and supports stage filters.
- Validate that `PipelineSummary.record_experiment_meta` aggregates statuses correctly.

## Test Infrastructure
- Add pytest configuration under `backend/tests`.
- Use `pytest` fixtures for:
  - `settings_override`: ensures tests use `.env.example` defaults with SQLite.
  - `polymarket_fixture_payload`: caches sample payload for reuse.
  - `dummy_pipeline_context`: constructs `PipelineContext` with stub repositories and strategies.
- Where network calls are required (test 1), mark with `@pytest.mark.network` to allow opt-in.

## Tooling / CI Considerations
- Add `pytest` dependency to backend requirements if missing.
- Provide documentation for running tests locally (`uv run pytest`).
- Ensure live-network test is resilient: handle HTTP 5xx by skipping with informative message after a small retry.

## Risks & Mitigations
- **Flaky network integration**: mitigate by setting timeout and capturing HTTP errors -> test fails with clear guidance.
- **Schema drift**: normalization test derived from fixture ensures we capture breaking API changes.
- **Long runtime**: limit number of markets consumed in integration tests to keep suite quick (<10s).

## Scrutiny & Revisions
- **Test overlap**: Test 4 (experiment manifest wiring) largely duplicates behavior exercised by the pipeline integration test once suites are stubbed. Instead of maintaining a separate manifest unit test, fold assertions about `PipelineSummary.record_experiment_meta` into the integration test using the stub strategies.
- **Live API resilience**: Directly asserting specific keys may fail if Polymarket introduces schema changes. Adjust plan so the integration test verifies minimal shape (e.g., `id` and `question`) and logs unexpected keys rather than hard failing.
- **Normalization fixtures**: Synthetic fixtures risk drifting from reality. Capture a real payload from the live API (persisted under `backend/tests/data/`) and pin it in tests. Add checksum to notice fixture drift.
- **Pipeline entry point**: `pipelines.daily_run` does not expose a dedicated `run_pipeline` function. To keep tests surgical, refactor slightly to extract a callable `run_pipeline(args, settings)` we can invoke. Alternatively, call `main()` with monkeypatched `sys.argv`. Prefer extraction for clarity.
- **Settings dependency**: Tests should avoid mutating global `settings`. Provide fixture that patches `app.core.config.get_settings` to return a frozen settings object with deterministic values (e.g., `ingestion_page_size=5`).
- **Network mark**: Introduce `pytest.ini` to register `network` marker to avoid `PytestUnknownMarkWarning`.

These adjustments will be incorporated into the implementation.

## TODO
1. Extract a `run_pipeline` helper from `pipelines.daily_run.main` (or expose existing core logic) to allow direct invocation in tests.
2. Introduce pytest config (`pytest.ini`) enabling `network` marker and default test discovery under `backend/tests`.
3. Add fixtures module under `backend/tests/conftest.py` with settings override, HTTP retry helper, and sample payload loader.
4. Capture a real Polymarket market payload and store under `backend/tests/data/sample_market.json` with checksum helper.
5. Implement tests:
   - `test_polymarket_client_live.py` covering live pagination with network marker and graceful skip on HTTP failure.
   - `test_normalize_market.py` verifying normalization from fixture and guarding optional fields.
   - `test_daily_pipeline_dry_run.py` stubbing repositories/strategies and asserting summary invariants including experiment meta aggregation.
6. Update backend requirements and documentation if pytest dependency missing.
7. Wire tests into CI instructions (README update if necessary).
