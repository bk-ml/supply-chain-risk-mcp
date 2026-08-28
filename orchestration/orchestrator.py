"""
Orchestrator: sequences Triage -> Research -> Synthesis. Hand-written state
machine, no framework — agents are injected via constructor so this file
never hardcodes which LLM backend or agent implementation is in use, and so
this control flow can be tested with stub agents before real agent logic
exists (Step 1.4) or with real agents later (Phase 2).

Two short-circuit paths, both terminate before Research/Synthesis run:
1. Triage classifies NO_RELEVANT_CHANGES -> SynthesisRiskLevel.NOT_APPLICABLE
2. Triage confidence below CONFIDENCE_THRESHOLD -> SynthesisRiskLevel.UNABLE_TO_ASSESS

The confidence threshold check lives here, not inside Triage Agent, so it's
a single visible, tunable constant rather than buried in agent logic —
Triage Agent's only job is classification, not deciding what counts as
confident enough.
"""

from __future__ import annotations

import logging
from typing import Protocol

from orchestration.mcp_client import MCPToolClient
from orchestration.schemas import (
    PRDiffInput,
    TriageResult,
    TriageIntent,
    ResearchResult,
    SynthesisOutput,
    SynthesisRiskLevel,
)

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.5


class TriageAgentProtocol(Protocol):
    async def run(self, pr_diff: PRDiffInput) -> TriageResult: ...


class ResearchAgentProtocol(Protocol):
    async def run(self, triage_result: TriageResult, pr_diff: PRDiffInput, mcp_client: MCPToolClient) -> ResearchResult: ...


class SynthesisAgentProtocol(Protocol):
    async def run(self, triage_result: TriageResult, research_result: ResearchResult) -> SynthesisOutput: ...


class Orchestrator:
    def __init__(
        self,
        triage_agent: TriageAgentProtocol,
        research_agent: ResearchAgentProtocol,
        synthesis_agent: SynthesisAgentProtocol,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
    ):
        self._triage_agent = triage_agent
        self._research_agent = research_agent
        self._synthesis_agent = synthesis_agent
        self._confidence_threshold = confidence_threshold

    async def run(self, pr_diff: PRDiffInput) -> SynthesisOutput:
        triage_result = await self._triage_agent.run(pr_diff)
        logger.info(
            "Triage: intent=%s confidence=%.2f packages=%d",
            triage_result.intent, triage_result.confidence, len(triage_result.affected_packages),
        )

        # Short-circuit 1: nothing relevant to assess.
        if triage_result.intent == TriageIntent.NO_RELEVANT_CHANGES:
            return SynthesisOutput(
                risk_level=SynthesisRiskLevel.NOT_APPLICABLE,
                affected_packages=[],
                recommendation="No dependency-relevant changes detected in this PR.",
            )

        # Short-circuit 2: low-confidence refusal path.
        if triage_result.confidence < self._confidence_threshold:
            return SynthesisOutput(
                risk_level=SynthesisRiskLevel.UNABLE_TO_ASSESS,
                affected_packages=[p.name for p in triage_result.affected_packages],
                recommendation="Unable to confidently classify this change.",
                unable_to_assess=True,
                unable_to_assess_reason=(
                    f"Triage confidence {triage_result.confidence:.2f} below "
                    f"threshold {self._confidence_threshold:.2f}"
                ),
            )

        async with MCPToolClient() as mcp_client:
            research_result = await self._research_agent.run(triage_result, pr_diff, mcp_client)

        logger.info("Research: %d package results", len(research_result.package_results))

        synthesis_output = await self._synthesis_agent.run(triage_result, research_result)
        logger.info("Synthesis: risk_level=%s", synthesis_output.risk_level)

        return synthesis_output