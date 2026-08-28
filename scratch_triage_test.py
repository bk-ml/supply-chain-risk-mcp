import asyncio
import os

from dotenv import load_dotenv
load_dotenv()

from orchestration.llm_backend import GeminiBackend
from orchestration.triage_agent import TriageAgent
from orchestration.schemas import PRDiffInput, TriageIntent

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

# Ambiguous case: lockfile churned (hash/resolved-url noise) but the actual
# manifest version constraint didn't change — is this a real version bump,
# or just lockfile noise? A good triage should either flag low confidence
# or correctly conclude no_relevant_changes; a bad one will confidently
# invent a version bump that didn't really happen.
AMBIGUOUS_LOCKFILE_DIFF = """diff --git a/package-lock.json b/package-lock.json
index aaaaaaa..bbbbbbb 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1200,8 +1200,8 @@
     "node_modules/lodash": {
       "version": "4.17.21",
-      "resolved": "https://registry.npmjs.org/lodash/-/lodash-4.17.21.tgz",
-      "integrity": "sha512-oldhashvalueoldhashvalueoldhashvalue=="
+      "resolved": "https://registry.npmjs.org/lodash/-/lodash-4.17.21.tgz",
+      "integrity": "sha512-newhashvaluenewhashvaluenewhashvalue=="
     }
"""


# Deliberately garbled/truncated case, meant to try to force genuine
# hedging — a mid-hunk cutoff with an unparseable version string, no clear
# before/after. If the model is well-calibrated it should either lower
# confidence or explicitly say it's guessing; if it always returns 1.0
# regardless of input quality, that's a real calibration gap worth knowing
# about before relying on the confidence threshold as a guardrail.
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

CASES = [
    ("version_bump (clean)", VERSION_BUMP_DIFF, ["package.json"], TriageIntent.VERSION_BUMP),
    ("no_relevant_changes", NO_RELEVANT_CHANGES_DIFF, ["src/utils.js"], TriageIntent.NO_RELEVANT_CHANGES),
    ("new_dependency", NEW_DEPENDENCY_DIFF, ["requirements.txt"], TriageIntent.NEW_DEPENDENCY),
    ("ambiguous lockfile-only churn", AMBIGUOUS_LOCKFILE_DIFF, ["package-lock.json"], None),
    ("garbled/truncated diff", GARBLED_DIFF, ["package.json"], None),
]


async def main():
    backend = GeminiBackend(api_key=os.environ["GEMINI_API_KEY"])
    agent = TriageAgent(backend)

    for label, diff_text, changed_files, expected_intent in CASES:
        pr_diff = PRDiffInput(
            repo_owner="test-org",
            repo_name="test-repo",
            diff_text=diff_text,
            changed_files=changed_files,
        )
        result = await agent.run(pr_diff)
        print(f"\n=== {label} ===")
        print(result.model_dump_json(indent=2))
        if expected_intent is not None:
            status = "OK" if result.intent == expected_intent else "MISMATCH"
            print(f"[{status}] expected intent={expected_intent}, got={result.intent}")


asyncio.run(main())