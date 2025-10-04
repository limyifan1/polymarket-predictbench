# Superforecasting Research Process

This playbook distills the research and reasoning workflow described in *Superforecasting: The Art and Science of Prediction* by Philip E. Tetlock and Dan Gardner (2015) and supporting publications from the Good Judgment Project. It focuses on the day-to-day habits that distinguished top forecasters in the IARPA tournaments.

## Core Principles
- **Precision in questions:** Nail down the exact claim, timeframe, and resolution criteria before estimating. Ambiguity is the enemy of calibration.
- **Outside view first:** Start from base rates using a relevant reference class. Treat this as the prior before incorporating case-specific details.
- **Deliberate decomposition:** Break big problems into smaller, more knowable pieces ("Fermi-ization"). Quantify the pieces whenever possible.
- **Actively open-minded:** Generate alternative hypotheses, hunt for disconfirming evidence, and update quickly when better information arrives.
- **Bayesian updating:** Treat beliefs as provisional. Adjust probabilities incrementally as new signals arrive, avoiding dramatic swings without proportionate evidence.
- **Calibration feedback loop:** Track past forecasts, compare to outcomes, and recalibrate judgment based on empirical accuracy metrics such as Brier scores.
- **Collaborative cross-checks:** Share reasoning transparently, challenge assumptions, and incorporate diverse viewpoints while avoiding groupthink.

## Step-by-Step Workflow
1. **Clarify and scope the forecast.**
   - Rephrase the market question as a precise probabilistic statement with explicit resolution criteria and time horizon.
   - Note any hidden assumptions or terms that require definitions.
2. **Decompose the problem.**
   - Map the causal chain or decision tree.
   - Identify discrete sub-questions (milestones, actors, necessary conditions) that determine the outcome.
3. **Establish the base rate (outside view).**
   - Select a reference class of analogous historical events.
   - Compute or cite the frequency distribution to derive an initial probability.
4. **Analyze the inside view details.**
   - Gather current facts, context, and indicators relevant to each sub-question.
   - Evaluate how the specifics push the estimate above or below the base rate.
5. **Construct and stress-test scenarios.**
   - Outline plausible pathways to the outcome and the key catalysts or blockers for each.
   - Estimate conditional probabilities for critical branches.
   - Look for disconfirming evidence and alternative explanations.
6. **Synthesize the probability estimate.**
   - Combine the adjusted sub-estimates into a coherent forecast.
   - Cross-check with outside benchmarks and ensure the final number is well-calibrated (e.g., avoid unjustified certainty).
7. **Document evidence and confidence.**
   - Cite sources, note data quality, and flag uncertainties or information gaps.
   - Capture indicators that would trigger an update.
8. **Plan for updates.**
   - Specify monitoring actions, update cadences, and thresholds for revising the forecast.
   - Record outstanding questions or data needs for follow-up research.

## Communication Guidelines
- Summaries should surface the question framing, current probability, reasoning chain, evidence quality, and monitoring plan.
- Separate facts from judgment; mark assumptions explicitly.
- Use precise probability language (percentages or odds) instead of vague qualifiers.
- Reference sources inline (e.g., `[source: publication, date]`) to maintain auditability.
- Close with expected triggers for upward or downward revisions and note competing viewpoints.

## Implications for PredictBench Experiments
- Prompts should force the model to walk through clarification, base rate estimation, decomposition, scenario analysis, synthesis, and update planning in order.
- Responses should read like a forecast logbook entry: structured narrative sections with explicit probabilities, evidence, and monitoring notes.
- Any automation should preserve iterative updates, making it easy to rerun the process when new information arrives.
