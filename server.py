"""MCP server exposing supply-chain risk assessment tools for open-source
packages: vulnerability checks (OSV.dev), dependency graphs and license
metadata (deps.dev), and maintenance health (GitHub API), combined into a
composite risk score. See SCORING.md for the scoring methodology.
"""

import json
import os

from dotenv import load_dotenv
from mcp.server import MCPServer

from clients import deps_dev_client, github_client, osv_client
from clients.deps_dev_client import DepsDevClientError
from clients.github_client import GitHubClientError, RepoNotFoundError
from clients.github_client import RateLimitError as GitHubRateLimitError
from clients.osv_client import OSVClientError
from logic.license_rules import LicenseConflictResult
from logic.license_rules import check_license_conflicts as run_license_check
from logic.scoring import calculate_risk_score

load_dotenv()

mcp = MCPServer("supply-chain-risk-mcp")

MAX_DEPS_TO_CHECK = 25  # cap on per-dependency license lookups to limit API calls

# In-memory cache for the repo://{owner}/{repo}/risk-summary resource.
# Resets on server restart; keyed by owner/repo only (last-checked package wins).
_risk_summary_cache: dict[str, dict] = {}


def _error(error_type: str, message: str) -> dict:
    return {"error": True, "error_type": error_type, "message": message}


# ---------- Internal helpers (real logic; tools are thin wrappers around these) ----------

async def _get_vulnerabilities(package_name: str, ecosystem: str, version: str | None):
    return await osv_client.query_vulnerabilities(package_name, ecosystem, version)


async def _get_dependency_graph(ecosystem: str, package_name: str, version: str):
    return await deps_dev_client.get_dependency_graph(ecosystem, package_name, version)


async def _get_maintenance_health(owner: str, repo: str):
    token = os.environ.get("GITHUB_TOKEN")
    return await github_client.get_repo_health(owner, repo, token=token)


async def _check_license_conflicts(
    project_license: str, package_name: str, ecosystem: str, version: str
) -> LicenseConflictResult:
    graph = await _get_dependency_graph(ecosystem, package_name, version)
    deps_to_check = [n for n in graph.nodes if n.name != package_name][:MAX_DEPS_TO_CHECK]

    dep_license_pairs = []
    for dep in deps_to_check:
        try:
            info = await deps_dev_client.get_version_info(dep.system, dep.name, dep.version)
            dep_license_pairs.append((dep.name, info.license or ""))
        except DepsDevClientError:
            dep_license_pairs.append((dep.name, ""))  # unknown license, don't fail the whole check

    return run_license_check(project_license, dep_license_pairs)


# ---------- Tools ----------

@mcp.tool()
async def check_vulnerabilities(package_name: str, ecosystem: str, version: str | None = None) -> dict:
    """Check a package for known vulnerabilities (CVEs) using the OSV.dev database.

    Use this when the user asks about security issues, CVEs, or known
    vulnerabilities for a specific package. Ecosystem examples: npm, PyPI, Go,
    crates.io, Maven. If version is omitted, checks vulnerabilities across all
    known versions of the package.
    """
    try:
        result = await _get_vulnerabilities(package_name, ecosystem, version)
    except osv_client.RateLimitError as e:
        return _error("rate_limited", str(e))
    except OSVClientError as e:
        return _error("api_error", str(e))
    return result.model_dump(mode="json")


@mcp.tool()
async def get_dependency_graph(package_name: str, ecosystem: str, version: str) -> dict:
    """Get the resolved dependency graph for a specific package version, via deps.dev.

    Use this when the user wants to know what a package depends on. Dependency
    graphs are only available for these ecosystems: npm, Cargo, Maven, PyPI.
    """
    try:
        result = await _get_dependency_graph(ecosystem, package_name, version)
    except deps_dev_client.UnsupportedEcosystemError as e:
        return _error("unsupported_ecosystem", str(e))
    except deps_dev_client.PackageNotFoundError as e:
        return _error("not_found", str(e))
    except deps_dev_client.RateLimitError as e:
        return _error("rate_limited", str(e))
    except DepsDevClientError as e:
        return _error("api_error", str(e))
    return result.model_dump(mode="json")


