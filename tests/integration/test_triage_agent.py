"""Integration tests for TriageAgent — real Gemini calls, no mocking of the
LLM. These are the committed version of the manual exploration that
validated: correct classification across intents, the deterministic
no-LLM-call short-circuit for non-manifest diffs, and genuine confidence
calibration on a deliberately garbled diff (this is what actually confirms
the low-confidence refusal guardrail can fire from real model output, not
just from hand-constructed TriageResult instances in orchestrator tests).

Run with:
    pytest tests/test_triage_agent_integration.py -v -m integration
"""

import os

import pytest
from dotenv import load_dotenv

from orchestration.llm_backend import GeminiBackend
from orchestration.triage_agent import TriageAgent
from orchestration.schemas import PRDiffInput, TriageIntent

load_dotenv()

pytestmark = pytest.mark.integration


@pytest.fixture
def agent():
    backend = GeminiBackend(api_key=os.environ["GEMINI_API_KEY"])
    return TriageAgent(backend)


VERSION_BUMP_DIFF = """diff --git a/package.json b/package.json
index 1234567..89abcde 100644
--- a/package.json
+++ b/package.json
@@ -10,7 +10,7 @@
   "dependencies": {
     "express": "^4.17.1",
-    "lodash": "^4.17.20",
+    "lodash": "^4.17.21",
     "axios": "^0.21.1"
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

NEW_DEPENDENCY_DIFF = """diff --git a/requirements.txt b/requirements.txt
index 1111111..2222222 100644
--- a/requirements.txt
+++ b/requirements.txt
@@ -3,3 +3,4 @@ flask==2.3.2
 requests==2.31.0
 sqlalchemy==2.0.19
+pyjwt==2.8.0
"""

GARBLED_DIFF = """diff --git a/package.json b/package.json
index 1234567..89abcde 100644
--- a/package.json
+++ b/pack
@@ -8,11 +8,7 @@
   "dependencies": {
-    "some-pkg": "^
+    "some-pkg": "workspace:*"
     <<<<<<< HEAD
-    "other-thing": "1.2
+    "other-thing":
     =======
"""


@pytest.mark.asyncio
async def test_clean_version_bump(agent):
    pr_diff = PRDiffInput(
        repo_owner="o", repo_name="r", diff_text=VERSION_BUMP_DIFF, changed_files=["package.json"]
    )
    result = await agent.run(pr_diff)

    assert result.intent == TriageIntent.VERSION_BUMP
    assert len(result.affected_packages) == 1
    assert result.affected_packages[0].name == "lodash"
    assert result.affected_packages[0].ecosystem == "npm"
    assert result.confidence > 0.5


@pytest.mark.asyncio
async def test_no_manifest_files_short_circuits_without_llm_call(agent, mocker):
    # Spy on the backend to confirm the LLM is never actually called —
    # this is a deterministic code path, not an LLM judgment call.
    complete_spy = mocker.spy(agent._llm_backend, "complete")

    pr_diff = PRDiffInput(
        repo_owner="o", repo_name="r", diff_text=NO_RELEVANT_CHANGES_DIFF, changed_files=["src/utils.js"]
    )
    result = await agent.run(pr_diff)

    assert result.intent == TriageIntent.NO_RELEVANT_CHANGES
    assert result.confidence == 1.0
    complete_spy.assert_not_called()


@pytest.mark.asyncio
async def test_new_dependency_extraction(agent):
    pr_diff = PRDiffInput(
        repo_owner="o", repo_name="r", diff_text=NEW_DEPENDENCY_DIFF, changed_files=["requirements.txt"]
    )
    result = await agent.run(pr_diff)

    assert result.intent == TriageIntent.NEW_DEPENDENCY
    assert len(result.affected_packages) == 1
    pkg = result.affected_packages[0]
    assert pkg.name == "pyjwt"
    assert pkg.ecosystem == "pypi"
    assert pkg.old_version is None
    assert pkg.new_version == "2.8.0"


@pytest.mark.asyncio
async def test_garbled_diff_produces_genuinely_low_confidence(agent):
    # This is the test that actually validates the low-confidence refusal
    # guardrail can fire from real model output — not just from a
    # hand-constructed TriageResult in orchestrator unit tests.
    pr_diff = PRDiffInput(
        repo_owner="o", repo_name="r", diff_text=GARBLED_DIFF, changed_files=["package.json"]
    )
    result = await agent.run(pr_diff)

    # Threshold chosen deliberately below the orchestrator's 0.5 gate, so a
    # pass here means the guardrail would actually trigger end-to-end.
    assert result.confidence < 0.5