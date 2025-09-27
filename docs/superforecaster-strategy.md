# Superforecaster Strategy Research & Implementation Plan

## Research Summary
- **Origins.** The Good Judgment Project demonstrated that trained forecasting teams using structured workflows could outperform intelligence analysts by 30–70% on geopolitical questions by combining crowd wisdom with rigorous evaluation metrics such as Brier scores.[^gjp-wikipedia]
- **Key practices identified in the tournament literature** include: establishing reference-class base rates, decomposing questions into mutually exclusive scenarios, updating beliefs incrementally as indicators arrive, and tracking calibration using scoring rules.[^mellers2014]
- **Traits of top performers.** Superforecasters maintain probabilistic thinking, actively seek disconfirming evidence, document their reasoning, and follow pre-committed update triggers to avoid recency bias.[^entrepreneur2022]

[^gjp-wikipedia]: [“The Good Judgment Project,” Wikipedia](http://en.wikipedia.org/wiki/Superforecasting)
[^mellers2014]: Mellers et al., “Psychological strategies for winning a geopolitical forecasting tournament,” *Psychological Science* 25(5):1106–1115 (2014).
[^entrepreneur2022]: Liz Brody, “Meet the Elite Team of Superforecasters Who Have Turned Future-Gazing Into a Science,” *Entrepreneur*, Jan 1 2022. (Referenced in the Wikipedia article above.)

## Application to PredictBench
1. **Dedicated research artifact.** Superforecasters begin with an outside-view baseline before layering inside-view considerations. The new `SuperforecasterBriefingResearch` strategy captures:
   - A succinct reference class description and quantitative base rate.
   - Scenario decomposition with probabilities and impact assessments.
   - Key uncertainties plus explicit monitoring triggers for future updates.
2. **Calibrated forecasting step.** `SuperforecasterDelphiForecast` consumes the briefing and optional OpenAI research, then:
   - Prompts GPT-5 with explicit instructions to anchor on the base rate and reason through scenario adjustments.
   - Blends the model’s output with market-implied base rates (40% regression to the outside view) to emulate superforecaster calibration discipline.
   - Emits diagnostics that log raw model probabilities, the base-rate blend, and monitoring plans so downstream scoring can audit the update path.
3. **Experiment suite structure.** `build_superforecaster_suite()` wires the briefing with the existing OpenAI web-search research plus the calibrated forecast strategy. The suite is registered alongside `baseline` and `openai`, making it easy to activate via `--suite superforecaster` during pipeline runs.

## Usage Notes
- Set `OPENAI_API_KEY` and optional model overrides as documented in `docs/openai-research-forecast.md` to run the suite.
- When experimenting locally, run `uv run python -m pipelines.daily_run --suite superforecaster --dry-run --limit 3` to validate the new wiring before persisting results.
- The diagnostics stored in `experiment_results` expose both the LLM-derived probabilities and the blended calibration so evaluation notebooks can compute Brier/log scores against either component.
