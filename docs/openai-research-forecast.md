# OpenAI-Powered Research & Forecast Flow

## Goals
- Add an automated research stage that can search the web for credible, up-to-date context about each Polymarket event.
- Feed the synthesized research into a lightweight forecasting stage that produces calibrated probability estimates using GPT‑5.
- Keep the implementation simple, inspectable, and easy to expand into richer experiment variants.

## Latest OpenAI API Capabilities To Leverage
- **Responses endpoint** (`client.responses.create`) is the unified interface for text, JSON, code, and tool-augmented generations.
- **Web search tool**: pass `{"type": "web_search"}` in the `tools` array so the assistant can fetch current information. The tool automatically cites URLs in the output metadata.
- **Structured JSON output** via `response_format={"type": "json_schema", ...}` keeps downstream parsing deterministic.
- **GPT‑5 models** (e.g. `gpt-5`, `gpt-5-mini`) offer improved reasoning and self-consistency, and respect JSON schema guarantees when paired with `json_schema` mode.
- **Client library**: `from openai import OpenAI` (Python SDK ≥1.42) handles retries, streaming, and future multimodal upgrades.

## Proposed Architecture
1. **Research strategy** (`OpenAIWebSearchResearch`)
   - Input: `EventMarketGroup` (markets grouped by Polymarket event).
   - Prompt the Responses API with event and market details.
   - Enable the `web_search` tool and ask for a concise situational brief plus bullet insights tied to URLs.
   - Return a `ResearchOutput` containing the structured JSON summary and a short Markdown excerpt for quick review.

2. **Forecast strategy** (`GPT5ForecastStrategy`)
   - Depends on the research artifact above (`requires=("openai_web_research",)`).
   - Calls the Responses API again with `model="gpt-5"` to convert research findings into outcome probabilities.
   - Accepts JSON schema that enumerates each contract slug/name and collects `probability` + `rationale`.
   - Returns a `ForecastOutput` per market, mapping outcomes to probabilities (0–1) and capturing the reasoning string.

3. **Suite wiring** (`OpenAIResearchForecastSuite`)
   - Expose both strategies behind a single experiment suite so the pipeline can enable it via `PROCESSING_EXPERIMENT_SUITES`.
   - Keep the suite opt-in (do not replace baseline) while the approach is validated.

## Request Patterns
- **Research Prompt Skeleton**
  ```python
  research_schema = {
      "type": "object",
      "properties": {
          "summary": {"type": "string"},
          "key_insights": {"type": "array", "items": {"type": "string"}},
          "confidence": {"type": "string"},
          "sources": {
              "type": "array",
              "items": {
                  "type": "object",
                  "properties": {
                      "title": {"type": "string"},
                      "url": {"type": "string"},
                      "snippet": {"type": "string"},
                  },
                  "required": ["title", "url", "snippet"],
                  "additionalProperties": False,
              },
          },
          "generated_at": {"type": "string"},
      },
      "required": ["summary", "key_insights", "confidence", "sources", "generated_at"],
      "additionalProperties": False,
  }
  json_mode = {
      "format": {
          "type": "json_schema",
          "name": "ResearchArtifact",
          "schema": research_schema,
      }
  }
  response = client.responses.create(
      model="gpt-4.1-mini",
      input=[
          {"role": "system", "content": "You are an analyst ..."},
          {"role": "user", "content": research_prompt},
      ],
      tools=[{"type": "web_search"}],
      text=json_mode,
  )
  ```
- The schema should include fields for `summary`, `drivers`, `confidence`, and `sources` (URL + snippet).
- Persist the raw JSON so forecasts can reuse it verbatim.
- Older SDKs that predate the `text` config can fall back to `response_format={...}`; the suite auto-detects which shape to use.
- Always provide the schema `name` alongside the JSON Schema body so both shapes satisfy the API contract.
- Stick to the subset of JSON Schema types supported by Structured Outputs (avoid `format` constraints unless explicitly required).
- Reference: [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses/create) — Structured Outputs.
- Additional implementation notes live in `docs/openai-responses-api-notes.md`.

- **Forecast Prompt Skeleton**
  ```python
  json_mode = {
      "format": {
          "type": "json_schema",
          "name": f"MarketForecast_{market_id}",
          "schema": forecast_schema,
      }
  }
  response = client.responses.create(
      model="gpt-5",
      input=[
          {"role": "system", "content": "You are a probability forecaster ..."},
          {"role": "user", "content": forecast_prompt},
      ],
      text=json_mode,
  )
  ```
  - Schema enumerates each outcome with `probability` (float 0–1) and `rationale`.
  - Optionally add `confidence` or `risk_flags` for debugging.

## Configuration
Add the following environment variables (documented in `.env.example`):
- `OPENAI_API_KEY` – required for all calls.
- `OPENAI_API_BASE` – optional override (Azure/OpenAI proxy).
- `OPENAI_ORG_ID` – optional; pass-through to match billing orgs.
- `OPENAI_PROJECT_ID` – optional; useful when scoping usage tracking.
- `OPENAI_RESEARCH_MODEL` – default `gpt-4.1-mini`.
- `OPENAI_FORECAST_MODEL` – default `gpt-5`.

## Error Handling & Observability
- Wrap every external call in retry logic with exponential backoff (SDK defaults cover transient HTTP 429/5xx).
- Capture `response.usage` metadata (tokens, search queries) in diagnostics to monitor cost.
- When the API fails, raise `ExperimentExecutionError` so the pipeline records the failure but continues other markets.
- Optionally log a redacted prompt to help auditing; never log secrets.

## Future Enhancements
- Cache research artifacts per event/date to avoid re-searching within the same run.
- Attach source URLs directly to frontend insights.
- Evaluate scoring calibration by backtesting GPT‑5 predictions against realized outcomes.
- Experiment with `gpt-5.1` reasoning models once available; they may increase accuracy at higher latency.
