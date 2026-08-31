"""
Eval test cases for the multi-agent PR dependency risk reviewer.

Design principles:
- Expected outcomes are STRUCTURAL/CATEGORICAL (e.g. risk_level in a set,
  unable_to_assess is True/False), not exact scores — real vulnerability
  databases and repo health change over time, so hardcoding e.g. "composite
  score must be exactly 39.8" would break as soon as a CVE gets patched or a
  new one is disclosed. Categorical assertions are what stays meaningful.
- Each guardrail (input rejection, schema enforcement, low-confidence
  refusal) has an explicit, labeled case — not just incidental coverage.
  Schema enforcement itself doesn't get a dedicated case: every case
  demonstrates it, since SynthesisOutput is always a validated pydantic
  model or the run fails loudly; this is noted once in the eval report
  rather than manufactured as a separate case.
- est_llm_calls is tracked per case so the eval report can honestly state
  total quota cost, and so cases can be run in quota-aware batches without
  guessing which ones are "free" (no manifest files -> Triage short-circuits
  with zero LLM calls) vs. costly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class EvalCase:
    id: str
    description: str
    guardrail: str | None  # None if this case isn't specifically testing a guardrail
    est_llm_calls: int

    # Inputs — None for cases that test PRDiffInput construction itself
    # failing (input-rejection case), where there's no valid diff to run.
    repo_owner: str | None = None
    repo_name: str | None = None
    diff_text: str | None = None
    changed_files: list[str] = field(default_factory=list)
    project_license: str = "MIT"
    invalid_pr_diff_kwargs: dict | None = None  # only set for the input-rejection case

    # Expected outcomes — categorical, checked by evals/run_evals.py
    expect_input_rejected: bool = False          # PRDiffInput construction itself should raise
    expect_no_llm_call: bool = False              # Triage should short-circuit before calling Gemini
    expect_short_circuit_before_research: bool = False  # orchestrator returns before Research/Synthesis run
    expect_unable_to_assess: bool | None = None   # None = don't check this field
    expect_risk_level_in: list[str] | None = None  # e.g. ["HIGH", "CRITICAL"]
    expect_intent_in: list[str] | None = None      # checked against TriageResult.intent if reachable
    expect_min_affected_packages: int | None = None


CASES: list[EvalCase] = [

    EvalCase(
        id="vuln_known_bad_package",
        description="Real package (lodash) with well-known unpatched vulnerabilities, version bump.",
        guardrail=None,
        est_llm_calls=2,
        repo_owner="lodash", repo_name="lodash",
        diff_text="""diff --git a/package.json b/package.json
index 1234567..89abcde 100644
--- a/package.json
+++ b/package.json
@@ -10,7 +10,7 @@
   "dependencies": {
     "express": "^4.18.2",
-    "lodash": "^4.17.20",
+    "lodash": "^4.17.21",
   }
""",
        changed_files=["package.json"],
        expect_intent_in=["version_bump"],
        expect_unable_to_assess=False,
        expect_risk_level_in=["MEDIUM", "HIGH", "CRITICAL"],
        expect_min_affected_packages=1,
    ),

    EvalCase(
        id="version_bump_well_maintained_package",
        description="Real, actively-maintained package (express) minor version bump — expect lower risk.",
        guardrail=None,
        est_llm_calls=2,
        repo_owner="expressjs", repo_name="express",
        diff_text="""diff --git a/package.json b/package.json
index 1234567..89abcde 100644
--- a/package.json
+++ b/package.json
@@ -10,7 +10,7 @@
   "dependencies": {
-    "express": "^4.18.1",
+    "express": "^4.18.2",
   }
""",
        changed_files=["package.json"],
        expect_intent_in=["version_bump"],
        expect_unable_to_assess=False,
        expect_min_affected_packages=1,
        # Deliberately no risk_level assertion here — express is generally
        # low-risk but this isn't guaranteed to stay true, and the point of
        # this case is "does it run cleanly on a healthy package", not
        # pinning an exact band.
    ),

    EvalCase(
        id="new_dependency_pypi",
        description="New PyPI dependency added.",
        guardrail=None,
        est_llm_calls=2,
        repo_owner="pallets", repo_name="flask",
        diff_text="""diff --git a/requirements.txt b/requirements.txt
index 1111111..2222222 100644
--- a/requirements.txt
+++ b/requirements.txt
@@ -3,3 +3,4 @@ flask==2.3.2
 requests==2.31.0
 sqlalchemy==2.0.19
+pyjwt==2.8.0
""",
        changed_files=["requirements.txt"],
        expect_intent_in=["new_dependency"],
        expect_min_affected_packages=1,
    ),

    EvalCase(
        id="new_dependency_cargo",
        description="New Cargo (Rust) dependency added.",
        guardrail=None,
        est_llm_calls=2,
        repo_owner="rust-lang", repo_name="cargo",
        diff_text="""diff --git a/Cargo.toml b/Cargo.toml
index 1111111..2222222 100644
--- a/Cargo.toml
+++ b/Cargo.toml
@@ -5,3 +5,4 @@
 [dependencies]
 serde = "1.0"
