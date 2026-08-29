"""
Research Agent: given a TriageResult's affected packages, calls the MCP
server's get_risk_score tool once per package and assembles a ResearchResult.

Design decisions:

1. PARALLEL calls via asyncio.gather(). Each package's risk check is fully
   independent, and a single get_risk_score call can fan out into ~30 HTTP
   requests under the hood (OSV + GitHub x3 + deps.dev per transitive dep).
   Sequential calls would multiply that latency by package count for no
   benefit — this is a legitimate design choice for a multi-package PR, not
   a premature optimization.

2. PARTIAL results. If get_risk_score fails or returns a domain error for
   one package (e.g. unsupported ecosystem), that failure is recorded in
   that package's tool_errors and the other packages' results are still
   returned. One package's failure never blocks assessment of the rest.

3. KNOWN LIMITATION, documented explicitly rather than left implicit:
   get_risk_score's maintenance-health dimension checks the health of
   `owner`/`repo` as passed in — which this agent passes as the PR's OWN
   repo (from PRDiffInput), not each dependency's upstream repo. E.g. for a
   PR bumping lodash in your-org/your-app, the maintenance-health portion of
   the score reflects your-org/your-app's health, NOT lodash/lodash's health.
   This is a real limitation of get_risk_score's signature (it conflates
   "repo to check health for" with "repo whose package is being scored"),
   inherited from Option A, not introduced here. Correctly resolving each
   package's own upstream GitHub repo would require reliable package-name
   -> GitHub-repo inference, which is unreliable to do generically and was
   decided against for time. Synthesis Agent's recommendation language
   should reflect this — the maintenance dimension is about the consuming
   project, not the dependency, and this should be stated plainly rather
   than presented as if it were dependency health.
"""

from __future__ import annotations

import asyncio
import logging
import re

from orchestration.mcp_client import MCPToolClient, MCPTransportError
from orchestration.schemas import (
    PRDiffInput,
    TriageResult,
    PackageRef,
    PackageRiskData,
    ResearchResult,
    ToolCallError,
    ToolCallErrorType,
)

logger = logging.getLogger(__name__)

_VERSION_RANGE_PREFIX_RE = re.compile(r"^[\^~>=<]+\s*")


def _normalize_version(raw_version: str) -> str:
    """Strip semver range operators (^, ~, >=, etc.) to get a base version
    usable by deps.dev's exact-version lookup APIs.

    KNOWN LIMITATION: this is an approximation, not a real resolution. A
    range like "^4.17.20" doesn't tell you the exact version actually
    installed — only a lockfile (package-lock.json, Cargo.lock, etc.) has
    that. Stripping the operator and using the range's base version is the
    best available approximation without parsing lockfiles, which was
    decided against for time. This means risk checks may occasionally run
    against a slightly different version than what's actually resolved,
    particularly for ranges like "^4.17.20" which permit any 4.x.x >= that.
    """
    return _VERSION_RANGE_PREFIX_RE.sub("", raw_version).strip()


class ResearchAgent:
    async def run(
        self,
        triage_result: TriageResult,
        pr_diff: PRDiffInput,
        mcp_client: MCPToolClient,
    ) -> ResearchResult:
        tasks = [
            self._research_one_package(pkg, pr_diff, mcp_client)
            for pkg in triage_result.affected_packages
        ]
        package_results = await asyncio.gather(*tasks) if tasks else []

        return ResearchResult(package_results=list(package_results))

    async def _research_one_package(
        self,
        package_ref: PackageRef,
        pr_diff: PRDiffInput,
        mcp_client: MCPToolClient,
    ) -> PackageRiskData:
        version = package_ref.new_version or package_ref.old_version
        result_data = PackageRiskData(package_ref=package_ref)

        if version is None:
            # No usable version to check (e.g. a removed package with only
            # old_version set to something unparseable, or genuinely no
            # version info extracted). Record as a domain-level gap rather
            # than attempting a call we know is meaningless.
            result_data.tool_errors.append(ToolCallError(
                tool_name="get_risk_score",
                error_type=ToolCallErrorType.DOMAIN,
                message=f"No usable version available for {package_ref.name}; skipping risk check.",
            ))
            return result_data

        normalized_version = _normalize_version(version)
        if normalized_version != version:
            logger.info(
                "Normalized version range %r -> %r for %s (see _normalize_version limitation)",
                version, normalized_version, package_ref.name,
            )

        try:
            tool_result = await mcp_client.get_risk_score(
                owner=pr_diff.repo_owner,
                repo=pr_diff.repo_name,
                package_name=package_ref.name,
                ecosystem=package_ref.ecosystem,
                version=normalized_version,
                project_license=pr_diff.project_license,
            )
        except MCPTransportError as e:
            logger.error("Transport failure researching %s: %s", package_ref.name, e)
            result_data.tool_errors.append(ToolCallError(
                tool_name="get_risk_score",
                error_type=ToolCallErrorType.TRANSPORT,
                message=str(e),
            ))
            return result_data

        if tool_result.is_error:
            logger.warning(
                "Domain error researching %s: %s (%s)",
                package_ref.name, tool_result.message, tool_result.error_type,
            )
            result_data.tool_errors.append(ToolCallError(
                tool_name="get_risk_score",
                error_type=ToolCallErrorType.DOMAIN,
                message=tool_result.message or "Unknown error",
            ))
            return result_data

        # Success — populate from the merged get_risk_score payload.
        # Import here (not top-level) to avoid a hard dependency on Option A's
        # exact pydantic types if this module is ever used standalone.
        from clients.osv_client import VulnQueryResult
        from clients.github_client import RepoHealth
        from logic.license_rules import LicenseConflictResult
        from logic.scoring import RiskScoreResult

        data = tool_result.data
        result_data.risk_score = RiskScoreResult(
            composite_score=data["composite_score"],
            band=data["band"],
            vuln_score=data["vuln_score"],
            maintenance_score=data["maintenance_score"],
            license_score=data["license_score"],
            primary_driver=data["primary_driver"],
        )
        result_data.vulnerabilities = VulnQueryResult(**data["vulnerabilities_checked"])
        result_data.repo_health = RepoHealth(**data["maintenance_health"])
        result_data.license_conflicts = LicenseConflictResult(**data["license_check"])

        if "license_check_warning" in data:
            result_data.tool_errors.append(ToolCallError(
                tool_name="get_risk_score",
                error_type=ToolCallErrorType.DOMAIN,
                message=data["license_check_warning"],
            ))

        return result_data