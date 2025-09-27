# Research Strategy Refactor Plan

## Current State Assessment
- Historically `backend/pipelines/experiments/openai.py` bundled request plumbing, prompt design, schema configuration, and diagnostics into one file. The new package layout (`backend/pipelines/experiments/openai/`) splits shared helpers, research strategies, forecasts, and suite wiring into focused modules to keep OpenAI-specific concerns isolated.
- Strategy overrides are dictionaries pulled from `Settings.experiment_config`, but the merge logic is repeated for every strategy and assumes OpenAI without a clean abstraction for alternate providers.
- Research variants duplicate request construction (building messages, wiring JSON schemas, handling tools, etc.), making it hard to add or modify strategies without copy/paste.
- Forecasting and research stages do not share a consistent runtime contract; diagnostics, hash computation, and JSON extraction are scattered.
- Extensibility is limited: swapping providers, adding new research personas, or reusing orchestration flows requires editing large sections of the monolithic file.

## Phase 1 Plan — Establish LLM Runtime Abstractions
1. **Introduce a reusable runtime helper module.**
   - Create `backend/pipelines/experiments/llm_support.py` with `LLMRequestSpec`, `resolve_llm_request`, and utilities for JSON-mode, payload hashing, and usage extraction.
   - Move callable import/client factory resolution and provider readiness checks into this module.
2. **Create a structured base class for research strategies.**
   - Implement `StructuredLLMResearchStrategy` that handles runtime resolution, request assembly, schema injection, response parsing, and diagnostics.
   - Allow subclasses to override prompt building, schema definitions, payload post-processing, and diagnostic enrichment without touching plumbing.
3. **Refactor existing research strategies to subclass the new base.**
   - `OpenAIWebSearchResearch`, `AtlasResearchSweep`, `ScoutChainReflex`, `LexisDigestStructured`, and `HorizonSignalTimeline` adopt the base class hooks.
   - `ConsensusMatrixOrchestrator` keeps a custom flow but reuses the shared runtime helpers.
4. **Unify forecast strategy runtime.**
   - Update `GPT5ForecastStrategy` to call `resolve_llm_request` for consistent model, client, and override handling.
5. **Document the design.**
   - Capture the plan, trade-offs, and intended extensibility in `docs/research-strategy-refactor.md` to align future work.

## Phase 2 Refinement — Simplify for Extensibility
1. **Runtime contract simplification.**
   - `LLMRequestSpec` exposes helper methods for merging request options, producing diagnostics, and normalizing tool payloads, so strategies never touch raw override dictionaries.
   - Stage-specific override keys (e.g., `research_model`, `forecast_tools`) are handled centrally.
2. **Strategy ergonomics.**
   - Base class hooks (`build_messages`, `build_schema`, `extra_diagnostics`, `postprocess_payload`) make new strategies declarative: define prompts + schema, optional extras, and rely on the runtime scaffold.
   - Defaults such as web-search tools and fallback models come from the suite context instead of env-only configuration.
3. **Provider flexibility.**
   - `resolve_llm_request` accepts custom client factories and detects non-OpenAI providers, ensuring a clear error when a provider lacks a client factory.
   - OpenAI-specific API-key checks live alongside the resolver, enabling future providers to plug in without editing every strategy.
4. **Diagnostics consistency.**
   - Usage metrics, provider identifiers, and artifact hashing are generated uniformly, ensuring downstream persistence can rely on consistent diagnostics payloads.
5. **Implementation sequencing.**
   - Refactor helpers first, then migrate strategies one by one to confirm compatibility, concluding with forecast strategy alignment and suite wiring.

## Outcome
- Strategies become declarative, plumbing lives in a single helper module, and the system can host additional providers or personas with minimal boilerplate. Suites can be assembled either by subclassing `DeclarativeExperimentSuite` or by using the `suite(...)` helper so configuration remains ergonomic.
- Documentation and code structure now make the pipeline easier to reason about, review, and extend.