+rand = "0.8"
""",
        changed_files=["Cargo.toml"],
        expect_intent_in=["new_dependency"],
        expect_min_affected_packages=1,
    ),

    EvalCase(
        id="new_dependency_maven",
        description="New Maven (Java) dependency added.",
        guardrail=None,
        est_llm_calls=2,
        repo_owner="apache", repo_name="maven",
        diff_text="""diff --git a/pom.xml b/pom.xml
index 1111111..2222222 100644
--- a/pom.xml
+++ b/pom.xml
@@ -20,5 +20,9 @@
   <dependencies>
+    <dependency>
+      <groupId>com.google.guava</groupId>
+      <artifactId>guava</artifactId>
+      <version>32.1.2-jre</version>
+    </dependency>
   </dependencies>
""",
        changed_files=["pom.xml"],
        expect_intent_in=["new_dependency"],
        expect_min_affected_packages=1,
    ),

    EvalCase(
        id="license_file_change",
        description="LICENSE file itself changed (MIT to GPL text swap).",
        guardrail=None,
        est_llm_calls=2,
        repo_owner="some-org", repo_name="some-repo",
        diff_text="""diff --git a/LICENSE b/LICENSE
index 1111111..2222222 100644
--- a/LICENSE
+++ b/LICENSE
@@ -1,5 +1,5 @@
-MIT License
+GNU GENERAL PUBLIC LICENSE
+Version 3, 29 June 2007
""",
        changed_files=["LICENSE"],
        expect_intent_in=["license_change"],
    ),

    EvalCase(
        id="no_relevant_changes_code_only",
        description="Only application code changed, no manifest files — should short-circuit with zero LLM calls.",
        guardrail=None,
        est_llm_calls=0,
        repo_owner="some-org", repo_name="some-repo",
        diff_text="""diff --git a/src/utils.js b/src/utils.js
index abc1234..def5678 100644
--- a/src/utils.js
+++ b/src/utils.js
@@ -12,7 +12,7 @@ function formatDate(date) {
-  return date.toISOString().split('T')[0];
+  return date.toISOString().slice(0, 10);
 }
""",
        changed_files=["src/utils.js"],
        expect_no_llm_call=True,
        expect_short_circuit_before_research=True,
        expect_intent_in=["no_relevant_changes"],
    ),

    EvalCase(
        id="lockfile_hash_only_churn",
        description="Lockfile integrity hash changed with no real version change — tests Triage precision on ambiguous input.",
        guardrail=None,
        est_llm_calls=2,
        repo_owner="lodash", repo_name="lodash",
        diff_text="""diff --git a/package-lock.json b/package-lock.json
index aaaaaaa..bbbbbbb 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1200,8 +1200,8 @@
     "node_modules/lodash": {
       "version": "4.17.21",
-      "integrity": "sha512-oldhashvalueoldhashvalueoldhashvalue=="
+      "integrity": "sha512-newhashvaluenewhashvaluenewhashvalue=="
     }
""",
        changed_files=["package-lock.json"],
        # No fixed intent expectation — either no_relevant_changes or a
        # correctly-reasoned version_bump would be acceptable; what matters
        # is that it doesn't confidently invent a fake version change.
        expect_unable_to_assess=False,
    ),

    EvalCase(
        id="garbled_diff_low_confidence",
        description="Deliberately truncated/garbled diff with merge-conflict markers — tests the low-confidence refusal guardrail.",
        guardrail="low_confidence_refusal",
        est_llm_calls=1,  # Triage only; orchestrator short-circuits before Synthesis
        repo_owner="some-org", repo_name="some-repo",
        diff_text="""diff --git a/package.json b/package.json
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
""",
        changed_files=["package.json"],
        expect_unable_to_assess=True,
    ),

    EvalCase(
        id="nonexistent_github_repo",
        description="PR repo itself doesn't exist on GitHub — tests honest refusal on tool failure rather than fabrication.",
        guardrail="honest_refusal_on_tool_failure",
        est_llm_calls=2,
        repo_owner="nobody", repo_name="doesnt-exist-xyz-123",
        diff_text="""diff --git a/package.json b/package.json
index 1234567..89abcde 100644
--- a/package.json
+++ b/package.json
@@ -10,7 +10,7 @@
   "dependencies": {
-    "lodash": "^4.17.20",
+    "lodash": "^4.17.21",
   }
""",
        changed_files=["package.json"],
        expect_unable_to_assess=True,
    ),

    EvalCase(
        id="nonexistent_package_real_repo",
        description="Package doesn't exist on npm, but the PR's own repo is real — tests partial-result isolation, not total failure.",
        guardrail=None,
        est_llm_calls=2,
        repo_owner="lodash", repo_name="lodash",
        diff_text="""diff --git a/package.json b/package.json
index 1234567..89abcde 100644
--- a/package.json
+++ b/package.json
@@ -10,7 +10,7 @@
   "dependencies": {
-    "totally-fake-package-xyz-123": "^1.0.0",
+    "totally-fake-package-xyz-123": "^2.0.0",
   }
