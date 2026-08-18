"""Client for the OSV.dev vulnerability database API. No auth required."""

import httpx
from pydantic import BaseModel

OSV_API_URL = "https://api.osv.dev/v1/query"


class OSVClientError(Exception):
    """Base exception for all OSV client errors."""


class PackageNotFoundError(OSVClientError):
    """Raised when the package/ecosystem combination returns no results."""


class RateLimitError(OSVClientError):
    """Raised when OSV.dev returns a 429."""


class OSVAPIError(OSVClientError):
    """Raised for any other unexpected API failure."""


class Vulnerability(BaseModel):
    id: str
    summary: str | None = None
    severity_label: str | None = None   # e.g. "HIGH", "CRITICAL" — best-effort
    cvss_score: float | None = None      # best-effort, may be unavailable
    aliases: list[str] = []              # e.g. ["CVE-2024-12345"]


class VulnQueryResult(BaseModel):
    package: str
    ecosystem: str
    version: str | None
    vulnerabilities: list[Vulnerability]

    @property
    def vulnerability_count(self) -> int:
        return len(self.vulnerabilities)


def _extract_severity(raw_vuln: dict) -> tuple[str | None, float | None]:
    """OSV severity data is inconsistent across entries — handle the common shapes."""
    label = raw_vuln.get("database_specific", {}).get("severity")

    score = None
    for sev in raw_vuln.get("severity", []):
        if sev.get("type") == "CVSS_V3" and "score" in sev:
            try:
                score = float(sev["score"])
            except (ValueError, TypeError):
                pass
            break

    return label, score


async def query_vulnerabilities(
    package: str, ecosystem: str, version: str | None = None
) -> VulnQueryResult:
    """Query OSV.dev for known vulnerabilities affecting a package.

    Raises:
        PackageNotFoundError: no vulnerabilities data available for this package/ecosystem.
        RateLimitError: OSV.dev rate limit hit.
        OSVAPIError: any other unexpected failure.
    """
    body: dict = {"package": {"name": package, "ecosystem": ecosystem}}
    if version:
        body["version"] = version

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(OSV_API_URL, json=body)
        except httpx.TimeoutException as e:
            raise OSVAPIError(f"Request to OSV.dev timed out: {e}") from e
        except httpx.RequestError as e:
            raise OSVAPIError(f"Network error contacting OSV.dev: {e}") from e

    if response.status_code == 429:
        raise RateLimitError("OSV.dev rate limit exceeded. Try again shortly.")
    if response.status_code >= 400:
        raise OSVAPIError(f"OSV.dev returned status {response.status_code}: {response.text}")

    data = response.json()
    raw_vulns = data.get("vulns", [])

    vulns = []
    for raw in raw_vulns:
        label, score = _extract_severity(raw)
        vulns.append(
            Vulnerability(
                id=raw["id"],
                summary=raw.get("summary"),
                severity_label=label,
                cvss_score=score,
                aliases=raw.get("aliases", []),
            )
        )

    return VulnQueryResult(
        package=package, ecosystem=ecosystem, version=version, vulnerabilities=vulns
    )