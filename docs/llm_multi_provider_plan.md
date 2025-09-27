# Multi-Provider LLM Architecture Plan

## Current Pain Points
- LLM integrations are hard-wired to OpenAI; `resolve_llm_request` assumes OpenAI defaults and imports.
- Experiment strategies import OpenAI helpers directly, preventing reuse with alternate providers.
- Configuration keys are OpenAI-specific (`openai_*`), limiting env-level overrides.
- JSON schema + tool invocation logic expect OpenAI Responses API semantics.
- Adding a second provider today would require copying OpenAI strategies and replacing plumbing piecemeal.

## Objectives
1. Abstract provider-specific concerns behind a common interface so experiments can reuse prompts across vendors.
2. Support OpenAI and Gemini out of the box, with hooks that make future providers (Anthropic, etc.) trivial to add.
3. Preserve current experiment configuration ergonomics (strategy overrides still land in `Settings.experiment_config`).
4. Keep per-provider defaults (API keys, model choices, structured-output settings) centralized and testable.
5. Maintain parity in diagnostics (usage metadata, payload hashing) regardless of provider.

## Proposed Architecture

### 1. Provider Registry
- Create `backend/app/services/llm/__init__.py` package with:
  - `providers.py`: defines `LLMProvider` protocol/dataclass capturing required hooks.
  - `registry.py`: maintains a mapping of provider names → provider objects. Provide `register_provider` + `get_provider` helpers with module-level defaults for OpenAI/Gemini.
- Provider contract responsibilities:
  - `name`: canonical provider identifier (e.g., `"openai"`, `"gemini"`).
  - `require_api_key`: flag to gate runs when credentials missing.
  - `resolve_client(context, overrides)`: return API client instance.
  - `default_model(stage, context)`: stage-aware fallback.
  - `default_request_options(stage, context)`: optional stage defaults.
  - `default_tools(stage, context)`: optional stage defaults.
  - `invoke(request: LLMRequestSpec, payload: Mapping[str, Any])`: execute request, attach provider-specific requirements (tools serialization, request shape).
  - `json_mode_kwargs(client, schema_name, schema)`: provider-specific structured-output wiring.
  - `extract_json(response)`, `usage_dict(response)`: normalization hooks.
- Ship built-in providers:
  - `OpenAIProvider` replicating current logic but relocated.
  - `GeminiProvider` using Google Generative AI SDK.

### 2. Request Resolution Flow
- Refactor `LLMRequestSpec` in `llm_support.py` to include `provider: LLMProvider` and helper methods (`invoke`, `json_mode_kwargs`, `extract_json`, `usage_dict`).
- `resolve_llm_request` steps:
  1. Identify provider via overrides (default `"openai"`).
  2. Lookup provider from registry (raise descriptive error if missing).
  3. Delegate API-key readiness check to `provider.ensure_ready` (a thin helper calling `require_api_key`).
  4. Resolve client via provider (respecting overrides `client` / `client_factory`).
  5. Resolve model via overrides or provider default per stage.
  6. Merge request options + tools using overrides first, falling back to provider defaults.
  7. Return populated `LLMRequestSpec` with bound provider.
- Keep override precedence identical to today (experiment override > default_model argument > provider fallback).

### 3. Strategy Updates
- Update `StructuredLLMResearchStrategy` & forecast equivalents to:
  - Call `runtime.json_mode_kwargs(...)` instead of module-level helper.
  - Invoke LLM via `runtime.invoke(payload, tools=...)` to allow providers to reshape payloads.
  - Extract artifacts/usage via `runtime.extract_json(response)` + `runtime.usage_dict(response)`.
- Remove direct imports of OpenAI-specific helpers from strategies.
- Ensure `default_tools` semantics still work: provider decides whether to send native `tools` block vs. Gemini function-calling equivalents.

### 4. Settings & Configuration
- Extend `Settings` minimally:
  - `llm_default_provider: str = "openai"` to drive fallback provider selection.
  - Keep existing OpenAI keys (`openai_*`) untouched for backwards compatibility.
- Add Gemini-specific settings alongside OpenAI ones:
  - `gemini_api_key: str | None`.
- Keep model defaults in code (strategy attributes + provider fallbacks) instead of `.env` values so
  each experiment can evolve independently.
- Update `.env.example` with Gemini fields and documentation comment.
- Document provider override contract in README/docs.

### 5. Gemini Provider Implementation
- Use `google.generativeai` SDK:
  - Configure via `genai.configure(api_key=...)` when client created (thread-safe reuse).
  - Client object: `GenerativeModel` per model or wrapper returning `.generate_content`.
- Structured output:
  - Use `response_mime_type="application/json"` + `response_schema=schema` in `GenerationConfig` (supported in latest API).
- Tooling parity:
  - Map OpenAI `web_search` tool to Gemini `google_search_retrieval` (document limitations); allow overrides to disable if unsupported.
- Response normalization:
  - Extract JSON from `response.text` or `response.candidates[0].content.parts`.
  - Build usage dict using `response.usage_metadata` (fields: `prompt_token_count`, `candidates_token_count`, etc.).

### 6. Migration Steps
1. Introduce provider infrastructure & update tests/docs.
2. Move OpenAI-specific helpers into provider class; ensure `resolve_llm_request` logic preserved.
3. Implement Gemini provider with schema/tool adapters.
4. Refactor experiment strategies to use provider-agnostic runtime helpers.
5. Update configuration + `.env.example` + docs.
6. Add smoke test / utility verifying provider lookup + JSON extraction for stub responses (unit tests or docstring example).

### 7. Testing & Validation
- Add targeted unit tests in `backend/tests/` (create new module if absent) for:
  - Provider registry lookups + error handling.
  - `resolve_llm_request` override precedence.
  - Gemini JSON extraction with mocked response objects.
- Run pipeline dry-run with `--stage research --limit 1` using mock clients to ensure strategy path unaffected (if runtime limitations, document manual QA steps).

### 8. Future Extensions
- Add CLI flag/env var to set global provider per stage (e.g., run research on Gemini, forecast on OpenAI).
- Support streaming/responses for providers that expose them (Anthropic).
- Persist provider metadata alongside artifacts for analytics.

## Critique Round 1
- Provider registry API is verbose; consider grouping hooks to avoid large interface surface.
- Plan assumes ability to translate OpenAI tool syntax to Gemini; may be unrealistic for initial integration.
- Settings additions may overcomplicate configuration (introducing `llm_providers` dict without immediate use).
- Testing plan references `backend/tests/` but repo lacks tests; need lighter-weight approach.

## Adjustments After Critique
- Simplify provider contract to core hooks: `ensure_ready`, `build_client`, `default_model`, `default_request_options`, `default_tools`, `invoke`, `json_mode_kwargs`, `extract_json`, `usage_dict`. Skip `llm_providers` nested dict for now to keep settings simple; rely on explicit provider-specific fields.
- Document limitation that Gemini ships with no tool support initially; experiments using `web_search` must override `tools` when selecting Gemini.
- Replace unit test plan with lightweight stub-based tests colocated next to helpers (e.g., `backend/pipelines/experiments/test_llm_support.py`) to match repo conventions.

## Final Plan Snapshot
- Implement provider registry with streamlined hook surface and built-in OpenAI/Gemini providers.
- Extend settings minimally (default provider + Gemini credentials/models) to avoid premature generalization.
- Update LLM request flow + strategies to depend on provider hooks rather than OpenAI client internals.
- Provide Gemini integration without search-tool parity in v1; document requirement for manual tool override.
- Add focused tests for provider lookup and JSON extraction without introducing heavy testing harness.