@mcp.tool()
async def get_maintenance_health(owner: str, repo: str) -> dict:
    """Get maintenance health signals for a public GitHub repo: last commit age,
    contributor count, and open issue backlog age.

    Use this when the user asks whether a project is actively maintained,
    abandoned, or run by a healthy contributor base. owner and repo are the
    GitHub path segments, e.g. for github.com/facebook/react: owner="facebook", repo="react".
    """
    try:
        result = await _get_maintenance_health(owner, repo)
    except RepoNotFoundError as e:
        return _error("not_found", str(e))
    except GitHubRateLimitError as e:
        return _error("rate_limited", str(e))
    except GitHubClientError as e:
        return _error("api_error", str(e))
    return result.model_dump(mode="json")


@mcp.tool()
async def check_license_conflicts(
    project_license: str, package_name: str, ecosystem: str, version: str
) -> dict:
    """Check a package's dependency tree for license conflicts against a given
    project license (e.g. flagging a GPL dependency pulled into an MIT project).

    Use this when the user asks about license compatibility or legal risk from
    open-source dependencies. This is a heuristic check based on license
    category, not legal advice. Checks up to the first 25 resolved
    dependencies, not the full transitive graph, to limit API calls.
    """
    try:
        result = await _check_license_conflicts(project_license, package_name, ecosystem, version)
    except deps_dev_client.UnsupportedEcosystemError as e:
        return _error("unsupported_ecosystem", str(e))
    except deps_dev_client.PackageNotFoundError as e:
        return _error("not_found", str(e))
    except deps_dev_client.RateLimitError as e:
        return _error("rate_limited", str(e))
    except DepsDevClientError as e:
        return _error("api_error", str(e))
    return result.model_dump(mode="json")


@mcp.tool()
async def get_risk_score(
    owner: str,
    repo: str,
    package_name: str,
    ecosystem: str,
    version: str,
    project_license: str = "MIT",
) -> dict:
    """Get a composite supply-chain risk score for a package: combines known
    vulnerabilities, GitHub maintenance health, and license conflicts into one
    0-100 score with a LOW/MEDIUM/HIGH/CRITICAL band and an explanation of what
    drove the score. See SCORING.md for the full methodology.

    Use this for a full risk assessment rather than checking each dimension
    separately. Note: vulnerability check currently covers the top-level
    package/version only, not every transitive dependency. Populates the
    repo://{owner}/{repo}/risk-summary resource cache for this repo.
    """
    try:
        vulns = await _get_vulnerabilities(package_name, ecosystem, version)
    except osv_client.RateLimitError as e:
        return _error("rate_limited", f"Vulnerability check failed: {e}")
    except OSVClientError as e:
        return _error("api_error", f"Vulnerability check failed: {e}")

    try:
        health = await _get_maintenance_health(owner, repo)
    except RepoNotFoundError as e:
        return _error("not_found", f"Maintenance check failed: {e}")
    except GitHubRateLimitError as e:
        return _error("rate_limited", f"Maintenance check failed: {e}")
    except GitHubClientError as e:
        return _error("api_error", f"Maintenance check failed: {e}")

    license_warning = None
    try:
        license_result = await _check_license_conflicts(project_license, package_name, ecosystem, version)
    except DepsDevClientError as e:
        license_result = LicenseConflictResult(project_license=project_license, checked_count=0, conflicts=[])
        license_warning = f"License check incomplete, treated as no data: {e}"

    score = calculate_risk_score(vulns, health, license_result)

    output = score.model_dump(mode="json")
    output["vulnerabilities_checked"] = vulns.model_dump(mode="json")
    output["maintenance_health"] = health.model_dump(mode="json")
    output["license_check"] = license_result.model_dump(mode="json")
    if license_warning:
        output["license_check_warning"] = license_warning

    _risk_summary_cache[f"{owner}/{repo}"] = output
    return output


# ---------- Resources ----------

@mcp.resource("repo://{owner}/{repo}/risk-summary")
async def repo_risk_summary(owner: str, repo: str) -> str:
    """Cached full risk summary for a repo. Populated after get_risk_score has
    been run for it in this server session — this is an in-memory cache, not
    persisted across restarts, and keyed by repo only (holds whichever package
    was most recently checked if a repo publishes several)."""
    key = f"{owner}/{repo}"
    if key not in _risk_summary_cache:
        return json.dumps(
            {"cached": False, "message": f"No cached risk summary for {key} yet. Run get_risk_score first."}
        )
    return json.dumps({"cached": True, **_risk_summary_cache[key]})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()