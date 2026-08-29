"""Integration tests for ResearchAgent — real MCP server spawn, real APIs.
Covers the three real findings from manual exploration:
1. Happy path with a real package (lodash).
2. Version-range normalization: package.json gives ranges like "^4.17.21",
   but deps.dev needs an exact version. This bug was found by observing a
   real 404 and is now regression-tested.
3. Full call-level domain error (nonexistent repo) isolating cleanly per
   package — no crash, no fabricated data, tool_errors populated correctly.

Run with:
    pytest tests/integration/test_research_agent.py -v -m integration
"""

import pytest

from orchestration.mcp_client import MCPToolClient
from orchestration.research_agent import ResearchAgent, _normalize_version
from orchestration.schemas import PackageRef, PRDiffInput, TriageResult, TriageIntent

pytestmark = pytest.mark.integration


def test_normalize_version_strips_range_operators():
    assert _normalize_version("^4.17.21") == "4.17.21"
    assert _normalize_version("~1.2.3") == "1.2.3"
    assert _normalize_version(">=2.0.0") == "2.0.0"
    assert _normalize_version("4.17.21") == "4.17.21"  # already exact, unchanged


@pytest.mark.asyncio
async def test_happy_path_known_good_package():
    triage_result = TriageResult(
        intent=TriageIntent.VERSION_BUMP,
        confidence=1.0,
        reasoning="test",
        affected_packages=[
            PackageRef(name="lodash", ecosystem="npm", old_version="^4.17.20", new_version="^4.17.21")
        ],
    )
    pr_diff = PRDiffInput(
        repo_owner="lodash", repo_name="lodash",
        diff_text="...", changed_files=["package.json"], project_license="MIT",
    )
    agent = ResearchAgent()

    async with MCPToolClient() as mcp_client:
        result = await agent.run(triage_result, pr_diff, mcp_client)

    assert len(result.package_results) == 1
    pkg_result = result.package_results[0]
    assert pkg_result.tool_errors == []
    assert pkg_result.risk_score is not None
    assert pkg_result.vulnerabilities is not None
    # Regression check: version actually sent was normalized, not the raw range.
    assert pkg_result.vulnerabilities.version == "4.17.21"


@pytest.mark.asyncio
async def test_domain_error_isolated_per_package_no_crash_no_fabrication():
    triage_result = TriageResult(
        intent=TriageIntent.VERSION_BUMP,
        confidence=1.0,
        reasoning="test",
        affected_packages=[
            PackageRef(name="lodash", ecosystem="npm", new_version="^4.17.21"),
            PackageRef(name="totally-fake-package-xyz-123", ecosystem="npm", new_version="^2.0.0"),
        ],
    )
    # Nonexistent repo forces a full get_risk_score domain failure
    # (not_found) for every package sharing this owner/repo.
    pr_diff = PRDiffInput(
        repo_owner="nobody", repo_name="doesnt-exist-xyz-123",
        diff_text="...", changed_files=["package.json"], project_license="MIT",
    )
    agent = ResearchAgent()

    async with MCPToolClient() as mcp_client:
        result = await agent.run(triage_result, pr_diff, mcp_client)

    assert len(result.package_results) == 2
    for pkg_result in result.package_results:
        assert pkg_result.risk_score is None
        assert pkg_result.vulnerabilities is None
        assert len(pkg_result.tool_errors) == 1
        assert pkg_result.tool_errors[0].error_type == "domain"
        assert "not found" in pkg_result.tool_errors[0].message.lower()