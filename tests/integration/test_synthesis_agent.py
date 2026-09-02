"""Integration tests for SynthesisAgent — real Gemini calls for the
recommendation prose. Covers real findings from manual exploration:
1. risk_level correctly derived from RiskBand.value, not str(enum) (this
   regression-tests a real bug: str(RiskBand.HIGH) == "RiskBand.HIGH", not
   "HIGH" — SynthesisRiskLevel(str(band)) crashed until fixed to use .value).
2. The maintenance-health caveat is actually present in the recommendation
   when maintenance health is the primary driver — confirmed against real
   LLM output, not assumed from the prompt text alone.
3. unable_to_assess fires correctly, with a non-empty reason, when there is
   nothing to synthesize (e.g. every package's research failed).

Run with:
    pytest tests/integration/test_synthesis_agent.py -v -m integration
"""

import os

import pytest
from dotenv import load_dotenv

from orchestration.llm_backend import GeminiBackend
from orchestration.synthesis_agent import SynthesisAgent
from orchestration.schemas import (
    PackageRef,
    PackageRiskData,
    ResearchResult,
    SynthesisRiskLevel,
    ToolCallError,
    ToolCallErrorType,
    TriageIntent,
    TriageResult,
)
from logic.scoring import RiskBand, RiskScoreResult

load_dotenv()

pytestmark = pytest.mark.integration


@pytest.fixture
def agent():
    backend = GeminiBackend(api_key=os.environ["GEMINI_API_KEY"])
    return SynthesisAgent(backend)


def _triage_result(packages):
    return TriageResult(
        intent=TriageIntent.VERSION_BUMP, confidence=1.0, reasoning="test",
        affected_packages=packages,
    )


@pytest.mark.asyncio
async def test_risk_level_correctly_derived_from_band_value_not_str(agent):
    # Regression test for the RiskBand.HIGH -> "RiskBand.HIGH" vs "HIGH" bug.
    pkg_ref = PackageRef(name="left-pad", ecosystem="npm", new_version="1.0.0")
    pkg_data = PackageRiskData(
        package_ref=pkg_ref,
        risk_score=RiskScoreResult(
            composite_score=80.0, band=RiskBand.HIGH,
            vuln_score=90.0, maintenance_score=10.0, license_score=0.0,
            primary_driver="driven primarily by an unpatched vulnerability",
        ),
    )
    research_result = ResearchResult(package_results=[pkg_data])

    output = await agent.run(_triage_result([pkg_ref]), research_result)

    assert output.risk_level == SynthesisRiskLevel.HIGH  # would raise before the fix


@pytest.mark.asyncio
async def test_maintenance_health_caveat_present_when_it_is_the_driver(agent):
    pkg_ref = PackageRef(name="some-pkg", ecosystem="npm", new_version="1.0.0")
    pkg_data = PackageRiskData(
        package_ref=pkg_ref,
        risk_score=RiskScoreResult(
            composite_score=5.0, band=RiskBand.LOW,
            vuln_score=0.0, maintenance_score=8.0, license_score=0.0,
            primary_driver="driven primarily by poor maintenance health",
        ),
    )
    research_result = ResearchResult(package_results=[pkg_data])

    output = await agent.run(_triage_result([pkg_ref]), research_result)

    # If the LLM call itself failed (e.g. quota exhaustion), SynthesisAgent
    # falls back to its deterministic templated recommendation by design
    # (see Step 2.3) — that fallback never contains the LLM-authored caveat
    # phrasing, since it isn't LLM-generated. Skip rather than fail in that
    # case: this test is meant to validate LLM prompt-following behavior,
    # not to re-detect quota exhaustion (run_evals.py's quota detection
    # already covers that separately).
    if output.recommendation.startswith("Overall risk:"):
        pytest.skip(
            "Synthesis fell back to templated recommendation (LLM call "
            "failed, likely quota exhaustion) — cannot validate caveat "
            "phrasing without a real LLM response. Re-run once quota resets."
        )

    # Confirms the model actually states the caveat, not just that the
    # prompt asked it to — this is real LLM output, not the prompt text.
    recommendation_lower = output.recommendation.lower()
    assert "maintenance" in recommendation_lower
    assert any(
        phrase in recommendation_lower
        for phrase in ["pr's own repo", "this pr", "not the", "consuming project", "upstream"]
    )


@pytest.mark.asyncio
async def test_unable_to_assess_when_all_packages_failed(agent):
    pkg_ref = PackageRef(name="broken-pkg", ecosystem="npm", new_version="1.0.0")
    pkg_data = PackageRiskData(
        package_ref=pkg_ref,
        risk_score=None,
        tool_errors=[ToolCallError(
            tool_name="get_risk_score", error_type=ToolCallErrorType.DOMAIN,
            message="repo not found",
        )],
    )
    research_result = ResearchResult(package_results=[pkg_data])

    output = await agent.run(_triage_result([pkg_ref]), research_result)

    assert output.risk_level == SynthesisRiskLevel.UNABLE_TO_ASSESS
    assert output.unable_to_assess is True
    assert output.unable_to_assess_reason  # non-empty, per the blank-reason fix
    assert "broken-pkg" in output.unable_to_assess_reason


@pytest.mark.asyncio
async def test_unable_to_assess_message_is_accurate_when_no_packages_identified(agent):
    # Regression test: previously this branch said "upstream triage may
    # have failed" even though an empty package_results list can ONLY mean
    # Triage correctly found zero packages (e.g. a license_change with no
    # associated dependency) — ResearchResult.package_results is built 1:1
    # from TriageResult.affected_packages, so this was never actually a
    # Triage failure signal.
    triage_result = TriageResult(
        intent=TriageIntent.LICENSE_CHANGE, confidence=1.0, reasoning="test",
        affected_packages=[],
    )
    research_result = ResearchResult(package_results=[])

    output = await agent.run(triage_result, research_result)

    assert output.risk_level == SynthesisRiskLevel.UNABLE_TO_ASSESS
    assert output.unable_to_assess is True
    reason_lower = output.unable_to_assess_reason.lower()
    assert "failed" not in reason_lower  # the old, misleading wording
    assert "license_change" in reason_lower