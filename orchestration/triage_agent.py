"""
Triage Agent: classifies a PR diff's intent (new dependency / version bump /
license change / no relevant changes) and extracts affected packages.

Scope note (see PRDiffInput docstring / README): this agent only considers
manifest-file changes (package.json, requirements.txt, Cargo.toml, pom.xml,
LICENSE) as relevant. This is not because non-manifest changes can't be
risky in general — a code change calling a new API from a bumped dependency
clearly can be. It's that this tool's entire value comes from calling
dependency-risk data sources (OSV, deps.dev, GitHub health) which require a
concrete (package_name, ecosystem, version) to query. A PR touching only
application code has no such triple to look up, so there is nothing this
tool's data sources could meaningfully assess — that's a scope boundary,
not blindness to risk in general. General code-risk review is a different
tool's job.

Failure handling: if the LLM's output doesn't parse into a valid TriageResult
(malformed JSON, schema violation), this agent does NOT retry — it fails
safe by returning a low-confidence TriageResult that the orchestrator's
existing confidence-threshold short-circuit routes to UNABLE_TO_ASSESS. This
reuses one failure path instead of introducing a second (retry-then-fail)
path, and keeps prompt quality — not runtime correction — as the thing that
has to actually be good.
"""

from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from orchestration.llm_backend import LLMBackend, LLMBackendError
from orchestration.schemas import PRDiffInput, TriageResult, TriageIntent

logger = logging.getLogger(__name__)

MANIFEST_FILENAMES = {
    "package.json",
    "package-lock.json",
    "requirements.txt",
    "pyproject.toml",
    "Cargo.toml",
    "Cargo.lock",
    "pom.xml",
    "build.gradle",
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
}

SYSTEM_PROMPT = """You are a dependency-change triage classifier for pull requests.

You will be given the names of changed files and the diff content for any
manifest/lockfile/license files that changed in a PR. Your job:

1. Classify the overall intent as exactly one of:
   - "new_dependency": a new package was added
   - "version_bump": an existing package's version changed
   - "license_change": a LICENSE file changed, or project license metadata changed
   - "no_relevant_changes": none of the above apply (e.g. only a lockfile
     churned with no real version change, or manifest formatting only)

2. Extract every affected package as an object with:
   - "name": exact package name as it appears in the manifest
   - "ecosystem": one of "npm", "pypi", "cargo", "maven" (infer from the
     manifest file type — package.json/package-lock.json = npm,
     requirements.txt/pyproject.toml = pypi, Cargo.toml/Cargo.lock = cargo,
     pom.xml/build.gradle = maven)
   - "old_version": version before the change, or null if newly added
   - "new_version": version after the change, or null if removed

3. Give a confidence score from 0.0 to 1.0 reflecting how certain you are
   about the intent classification and extracted packages. Use a LOW score
   (below 0.5) if the diff is ambiguous, truncated, or you are guessing at
   version numbers.

4. Give a one-sentence reasoning for your classification.

Respond with ONLY a JSON object, no markdown fences, no other text, in
exactly this shape:
{
  "intent": "new_dependency" | "version_bump" | "license_change" | "no_relevant_changes",
  "affected_packages": [
    {"name": "...", "ecosystem": "...", "old_version": "..." | null, "new_version": "..." | null}
  ],
  "confidence": 0.0-1.0,
  "reasoning": "..."
}
"""


def _extract_manifest_diff_sections(pr_diff: PRDiffInput) -> str:
    """Pull out only the diff hunks for manifest files, to keep the prompt
    small and focused. Falls back to the full diff_text if we can't cleanly
    split it (e.g. unexpected diff format) — better to over-include than
    silently drop relevant content."""
    relevant_files = [f for f in pr_diff.changed_files if f.rsplit("/", 1)[-1] in MANIFEST_FILENAMES]
    if not relevant_files:
        return ""

    # Unified diff hunks start with "diff --git a/<path> b/<path>".
    # Split the whole diff on that marker and keep only hunks whose path
    # matches a relevant manifest file.
    sections = pr_diff.diff_text.split("diff --git ")
    matched = [s for s in sections if any(f in s for f in relevant_files)]

    if not matched:
        logger.warning(
            "Manifest files %s listed in changed_files but no matching diff "
            "hunk found — falling back to full diff_text", relevant_files,
        )
        return pr_diff.diff_text

    return "diff --git " + "diff --git ".join(matched)


class TriageAgent:
    def __init__(self, llm_backend: LLMBackend):
        self._llm_backend = llm_backend

    async def run(self, pr_diff: PRDiffInput) -> TriageResult:
        manifest_diff = _extract_manifest_diff_sections(pr_diff)

        # No manifest files touched at all — deterministic short-circuit,
        # no LLM call needed. Cheaper and more reliable than asking the
        # model to notice "there's nothing relevant here."
        if not manifest_diff:
            return TriageResult(
                intent=TriageIntent.NO_RELEVANT_CHANGES,
                affected_packages=[],
                confidence=1.0,
                reasoning="No manifest, lockfile, or license files were changed in this PR.",
            )

        user_prompt = (
            f"Changed files:\n{chr(10).join(pr_diff.changed_files)}\n\n"
            f"Relevant diff content:\n{manifest_diff}"
        )

        try:
            raw_output = await self._llm_backend.complete(SYSTEM_PROMPT, user_prompt)
        except LLMBackendError as e:
            logger.warning("Triage LLM call failed: %s", e)
            return self._unable_to_assess_result(f"LLM call failed: {e}")

        try:
            parsed = json.loads(raw_output)
            return TriageResult(**parsed)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(
                "Triage LLM output failed to parse/validate. Raw output: %r. Error: %s",
                raw_output, e,
            )
            return self._unable_to_assess_result(f"Malformed triage output: {e}")

    @staticmethod
    def _unable_to_assess_result(reason: str) -> TriageResult:
        # Confidence 0.0 guarantees the orchestrator's threshold check routes
        # this to UNABLE_TO_ASSESS — reusing that path rather than a second
        # ad-hoc failure mode. Intent is a required field; NEW_DEPENDENCY is
        # an arbitrary non-NO_RELEVANT_CHANGES placeholder here since the
        # confidence gate is what actually decides the outcome, not intent.
        return TriageResult(
            intent=TriageIntent.NEW_DEPENDENCY,
            affected_packages=[],
            confidence=0.0,
            reasoning=reason,
        )