""",
        changed_files=["package.json"],
        # Should NOT be unable_to_assess — get_risk_score's internal license
        # fallback absorbs the deps.dev 404, still returns a score.
        expect_unable_to_assess=False,
    ),

    EvalCase(
        id="gpl_dependency_into_mit_project",
        description="Adding a copyleft-licensed dependency to an MIT project — tests license-conflict detection.",
        guardrail=None,
        est_llm_calls=2,
        repo_owner="lodash", repo_name="lodash",  # real, existing repo — the
        # actual project being checked doesn't need to BE an MIT project for
        # this test; we're checking whether adding a GPL-family package is
        # correctly flagged against a declared MIT project_license.
        diff_text="""diff --git a/package.json b/package.json
index 1111111..2222222 100644
--- a/package.json
+++ b/package.json
@@ -5,3 +5,4 @@
   "dependencies": {
+    "readline": "^1.3.0",
   }
""",
        changed_files=["package.json"],
        project_license="MIT",
        expect_intent_in=["new_dependency"],
        # Not asserting conflicts are found — license_rules.py's actual SPDX
        # logic is Option A's domain and already unit-tested there. This
        # case just confirms the multi-agent path surfaces whatever that
        # logic finds, without crashing. Also NOT asserting unable_to_assess
        # here, since a real repo is now used and the call should succeed.
        expect_unable_to_assess=False,
    ),

    EvalCase(
        id="multiple_packages_one_diff",
        description="Two packages changed in the same PR — tests parallel Research Agent calls.",
        guardrail=None,
        est_llm_calls=2,
        repo_owner="lodash", repo_name="lodash",
        diff_text="""diff --git a/package.json b/package.json
index 1234567..89abcde 100644
--- a/package.json
+++ b/package.json
@@ -10,8 +10,8 @@
   "dependencies": {
-    "lodash": "^4.17.20",
+    "lodash": "^4.17.21",
-    "axios": "^0.21.1",
+    "axios": "^1.6.0",
   }
""",
        changed_files=["package.json"],
        expect_min_affected_packages=2,
        expect_unable_to_assess=False,
    ),

    EvalCase(
        id="version_downgrade",
        description="Version DECREASED rather than increased — edge case for extraction and reasoning.",
        guardrail=None,
        est_llm_calls=2,
        repo_owner="some-org", repo_name="some-repo",
        diff_text="""diff --git a/package.json b/package.json
index 1234567..89abcde 100644
--- a/package.json
+++ b/package.json
@@ -10,7 +10,7 @@
   "dependencies": {
-    "lodash": "^4.17.21",
+    "lodash": "^4.17.15",
   }
""",
        changed_files=["package.json"],
        expect_intent_in=["version_bump"],
        expect_min_affected_packages=1,
    ),

    EvalCase(
        id="package_added_and_removed_same_diff",
        description="One package added, a different one removed, in the same diff.",
        guardrail=None,
        est_llm_calls=2,
        repo_owner="some-org", repo_name="some-repo",
        diff_text="""diff --git a/requirements.txt b/requirements.txt
index 1111111..2222222 100644
--- a/requirements.txt
+++ b/requirements.txt
@@ -1,4 +1,4 @@
 flask==2.3.2
-requests==2.31.0
+httpx==0.27.0
 sqlalchemy==2.0.19
""",
        changed_files=["requirements.txt"],
        expect_min_affected_packages=1,  # at minimum the added package should be captured
    ),

    EvalCase(
        id="empty_diff_no_changed_files",
        description="No changed_files at all — should short-circuit cleanly, not error.",
        guardrail=None,
        est_llm_calls=0,
        repo_owner="some-org", repo_name="some-repo",
        diff_text="",
        changed_files=[],
        expect_no_llm_call=True,
        expect_short_circuit_before_research=True,
        expect_intent_in=["no_relevant_changes"],
    ),

    EvalCase(
        id="input_rejection_missing_required_fields",
        description="Malformed PRDiffInput missing required fields — tests input validation guardrail at the schema level, before any agent runs.",
        guardrail="input_rejection",
        est_llm_calls=0,
        invalid_pr_diff_kwargs={"diff_text": "some diff"},  # missing repo_owner, repo_name
        expect_input_rejected=True,
    ),

    EvalCase(
        id="whitespace_only_manifest_change",
        description="Manifest file changed but only whitespace/formatting, no real dependency change.",
        guardrail=None,
        est_llm_calls=2,
        repo_owner="lodash", repo_name="lodash",
        diff_text="""diff --git a/package.json b/package.json
index 1234567..89abcde 100644
--- a/package.json
+++ b/package.json
@@ -8,7 +8,7 @@
   "dependencies": {
-    "lodash":    "^4.17.21",
+    "lodash": "^4.17.21",
   }
""",
        changed_files=["package.json"],
        # Expect it to correctly recognize no real change occurred, similar
        # spirit to the lockfile-churn case but purely whitespace this time.
        expect_unable_to_assess=False,
    ),
]