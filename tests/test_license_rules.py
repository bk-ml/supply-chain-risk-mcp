from logic.license_rules import check_license_conflicts, classify_license, LicenseCategory


def test_classify_known_licenses():
    assert classify_license("MIT") == LicenseCategory.PERMISSIVE
    assert classify_license("gpl-3.0") == LicenseCategory.STRONG_COPYLEFT  # case-insensitive
    assert classify_license("LGPL-2.1") == LicenseCategory.WEAK_COPYLEFT
    assert classify_license("Some-Made-Up-License") == LicenseCategory.UNKNOWN


def test_permissive_project_with_strong_copyleft_dependency_is_high_severity():
    result = check_license_conflicts("MIT", [("some-gpl-lib", "GPL-3.0")])

    assert result.has_conflicts
    assert result.conflicts[0].severity == "high"


def test_permissive_project_with_weak_copyleft_dependency_is_medium_severity():
    result = check_license_conflicts("MIT", [("some-lgpl-lib", "LGPL-2.1")])

    assert result.has_conflicts
    assert result.conflicts[0].severity == "medium"


def test_matching_permissive_licenses_produce_no_conflict():
    result = check_license_conflicts("MIT", [("some-mit-lib", "MIT"), ("some-apache-lib", "Apache-2.0")])

    assert not result.has_conflicts
    assert result.checked_count == 2


def test_unknown_dependency_license_is_flagged_medium():
    result = check_license_conflicts("Apache-2.0", [("mystery-lib", "SomeWeirdLicense-1.0")])

    assert result.has_conflicts
    assert result.conflicts[0].severity == "medium"


def test_missing_dependency_license_is_flagged():
    result = check_license_conflicts("MIT", [("no-license-lib", "")])

    assert result.has_conflicts
    assert "manual review" in result.conflicts[0].reason


def test_dual_licensed_dependency_resolves_to_least_restrictive():
    """MIT OR GPL-3.0 means the consumer can choose MIT — should NOT conflict."""
    result = check_license_conflicts("MIT", [("dual-licensed-lib", "MIT OR GPL-3.0")])

    assert not result.has_conflicts


def test_conjunctive_license_resolves_to_most_restrictive():
    """GPL-2.0 AND Apache-2.0 means both apply — should conflict like pure GPL."""
    result = check_license_conflicts("MIT", [("conjunctive-lib", "GPL-2.0 AND Apache-2.0")])

    assert result.has_conflicts
    assert result.conflicts[0].severity == "high"