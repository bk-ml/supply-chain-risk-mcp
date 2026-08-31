"""End-to-end integration test: real Orchestrator, real Triage/Research/
Synthesis agents, real MCP server spawn, real Gemini calls. This is the only
test that exercises the full seam between Orchestrator.run()'s own
`async with MCPToolClient()` and real (non-stub) agents together — the
orchestrator unit tests (tests/unit/test_orchestrator.py) only ever used
AsyncMock stubs and a mocked MCPToolClient.

Run with:
    pytest tests/integration/test_orchestrator_e2e.py -v -m integration
"""

import os

import pytest
from dotenv import load_dotenv

from orchestration.llm_backend import GeminiBackend
from orchestration.triage_agent import TriageAgent
from orchestration.research_agent import ResearchAgent
from orchestration.synthesis_agent import SynthesisAgent
from orchestration.orchestrator import Orchestrator
from orchestration.schemas import PRDiffInput, SynthesisRiskLevel

load_dotenv()

pytestmark = pytest.mark.integration


@pytest.fixture
def orchestrator():
    backend = GeminiBackend(api_key=os.environ["GEMINI_API_KEY"])
    return Orchestrator(
        triage_agent=TriageAgent(backend),
        research_agent=ResearchAgent(),
        synthesis_agent=SynthesisAgent(backend),
    )


VERSION_BUMP_DIFF = """diff --git a/package.json b/package.json
index 1234567..89abcde 100644
--- a/package.json
+++ b/package.json
@@ -10,7 +10,7 @@
   "dependencies": {
     "express": "^4.18.2",
-    "lodash": "^4.17.20",
+    "lodash": "^4.17.21",
   }
"""

NO_RELEVANT_CHANGES_DIFF = """diff --git a/src/utils.js b/src/utils.js
index abc1234..def5678 100644
--- a/src/utils.js
+++ b/src/utils.js
@@ -12,7 +12,7 @@ function formatDate(date) {
-  return date.toISOString().split('T')[0];
+  return date.toISOString().slice(0, 10);
 }
"""


@pytest.mark.asyncio
async def test_full_chain_end_to_end_via_real_orchestrator(orchestrator):
    pr_diff = PRDiffInput(
        repo_owner="lodash", repo_name="lodash",
        diff_text=VERSION_BUMP_DIFF, changed_files=["package.json"], project_license="MIT",
    )

    output, triage_result = await orchestrator.run(pr_diff)

    assert output.risk_level == SynthesisRiskLevel.HIGH
    assert "lodash" in output.affected_packages
    assert output.unable_to_assess is False
    assert len(output.recommendation) > 0
    assert triage_result.intent.value == "version_bump"


@pytest.mark.asyncio
async def test_no_relevant_changes_short_circuits_with_real_agents(orchestrator, mocker):
    # Spy on the MCP client constructor to confirm it's genuinely never
    # spawned for this path, even with real (non-stub) agents wired in.
    mcp_spy = mocker.spy(
        __import__("orchestration.orchestrator", fromlist=["MCPToolClient"]),
        "MCPToolClient",
    )

    pr_diff = PRDiffInput(
        repo_owner="o", repo_name="r",
        diff_text=NO_RELEVANT_CHANGES_DIFF, changed_files=["src/utils.js"], project_license="MIT",
    )

    output, triage_result = await orchestrator.run(pr_diff)

    assert output.risk_level == SynthesisRiskLevel.NOT_APPLICABLE
    mcp_spy.assert_not_called()