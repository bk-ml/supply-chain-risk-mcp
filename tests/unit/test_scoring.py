from clients.github_client import RepoHealth
from clients.osv_client import VulnQueryResult, Vulnerability
from logic.license_rules import LicenseConflict, LicenseConflictResult
from logic.scoring import RiskBand, calculate_risk_score


def _clean_vulns():
    return VulnQueryResult(package="test-pkg", ecosystem="npm", version="1.0.0", vulnerabilities=[])


def _healthy_repo():
    return RepoHealth(
        owner="test", repo="test-repo", stars=1000, default_branch="main",
        last_commit_date=None, days_since_last_commit=5,
        contributor_count=50, open_issue_count=10, oldest_open_issue_age_days=30,
    )


def _no_license_conflicts():
    return LicenseConflictResult(project_license="MIT", checked_count=5, conflicts=[])


def test_clean_package_scores_low():
    result = calculate_risk_score(_clean_vulns(), _healthy_repo(), _no_license_conflicts())

    assert result.band == RiskBand.LOW
    assert result.composite_score < 20


def test_critical_cve_dominates_even_with_healthy_repo():
    vulns = VulnQueryResult(
        package="risky-pkg", ecosystem="npm", version="1.0.0",
        vulnerabilities=[Vulnerability(id="CVE-2024-1", cvss_score=9.8)],
    )

    result = calculate_risk_score(vulns, _healthy_repo(), _no_license_conflicts())

    assert result.band == RiskBand.CRITICAL
    assert "vulnerability" in result.primary_driver

def test_escalation_does_not_inflate_the_composite_score():
    """Band gets escalated to CRITICAL, but composite_score should still
    reflect the real weighted average, not jump to match the band."""
    vulns = VulnQueryResult(package="p", ecosystem="npm", version="1.0",
                             vulnerabilities=[Vulnerability(id="CVE-1", cvss_score=9.8)])

    result = calculate_risk_score(vulns, _healthy_repo(), _no_license_conflicts())

    assert result.band == RiskBand.CRITICAL
    assert result.composite_score < 60  # still a modest weighted average, ~49
    
def test_multiple_low_severity_vulns_dont_average_down_a_critical_one():
    vulns = VulnQueryResult(
        package="mixed-pkg", ecosystem="npm", version="1.0.0",
        vulnerabilities=[
            Vulnerability(id="CVE-1", cvss_score=9.8),
            Vulnerability(id="CVE-2", cvss_score=2.0),
            Vulnerability(id="CVE-3", cvss_score=1.5),
        ],
    )

    result = calculate_risk_score(vulns, _healthy_repo(), _no_license_conflicts())

    assert result.vuln_score == 98.0  # highest CVSS * 10, not averaged


def test_stale_single_maintainer_repo_scores_high_maintenance_risk():
    stale_repo = RepoHealth(
        owner="test", repo="abandoned", stars=10, default_branch="main",
        last_commit_date=None, days_since_last_commit=1000,  # beyond 2yr cap
        contributor_count=1, open_issue_count=200, oldest_open_issue_age_days=900,
    )

    result = calculate_risk_score(_clean_vulns(), stale_repo, _no_license_conflicts())

    assert result.maintenance_score == 100.0  # capped staleness + single-maintainer penalty
    assert "maintenance" in result.primary_driver


def test_unknown_contributor_count_applies_penalty():
    repo = RepoHealth(
        owner="test", repo="unknown-contributors", stars=100, default_branch="main",
        last_commit_date=None, days_since_last_commit=5,
        contributor_count=None, open_issue_count=5, oldest_open_issue_age_days=10,
    )

    result = calculate_risk_score(_clean_vulns(), repo, _no_license_conflicts())

    assert result.maintenance_score >= 15  # penalty applied even though repo is fresh


def test_high_severity_license_conflict_scores_max_license_risk():
    conflicts = LicenseConflictResult(
        project_license="MIT", checked_count=1,
        conflicts=[LicenseConflict(package="gpl-dep", dependency_license="GPL-3.0",
                                     severity="high", reason="test")],
    )

    result = calculate_risk_score(_clean_vulns(), _healthy_repo(), conflicts)

    assert result.license_score == 100.0


def test_primary_driver_reflects_the_weighted_dominant_factor():
    """Maintenance is bad but not vuln-bad — weighted math should still pick
    correctly even though maintenance's raw score might be lower than vuln's."""
    vulns = VulnQueryResult(package="p", ecosystem="npm", version="1.0",
                             vulnerabilities=[Vulnerability(id="CVE-1", cvss_score=3.0)])
    stale_repo = RepoHealth(owner="t", repo="r", stars=1, default_branch="main",
                             last_commit_date=None, days_since_last_commit=1500,
                             contributor_count=1, open_issue_count=1,
                             oldest_open_issue_age_days=1)

    result = calculate_risk_score(vulns, stale_repo, _no_license_conflicts())

    # vuln_score=30*0.5=15, maintenance_score=100*0.3=30 -> maintenance should dominate
    assert "maintenance" in result.primary_driver