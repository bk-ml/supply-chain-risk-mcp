"""Tests the orchestrator's control flow in isolation — right agents called
in right order, both short-circuits taken correctly — using stub agents that
return hardcoded schema instances. No real LLM calls, no real MCP server
spawned for the short-circuit tests (they never reach the MCP client at all,
which is itself something worth asserting).
"""

import pytest
from unittest.mock import AsyncMock

from orchestration.orchestrator import Orchestrator
from orchestration.schemas import (
    PRDiffInput,
    TriageResult,
    TriageIntent,
    PackageRef,
    ResearchResult,
    SynthesisOutput,
    SynthesisRiskLevel,
)


def _diff(**overrides) -> PRDiffInput:
    defaults = dict(
        repo_owner="o", repo_name="r", diff_text="...", changed_files=["package.json"]
    )
    defaults.update(overrides)
    return PRDiffInput(**defaults)


class StubTriageAgent:
    def __init__(self, result: TriageResult):
        self._result = result
        self.called_with = None

    async def run(self, pr_diff: PRDiffInput) -> TriageResult:
        self.called_with = pr_diff
        return self._result


@pytest.mark.asyncio
async def test_no_relevant_changes_short_circuits_before_research_and_synthesis():
    triage = StubTriageAgent(TriageResult(
        intent=TriageIntent.NO_RELEVANT_CHANGES, confidence=0.99, reasoning="unrelated file"
    ))
    research = AsyncMock()
    synthesis = AsyncMock()

    orchestrator = Orchestrator(triage, research, synthesis)
    output, triage_result = await orchestrator.run(_diff())

    assert output.risk_level == SynthesisRiskLevel.NOT_APPLICABLE
    assert triage_result.intent == TriageIntent.NO_RELEVANT_CHANGES
    research.run.assert_not_called()
    synthesis.run.assert_not_called()


@pytest.mark.asyncio
async def test_low_confidence_short_circuits_to_unable_to_assess():
    triage = StubTriageAgent(TriageResult(
        intent=TriageIntent.NEW_DEPENDENCY,
        confidence=0.2,  # below default threshold of 0.5
        reasoning="ambiguous diff",
        affected_packages=[PackageRef(name="left-pad", ecosystem="npm", new_version="1.0.0")],
    ))
    research = AsyncMock()
    synthesis = AsyncMock()

    orchestrator = Orchestrator(triage, research, synthesis)
    output, triage_result = await orchestrator.run(_diff())

    assert output.risk_level == SynthesisRiskLevel.UNABLE_TO_ASSESS
    assert output.unable_to_assess is True
    assert "left-pad" in output.affected_packages
    assert triage_result.confidence == 0.2
    research.run.assert_not_called()
    synthesis.run.assert_not_called()


@pytest.mark.asyncio
async def test_confident_relevant_change_calls_research_and_synthesis_in_order(mocker):
    triage_result = TriageResult(
        intent=TriageIntent.NEW_DEPENDENCY,
        confidence=0.9,
        reasoning="added left-pad",
        affected_packages=[PackageRef(name="left-pad", ecosystem="npm", new_version="1.0.0")],
    )
    triage = StubTriageAgent(triage_result)

    research_result = ResearchResult(package_results=[])
    research = AsyncMock()
    research.run.return_value = research_result

    synthesis_output = SynthesisOutput(
        risk_level=SynthesisRiskLevel.LOW, recommendation="looks fine"
    )
    synthesis = AsyncMock()
    synthesis.run.return_value = synthesis_output

    # Avoid actually spawning the real MCP server for this control-flow test —
    # patch MCPToolClient's context manager to a no-op stand-in.
    fake_mcp_client = mocker.MagicMock()
    fake_mcp_client_cm = mocker.MagicMock()
    fake_mcp_client_cm.__aenter__ = AsyncMock(return_value=fake_mcp_client)
    fake_mcp_client_cm.__aexit__ = AsyncMock(return_value=False)
    mocker.patch("orchestration.orchestrator.MCPToolClient", return_value=fake_mcp_client_cm)

    orchestrator = Orchestrator(triage, research, synthesis)
    output, returned_triage_result = await orchestrator.run(_diff())

    assert output.risk_level == SynthesisRiskLevel.LOW
    assert returned_triage_result is triage_result
    research.run.assert_called_once()
    synthesis.run.assert_called_once_with(triage_result, research_result)