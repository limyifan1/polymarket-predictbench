# Pipeline token optimization analysis

## Current research execution flow
- The daily pipeline groups markets by event and iterates through each configured suite for every group, running all research strategies that are enabled for that suite before executing forecasts.【F:backend/pipelines/daily_run.py†L835-L856】
- Research strategies return `ResearchOutput` objects that are recorded per suite variant; the pipeline persists the artifacts and ties them back to the originating experiment run metadata.【F:backend/pipelines/daily_run.py†L954-L989】【F:backend/pipelines/experiments/base.py†L26-L71】
- Suites are defined independently, so the same strategy class can appear in multiple suites. For example, both the OpenAI and Superforecaster suites include the `OpenAIWebSearchResearch` variant, but the pipeline treats these as separate runs because the suite-scoped experiment name differs.【F:backend/pipelines/experiments/openai/suite.py†L12-L25】【F:backend/pipelines/experiments/superforecaster/suite.py†L11-L25】【F:backend/pipelines/experiments/llm_support.py†L246-L300】

## Sources of duplicated LLM spend
- Because `_run_suite_for_group` instantiates and runs every research strategy for each suite in isolation, the same research prompt is re-issued for every suite that references it. The current implementation does not check for pre-existing results or share artifacts across suites.【F:backend/pipelines/daily_run.py†L538-L660】【F:backend/pipelines/daily_run.py†L842-L855】
- Forecast strategies can optionally consume research outputs by name, but today they only see artifacts produced by their own suite. The Superforecaster forecast lists `openai_web_search`, `atlas_research_sweep`, and `horizon_signal_timeline` as optional inputs even though those artifacts are only produced by the OpenAI suite in the current registry, which implies unrealised sharing opportunities.【F:backend/pipelines/experiments/superforecaster/forecast_calibrated.py†L107-L182】
- Experiment-level overrides (provider, model, request options) are keyed by the suite-specific experiment name, so any change in configuration causes separate LLM calls even if the underlying strategy code is identical.【F:backend/pipelines/experiments/llm_support.py†L246-L300】

## Common research strategy catalog
1. **Define suite-agnostic strategy identities**
   - Introduce a shared catalog that enumerates every research strategy once, describing its inputs, expected outputs, and canonical configuration. Suites would reference catalog entries rather than embedding strategy constructors directly, which guarantees that `OpenAIWebSearchResearch` means the same thing everywhere and keeps model/prompt drift under control.【F:backend/pipelines/experiments/llm_support.py†L246-L300】【F:backend/pipelines/experiments/openai/base.py†L58-L116】
   - Catalog entries can expose overridable knobs (e.g., temperature, context window), but the overrides must be declared as deltas layered on top of the shared definition. When a suite sticks with the canonical configuration, the pipeline can confidently reuse artifacts across all suites that opt in to the same identity.

2. **Group suites by research needs**
   - Before the run, collapse all suites into “research bundles” keyed by catalog identity plus normalized override parameters. Each bundle is executed once per market group, and the resulting artifact is registered under every suite that belongs to the bundle. This keeps suite-level reporting intact while eliminating duplicated LLM calls.【F:backend/pipelines/daily_run.py†L714-L760】【F:backend/pipelines/daily_run.py†L842-L855】
   - Bundles also provide a natural home for shared validation rules (for example, minimum reasoning quality or reference link checks) so we can improve output consistency while saving tokens.

3. **Explicit suite overlays for bespoke logic**
   - Some suites may need custom prompts or guardrails. Capture those as overlay strategies that wrap a shared base strategy rather than re-implementing it. The overlay documents how it diverges from the catalog definition and signals to the scheduler that reuse is unsafe unless all overlay parameters match.【F:backend/pipelines/experiments/base.py†L26-L71】
   - This ensures we only pay for truly unique research paths and pushes teams to justify bespoke variants.

## Static analysis for artifact reuse
1. **Compile strategy dependency graphs before execution**
   - Expand the pipeline bootstrap to scan every suite, load the catalog entries they reference, and build a graph of strategy dependencies. With the graph, we can determine which artifacts feed into which forecasts, highlight unused results, and emit a minimal execution plan that avoids redundant work.【F:backend/pipelines/daily_run.py†L714-L760】【F:backend/pipelines/daily_run.py†L842-L989】
   - The same analysis can populate a manifest that the research runner and forecast runner share, allowing forecasts to request artifacts by stable identity instead of suite-specific names.

2. **Pre-compute artifact fingerprints**
   - During static analysis, derive the input fingerprint for each catalog entry (e.g., hash of normalized market context plus resolved config). If two suites produce identical fingerprints, the manifest records that they can reuse a single artifact instance. When we persist run metadata, we link each suite back to the shared artifact to preserve auditing trails.【F:backend/pipelines/daily_run.py†L954-L989】
   - Fingerprints give us a deterministic key we can reuse across pipeline invocations, so future runs can skip recomputing artifacts when both the market snapshot and configuration remain unchanged.

3. **Validate cross-suite compatibility upfront**
   - The analysis stage can also enforce that forecasts only depend on artifacts that will exist in the shared manifest. If a forecast references a strategy that no suite produces, we fail fast before any tokens are spent. Conversely, we can surface warnings when two suites produce near-identical artifacts but do not opt into sharing, nudging maintainers to align configurations.

## Recommended next steps
- Model the research catalog as metadata objects (name, version, canonical config, overridable fields) and retrofit existing suites to reference it. Start with high-usage strategies such as `openai_web_search` and `atlas_research_sweep` to maximise immediate reuse.【F:backend/pipelines/experiments/openai/suite.py†L12-L25】【F:backend/pipelines/experiments/superforecaster/suite.py†L11-L25】
- Extend pipeline bootstrapping to build the static manifest: resolve catalog references, bucket suites into research bundles, compute fingerprints, and emit the execution plan shared by research and forecast stages.【F:backend/pipelines/daily_run.py†L714-L989】
- Update the forecast runner to consume artifacts via catalog identity (plus overlay qualifiers) so shared outputs automatically satisfy cross-suite dependencies without additional LLM calls.【F:backend/pipelines/daily_run.py†L599-L660】【F:backend/pipelines/experiments/superforecaster/forecast_calibrated.py†L107-L182】

## Implementation snapshot
- Research strategies now declare an optional `shared_identity`; the OpenAI web search research opts in so the OpenAI and Superforecaster suites execute it once per market group and reuse the artifact across both suites.【F:backend/pipelines/experiments/openai/base.py†L98-L116】【F:backend/pipelines/experiments/openai/research_web_search.py†L9-L49】
- The daily pipeline builds deterministic research bundles keyed by shared identity plus configuration fingerprint, runs a canonical strategy per bundle, and fans the results out to every participating suite while preserving suite-level metadata and persistence flows.【F:backend/pipelines/daily_run.py†L356-L533】【F:backend/pipelines/daily_run.py†L912-L1105】

This approach replaces ad-hoc caching with an explicit, reusable strategy catalog and a static execution plan. It reduces redundant tokens, clarifies configuration ownership, and gives us the foundation to reuse artifacts both within a run and across daily executions when nothing meaningful changes.
