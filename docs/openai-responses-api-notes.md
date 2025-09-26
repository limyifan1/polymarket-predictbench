# OpenAI Responses API Notes

## Structured Output Requirements
- Use `text={"format": {"type": "json_schema", "name": <SCHEMA_NAME>, "schema": <JSON_SCHEMA>}}` when working with SDK >=1.3x that exposes the `text` parameter on `client.responses.create`.
- The `json_schema` entry must be a pure JSON Schema object. Do not wrap it in auxiliary metadata keys; the schema `name` is provided separately at the top level.
- Provide stable, unique schema names (e.g., `ResearchArtifact`, `MarketForecast_<market_id>`) to help the API distinguish formats across multiple calls in the same conversation.
- For SDKs that predate the `text` parameter, fall back to `response_format={"type": "json_schema", "name": <SCHEMA_NAME>, "schema": <JSON_SCHEMA>}`; both shapes are accepted by the API.
- Reference: [OpenAI Responses API — Structured Outputs](https://platform.openai.com/docs/api-reference/responses/create#responses-create-text).
- The Structured Outputs surface supports a restricted JSON Schema subset; omit secondary `format` annotations unless the docs explicitly list them as supported.

## Web Search Tool Usage
- Supply `tools=[{"type": "web_search"}]` to enable federated search within the Responses call.
- The tool may emit URL metadata in the response; capture and preserve this context for audit trails.
- Reference: [OpenAI Tool Use — Web Search](https://platform.openai.com/docs/guides/function-calling/web-search).

## Error Handling Guidance
- HTTP 400 errors typically indicate missing parameters (`text.format.<field>`). Confirm the payload shape matches the documented schema requirements above.
- HTTP 429/5xx responses are transient; rely on the SDK's built-in retry logic, but surface token usage for cost monitoring (`response.usage`).
- When retries are exhausted, surface an `ExperimentExecutionError` so the pipeline records the failure and moves on without corrupting downstream state.

## Prompt Hygiene Checklist
- Avoid logging raw prompts that may contain sensitive data; rely on diagnostics payloads for anonymized telemetry.
- Keep research prompts concise and structured so the model understands expectations (summary, insights, confidence, sources).
- For forecasting prompts, include the full research JSON and target market question to ground the probabilities.

Keeping these guardrails in place prevents contract mismatches with the Responses API and reduces the incidence of runtime errors during ingestion runs.
