"""
Message schemas passed between agents in the multi-agent orchestration layer.

Design note (scope decision, document in README):
PRDiffInput is deliberately scoped to MANIFEST-FILE changes (package.json,
requirements.txt, Cargo.toml, pom.xml, license files) rather than arbitrary
code diffs. Reasoning: Research Agent's tools require (package_name,
ecosystem, version) to call anything meaningful — that data is only reliably
extractable from manifest-file diffs, not general code changes. This keeps
Triage close to deterministic (parse structured manifest diff) rather than
an LLM guessing "is this dependency-relevant" from unstructured code, which
would be both less reliable and harder to eval consistently.

Design note: RiskScoreResult (composite scoring) already exists in Option A's
logic/scoring.py and is produced by the get_risk_score MCP tool. Research
Agent calls that tool directly and stores the ready-made result — it does NOT
re-derive scoring. Synthesis Agent interprets/phrases the already-computed
score; it does not recompute it. This keeps the scoring formula single-sourced
and deterministic rather than duplicated or LLM-reconstructed.
"""

from __future__ import annotations

from datetime import datetime, UTC
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

# Import Option A's existing result types directly — no duplication.
from clients.osv_client import VulnQueryResult
from clients.github_client import RepoHealth
from clients.deps_dev_client import DependencyGraphResult
from logic.license_rules import LicenseConflictResult
from logic.scoring import RiskScoreResult


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

class PackageRef(BaseModel):
    """A single package identified in a manifest diff."""
    name: str
    ecosystem: Literal["npm", "pypi", "cargo", "maven"]
    old_version: str | None = None
    new_version: str | None = None


class PRDiffInput(BaseModel):
    """Raw input to the orchestrator: a PR's manifest-relevant diff."""
    repo_owner: str
    repo_name: str
    pr_number: int | None = None

    diff_text: str
    """Full unified diff, kept for context/logging. Triage parses
    changed_files + manifest content, not this raw text, for extraction."""

    changed_files: list[str] = Field(default_factory=list)

    project_license: str = "MIT"
    """The consuming project's own license (SPDX identifier), required by
    get_risk_score for license-conflict checking. Caller-supplied rather than
    defaulted silently — real PR context should know this. Defaults to MIT
    only as a fallback for synthetic/test diffs that don't specify one."""


# ---------------------------------------------------------------------------
# Triage Agent output
# ---------------------------------------------------------------------------

class TriageIntent(str, Enum):
    NEW_DEPENDENCY = "new_dependency"
    VERSION_BUMP = "version_bump"
    LICENSE_CHANGE = "license_change"
    NO_RELEVANT_CHANGES = "no_relevant_changes"


class TriageResult(BaseModel):
    intent: TriageIntent
    affected_packages: list[PackageRef] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    """Short LLM-provided explanation — for logs/debugging, not shown to end user."""


# ---------------------------------------------------------------------------
# Research Agent output
# ---------------------------------------------------------------------------

class ToolCallErrorType(str, Enum):
    TRANSPORT = "transport"   # MCP/IPC-level failure (server didn't respond, malformed response)
    DOMAIN = "domain"         # typed error surfaced by Option A tools (PackageNotFoundError, etc.)


class ToolCallError(BaseModel):
    tool_name: str
    error_type: ToolCallErrorType
    message: str


class PackageRiskData(BaseModel):
    """Aggregated per-package results from all relevant MCP tool calls.
    Any field is None if that tool wasn't applicable or failed — check
    tool_errors to distinguish 'not applicable' from 'failed'."""
    package_ref: PackageRef

    vulnerabilities: VulnQueryResult | None = None
    dependency_graph: DependencyGraphResult | None = None
    license_conflicts: LicenseConflictResult | None = None
    repo_health: RepoHealth | None = None
    risk_score: RiskScoreResult | None = None
    """Ready-made composite score from Option A's get_risk_score tool.
    Research Agent stores this as-is; nothing downstream recomputes it."""

    tool_errors: list[ToolCallError] = Field(default_factory=list)


class ResearchResult(BaseModel):
    package_results: list[PackageRiskData] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Synthesis Agent output (final, schema-enforced — consumed by e.g. a PR bot)
# ---------------------------------------------------------------------------

class SynthesisRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNABLE_TO_ASSESS = "UNABLE_TO_ASSESS"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SynthesisOutput(BaseModel):
    risk_level: SynthesisRiskLevel
    affected_packages: list[str] = Field(default_factory=list)
    recommendation: str

    unable_to_assess: bool = False
    unable_to_assess_reason: str | None = None
    """Populated iff unable_to_assess is True — e.g. unknown ecosystem,
    all tool calls failed, or Triage confidence below threshold. This is
    the explicit low-confidence refusal path, not a crash/exception."""

    raw_agent_trace_id: str = Field(default_factory=lambda: str(uuid4()))
    """Ties this output back to the structured log for this run (Step 5.1)."""

    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))