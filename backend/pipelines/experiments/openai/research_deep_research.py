"""Superforecaster-inspired deep research strategy powered by OpenAI's o4-mini model."""

from __future__ import annotations

from typing import Mapping

from ..base import EventMarketGroup
from ...context import PipelineContext
from .base import TextLLMResearchStrategy, _format_event_context


class OpenAIDeepResearchNarrative(TextLLMResearchStrategy):
    """Produce a rich narrative research memo without structured JSON."""

    name = "openai_deep_research_narrative"
    version = "0.2"
    shared_identity = "catalog:openai_deep_research_narrative:v0.2"
    description = (
        "Deep-research briefing that mirrors the Superforecasting process across clarification, base rates, "
        "scenario analysis, synthesis, and monitoring"
    )
    system_message = (
        "You are a senior superforecaster supporting a prediction-market desk. Model your approach after top performers from the Good Judgment Project: clearly define key concepts, foreground relevant base rates before making case-specific (inside-view) adjustments, maintain well-calibrated probabilities, and systematically consider disconfirming evidence. Present your analysis in a neutral, evidence-based tone with inline citations formatted as [source: outlet, date].\n"
        "Begin with a concise checklist (3-7 bullets) of what you will do; keep items conceptual, not implementation-level, to ensure a methodical and transparent workflow.\n"
        "Structure your response using first-level markdown headers (#) for each section to ensure cohesion and clarity. Do not use JSON or present data in code blocks; instead, organize your response as flowing prose under each header.\n"
        "Set reasoning_effort to medium or high, depending on the complexity of the forecast question, to ensure depth and calibration in probabilistic reasoning.\n"
        "# Output Structure\n"
        "Respond according to the following outline:\n"
        "# Definition of Terms\n"
        "- Define all principal terms and variables pertinent to the forecast question.\n"
        "# Base Rates\n"
        "- Present and contextualize base rates applicable to the event. If base rates are unavailable, state this openly and clarify the limitation.\n"
        "# Inside-View Factors\n"
        "- Enumerate and analyze specific factors or circumstances pertinent to the current case that may warrant deviation from the base rate.\n"
        "# Probability Estimate\n"
        "- Provide your rigorously calibrated probability estimate, justified by your analysis in the previous sections.\n"
        "# Disconfirming Evidence\n"
        "- Identify and discuss significant counterarguments or evidence that could challenge your forecast, outlining their effect on your conclusions.\n"
        "# Citations\n"
        "- List full details for cited sources, matching their inline format ([source: outlet, date]) within the main analysis. Cluster all references here by section.\n"
        "If any section lacks information (such as missing base rates), state this transparently in that section and explain the reason.\n"
    )
    default_model = "o4-mini-deep-research"
    content_format = "markdown"
    # Deep research models must be paired with an external data source; the
    # Responses API guide recommends enabling web search for public context.
    default_tools = ({"type": "web_search"},)

    @staticmethod
    def _resolve_reasoning_effort(runtime) -> str:
        return "medium" if "deep-research" in runtime.model else "high"

    def build_user_prompt(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime,
    ) -> str:
        del context, runtime
        event_context = _format_event_context(group)
        return (
            "Prepare a superforecaster-style research memo (≈900-1300 words) for the prediction markets below. "
            "Follow the workflow from Tetlock & Gardner's *Superforecasting*: walk step-by-step through "
            "clarification, decomposition, base rates, inside-view adjustments, scenario modelling, synthesis, and "
            "update planning.\n"
            "\nStructure the memo with the following titled sections (use markdown headings):\n"
            "1. Forecast Framing & Resolution – restate the question with explicit resolution criteria and timeframe.\n"
            "2. Problem Decomposition – map critical sub-questions, actors, and necessary conditions.\n"
            "3. Outside-View Base Rates – identify the reference class, provide base-rate data, and cite sources.\n"
            "4. Inside-View Adjustments – evaluate current indicators for each sub-question, noting pushes up/down from the base rate.\n"
            "5. Scenario & Probability Analysis – outline plausible scenarios, assign conditional probabilities, and surface disconfirming evidence.\n"
            "6. Synthesis & Current Forecast – combine insights into a single probability estimate (expressed as a percentage) with justification and calibration checks.\n"
            "7. Evidence, Uncertainty & Alternative Views – catalogue key sources, data quality, assumptions, and gaps.\n"
            "8. Monitoring & Update Plan – specify indicators to watch, potential triggers for revisions, and follow-up research needs.\n"
            "\nGuidelines:\n"
            "- Lean on the model's deep research tools to fetch relevant historical, policy, and statistical context.\n"
            "- Reference all external facts inline as [source: outlet, date]; skip opaque footnotes.\n"
            "- Keep the tone analytical and calibrated; avoid confident language unless evidence warrants it.\n"
            "- Provide at least one explicit disconfirming argument or scenario.\n"
            "- Do not emit JSON or bullet-only answers; write richly reasoned paragraphs under each heading.\n"
            "\nEvent and market context:\n"
            f"{event_context}\n"
        )

    def extra_request_options(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime,
    ) -> Mapping[str, object] | None:
        del group, context
        effort = self._resolve_reasoning_effort(runtime)
        options = {
            # Deep Research endpoints cap reasoning effort at "medium"; standard
            # GPT models still benefit from the "high" setting when available.
            "reasoning": {"effort": effort},
        }
        if "deep-research" not in runtime.model:
            # Standard GPT models accept temperature but Deep Research endpoints reject it.
            options["temperature"] = 0.35
        return options

    def postprocess_text_output(
        self,
        content: str,
        *,
        group: EventMarketGroup,
        context: PipelineContext,
        runtime,
        response,
    ) -> dict[str, object]:
        cleaned = content.strip()
        payload = super().postprocess_text_output(
            cleaned,
            group=group,
            context=context,
            runtime=runtime,
            response=response,
        )
        payload["model"] = runtime.model
        payload["reasoning_effort"] = self._resolve_reasoning_effort(runtime)
        return payload


__all__ = ["OpenAIDeepResearchNarrative"]
