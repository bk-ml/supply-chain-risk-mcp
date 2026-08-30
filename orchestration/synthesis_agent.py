"""
Synthesis Agent: takes TriageResult + ResearchResult and produces the final
SynthesisOutput.

Design decision — deterministic risk_level, LLM-only prose:
risk_level is computed in CODE from RiskScoreResult.band (Option A's own
scoring output), taking the worst band across all successfully-assessed
packages. The LLM is only ever asked to write the human-readable
`recommendation` text — never asked to also produce the risk_level enum.
This removes an entire class of potential schema violations (the LLM getting
an enum value wrong) and keeps the number that actually drives eval scoring
fully deterministic and traceable to Option A's documented scoring
methodology, rather than subject to LLM unpredictability.

unable_to_assess triggers (in order):
1. ALL packages have no risk_score (every one hit a tool_errors failure) ->
   deterministic UNABLE_TO_ASSESS, no LLM call — there is nothing to
   synthesize prose about.
2. Otherwise, at least one package succeeded -> risk_level computed from
   successful packages only; the recommendation prose explicitly names any
   packages that couldn't be assessed and why (using tool_errors messages),
   so partial data is surfaced, not silently dropped.

Note (see ResearchAgent docstring): the recommendation prompt below
explicitly tells the LLM that maintenance-health reflects the CONSUMING
project, not the dependency's own upstream repo, so this known limitation
is stated plainly in output rather than presented as if it were dependency
health.
"""

from __future__ import annotations

import logging

from orchestration.llm_backend import LLMBackend, LLMBackendError
from orchestration.schemas import (
    PackageRiskData,
    ResearchResult,
    SynthesisOutput,
    SynthesisRiskLevel,
    TriageResult,
)

logger = logging.getLogger(__name__)

# Worst-to-best ordering, matches Option A's RiskBand semantics.
_BAND_SEVERITY = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

SYSTEM_PROMPT = """You are writing a short, clear PR review comment about
dependency risk, for a developer to read directly in their pull request.

You will be given: the overall risk level (already determined — do not
second-guess or restate a different level), per-package risk data, and any
packages that could not be assessed due to tool failures.

Write a concise recommendation (2-4 sentences) that:
- States the overall risk level and what's driving it (cite the specific
  vulnerability, license conflict, or maintenance concern by name if one
  clearly dominates)
- Explicitly names any packages that could not be assessed and briefly why,
  if any are listed
- IMPORTANT: if maintenance-health data is mentioned, note plainly that it
  reflects the health of the PR's own repository, not the health of the
  dependency's own upstream project — do not imply it's about the
  dependency's maintenance status
- Gives a one-line actionable suggestion (e.g. "consider pinning to a patched
  version" or "review the license conflict before merging")

Respond with ONLY the recommendation text. No JSON, no markdown, no preamble.
"""


class SynthesisAgent:
    def __init__(self, llm_backend: LLMBackend):
        self._llm_backend = llm_backend

    async def run(self, triage_result: TriageResult, research_result: ResearchResult) -> SynthesisOutput:
        assessed = [p for p in research_result.package_results if p.risk_score is not None]
        unassessed = [p for p in research_result.package_results if p.risk_score is None]

        if not assessed:
            reason = (
                self._summarize_failures(research_result.package_results)
                if research_result.package_results
                else "No packages were available to research (upstream triage may have failed)."
            )
            return SynthesisOutput(
                risk_level=SynthesisRiskLevel.UNABLE_TO_ASSESS,
                affected_packages=[p.package_ref.name for p in research_result.package_results],
                recommendation="Unable to assess risk: all package checks failed.",
                unable_to_assess=True,
                unable_to_assess_reason=reason,
            )

        risk_level = self._compute_risk_level(assessed)
        all_package_names = [p.package_ref.name for p in research_result.package_results]

        try:
            recommendation = await self._generate_recommendation(risk_level, assessed, unassessed)
        except LLMBackendError as e:
            logger.warning("Synthesis LLM call failed, falling back to templated recommendation: %s", e)
            recommendation = self._fallback_recommendation(risk_level, assessed, unassessed)

        return SynthesisOutput(
            risk_level=risk_level,
            affected_packages=all_package_names,
            recommendation=recommendation,
        )

    @staticmethod
    def _compute_risk_level(assessed: list[PackageRiskData]) -> SynthesisRiskLevel:
        worst_band = max(
            (p.risk_score.band for p in assessed),
            key=lambda band: _BAND_SEVERITY.get(band.value, 0),
        )
        return SynthesisRiskLevel(worst_band.value)

    @staticmethod
    def _summarize_failures(packages: list[PackageRiskData]) -> str:
        parts = []
        for p in packages:
            msgs = "; ".join(e.message for e in p.tool_errors) or "unknown error"
            parts.append(f"{p.package_ref.name}: {msgs}")
        return " | ".join(parts)

    async def _generate_recommendation(
        self,
        risk_level: SynthesisRiskLevel,
        assessed: list[PackageRiskData],
        unassessed: list[PackageRiskData],
    ) -> str:
        lines = [f"Overall risk level: {risk_level.value}", ""]
        for p in assessed:
            lines.append(
                f"- {p.package_ref.name}: band={p.risk_score.band}, "
                f"composite_score={p.risk_score.composite_score}, "
                f"primary_driver={p.risk_score.primary_driver}"
            )
        if unassessed:
            lines.append("\nPackages that could not be assessed:")
            for p in unassessed:
                msgs = "; ".join(e.message for e in p.tool_errors) or "unknown error"
                lines.append(f"- {p.package_ref.name}: {msgs}")

        user_prompt = "\n".join(lines)
        return await self._llm_backend.complete(SYSTEM_PROMPT, user_prompt)

    @staticmethod
    def _fallback_recommendation(
        risk_level: SynthesisRiskLevel,
        assessed: list[PackageRiskData],
        unassessed: list[PackageRiskData],
    ) -> str:
        """Used only if the LLM call itself fails (not if it produces bad
        output — that's a separate concern). Deterministic, ensures
        Synthesis never returns with no recommendation at all."""
        drivers = ", ".join(f"{p.package_ref.name} ({p.risk_score.primary_driver})" for p in assessed)
        text = f"Overall risk: {risk_level.value}. Drivers: {drivers}."
        if unassessed:
            names = ", ".join(p.package_ref.name for p in unassessed)
            text += f" Could not assess: {names}."
        return text