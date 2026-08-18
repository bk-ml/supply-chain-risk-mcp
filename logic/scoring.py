"""Composite risk scoring. Combines vulnerability severity, maintenance health,
and license risk into a single 0-100 score. See SCORING.md for full methodology
and the reasoning behind the weights below — this is a heuristic, not an
empirically validated model.
"""

from enum import Enum

from pydantic import BaseModel

from clients.github_client import RepoHealth
from clients.osv_client import VulnQueryResult
from logic.license_rules import LicenseConflictResult

# Weights — see SCORING.md for reasoning
VULN_WEIGHT = 0.5
MAINTENANCE_WEIGHT = 0.3
LICENSE_WEIGHT = 0.2

STALENESS_CAP_DAYS = 730  # 2 years — beyond this, staleness score is maxed at 100
SINGLE_MAINTAINER_PENALTY = 15


class RiskBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskScoreResult(BaseModel):
    composite_score: float          # 0-100, higher = riskier
    band: RiskBand
    vuln_score: float
    maintenance_score: float
    license_score: float
    primary_driver: str             # human-readable explanation of what dominated


def _score_vulnerabilities(vuln_result: VulnQueryResult) -> float:
    """Highest CVSS score found, scaled to 0-100. Not averaged — one critical CVE
    shouldn't get diluted by a pile of low-severity ones."""
    if not vuln_result.vulnerabilities:
        return 0.0

    highest_cvss = max(
        (v.cvss_score for v in vuln_result.vulnerabilities if v.cvss_score is not None),
        default=None,
    )

    if highest_cvss is not None:
        return min(highest_cvss * 10, 100.0)

    # Fallback: no CVSS scores available, only severity labels
    labels = {v.severity_label for v in vuln_result.vulnerabilities if v.severity_label}
    if "CRITICAL" in labels:
        return 95.0
    if "HIGH" in labels:
        return 75.0
    if "MODERATE" in labels or "MEDIUM" in labels:
        return 50.0
    if "LOW" in labels:
        return 20.0
    # Vulnerabilities exist but we have zero severity info at all
    return 40.0


def _score_maintenance(repo_health: RepoHealth) -> float:
    """Linear staleness scaling, capped at 2 years, plus a flat penalty for
    single/unknown-maintainer bus-factor risk."""
    if repo_health.days_since_last_commit is None:
        staleness_score = 50.0  # unknown — treat as moderate risk, not zero
    else:
        staleness_score = min(
            100.0, (repo_health.days_since_last_commit / STALENESS_CAP_DAYS) * 100
        )

    penalty = 0.0
    if repo_health.contributor_count is None or repo_health.contributor_count <= 1:
        penalty = SINGLE_MAINTAINER_PENALTY

    return min(100.0, staleness_score + penalty)


def _score_license(license_result: LicenseConflictResult) -> float:
    """Worst conflict found, not averaged — same reasoning as vulnerabilities."""
    if not license_result.conflicts:
        return 0.0
    if any(c.severity == "high" for c in license_result.conflicts):
        return 100.0
    return 50.0  # only medium-severity conflicts present

class RiskBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

_BAND_ORDER = {RiskBand.LOW: 0, RiskBand.MEDIUM: 1, RiskBand.HIGH: 2, RiskBand.CRITICAL: 3}

# These map directly onto NVD's own CVSS qualitative severity ratings, since
# vuln_score = cvss_score * 10 (e.g. CVSS 9.0+ = "Critical" per NVD).
CRITICAL_VULN_THRESHOLD = 90.0
HIGH_VULN_THRESHOLD = 70.0
HIGH_LICENSE_THRESHOLD = 100.0

def _band_from_composite(score: float) -> RiskBand:
    if score <= 20:
        return RiskBand.LOW
    if score <= 50:
        return RiskBand.MEDIUM
    if score <= 75:
        return RiskBand.HIGH
    return RiskBand.CRITICAL


def _escalate(band: RiskBand, floor: RiskBand) -> RiskBand:
    return floor if _BAND_ORDER[floor] > _BAND_ORDER[band] else band

def _determine_band(composite: float, vuln_score: float, license_score: float) -> RiskBand:
    """Composite-score band, escalated if any single dimension is independently
    severe enough on its own — a critical CVE shouldn't get diluted just because
    everything else about the package looks healthy."""
    band = _band_from_composite(composite)

    if vuln_score >= CRITICAL_VULN_THRESHOLD:
        band = _escalate(band, RiskBand.CRITICAL)
    elif vuln_score >= HIGH_VULN_THRESHOLD:
        band = _escalate(band, RiskBand.HIGH)

    if license_score >= HIGH_LICENSE_THRESHOLD:
        band = _escalate(band, RiskBand.HIGH)

    return band


def _determine_primary_driver(
    vuln_score: float, maintenance_score: float, license_score: float
) -> str:
    weighted = {
        "an unpatched vulnerability": vuln_score * VULN_WEIGHT,
        "poor maintenance health": maintenance_score * MAINTENANCE_WEIGHT,
        "a license conflict": license_score * LICENSE_WEIGHT,
    }
    top_driver = max(weighted, key=weighted.get)
    if weighted[top_driver] == 0:
        return "no significant risk factors found"
    return f"driven primarily by {top_driver}"


def calculate_risk_score(
    vuln_result: VulnQueryResult,
    repo_health: RepoHealth,
    license_result: LicenseConflictResult,
) -> RiskScoreResult:
    """Combine the three risk dimensions into a single composite score."""
    vuln_score = _score_vulnerabilities(vuln_result)
    maintenance_score = _score_maintenance(repo_health)
    license_score = _score_license(license_result)

    composite = (
        vuln_score * VULN_WEIGHT
        + maintenance_score * MAINTENANCE_WEIGHT
        + license_score * LICENSE_WEIGHT
    )

    return RiskScoreResult(
        composite_score=round(composite, 1),
        band=_determine_band(composite, vuln_score, license_score),
        vuln_score=round(vuln_score, 1),
        maintenance_score=round(maintenance_score, 1),
        license_score=round(license_score, 1),
        primary_driver=_determine_primary_driver(vuln_score, maintenance_score, license_score),
    )