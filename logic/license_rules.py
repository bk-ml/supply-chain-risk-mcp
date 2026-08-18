"""SPDX-based license conflict detection. This is a heuristic classifier for
flagging licenses worth a human review — it is NOT legal advice, and does not
account for linking method, distribution model, or jurisdiction.
"""

from enum import IntEnum

from pydantic import BaseModel


class LicenseCategory(IntEnum):
    """Ordered by increasing obligation/risk — used to resolve OR/AND expressions."""
    PERMISSIVE = 0
    WEAK_COPYLEFT = 1
    STRONG_COPYLEFT = 2
    UNKNOWN = 3


_LICENSE_MAP: dict[str, LicenseCategory] = {
    # Permissive
    "MIT": LicenseCategory.PERMISSIVE,
    "BSD-2-CLAUSE": LicenseCategory.PERMISSIVE,
    "BSD-3-CLAUSE": LicenseCategory.PERMISSIVE,
    "APACHE-2.0": LicenseCategory.PERMISSIVE,
    "ISC": LicenseCategory.PERMISSIVE,
    "0BSD": LicenseCategory.PERMISSIVE,
    "UNLICENSE": LicenseCategory.PERMISSIVE,
    "CC0-1.0": LicenseCategory.PERMISSIVE,
    # Weak copyleft
    "LGPL-2.1": LicenseCategory.WEAK_COPYLEFT,
    "LGPL-2.1-ONLY": LicenseCategory.WEAK_COPYLEFT,
    "LGPL-2.1-OR-LATER": LicenseCategory.WEAK_COPYLEFT,
    "LGPL-3.0": LicenseCategory.WEAK_COPYLEFT,
    "LGPL-3.0-ONLY": LicenseCategory.WEAK_COPYLEFT,
    "LGPL-3.0-OR-LATER": LicenseCategory.WEAK_COPYLEFT,
    "MPL-2.0": LicenseCategory.WEAK_COPYLEFT,
    "EPL-2.0": LicenseCategory.WEAK_COPYLEFT,
    # Strong copyleft
    "GPL-2.0": LicenseCategory.STRONG_COPYLEFT,
    "GPL-2.0-ONLY": LicenseCategory.STRONG_COPYLEFT,
    "GPL-2.0-OR-LATER": LicenseCategory.STRONG_COPYLEFT,
    "GPL-3.0": LicenseCategory.STRONG_COPYLEFT,
    "GPL-3.0-ONLY": LicenseCategory.STRONG_COPYLEFT,
    "GPL-3.0-OR-LATER": LicenseCategory.STRONG_COPYLEFT,
    "AGPL-3.0": LicenseCategory.STRONG_COPYLEFT,
    "AGPL-3.0-ONLY": LicenseCategory.STRONG_COPYLEFT,
    "AGPL-3.0-OR-LATER": LicenseCategory.STRONG_COPYLEFT,
}


class LicenseConflict(BaseModel):
    package: str
    dependency_license: str
    severity: str   # "high" | "medium"
    reason: str


class LicenseConflictResult(BaseModel):
    project_license: str
    checked_count: int
    conflicts: list[LicenseConflict]

    @property
    def has_conflicts(self) -> bool:
        return len(self.conflicts) > 0


def classify_license(spdx_token: str) -> LicenseCategory:
    """Classify a single SPDX license identifier (no OR/AND expressions here)."""
    normalized = spdx_token.strip().strip("()").upper()
    return _LICENSE_MAP.get(normalized, LicenseCategory.UNKNOWN)


def _resolve_expression(license_str: str | None) -> LicenseCategory:
    """Resolve an SPDX expression to a single category.
    'OR' (dual-license) resolves to the LEAST restrictive option (consumer's choice).
    'AND' (conjunctive) resolves to the MOST restrictive option (all terms apply).
    """
    if not license_str or not license_str.strip():
        return LicenseCategory.UNKNOWN

    normalized = license_str.strip()

    if " OR " in normalized.upper():
        parts = [p.strip() for p in normalized.split(" OR ")]
        # case-insensitive split workaround: re-split preserving original case tokens
        parts = [p for p in normalized.replace(" or ", " OR ").split(" OR ")]
        return min(classify_license(p) for p in parts)

    if " AND " in normalized.upper():
        parts = normalized.replace(" and ", " AND ").split(" AND ")
        return max(classify_license(p) for p in parts)

    return classify_license(normalized)


def _evaluate_conflict(
    package: str, project_category: LicenseCategory, dep_license_str: str, dep_category: LicenseCategory
) -> LicenseConflict | None:
    if dep_category == LicenseCategory.STRONG_COPYLEFT and project_category in (
        LicenseCategory.PERMISSIVE,
        LicenseCategory.WEAK_COPYLEFT,
    ):
        return LicenseConflict(
            package=package,
            dependency_license=dep_license_str,
            severity="high",
            reason=(
                "Strong copyleft dependency (e.g. GPL/AGPL) typically requires derivative "
                "works to be licensed under the same terms — review before distributing."
            ),
        )

    if dep_category == LicenseCategory.WEAK_COPYLEFT and project_category == LicenseCategory.PERMISSIVE:
        return LicenseConflict(
            package=package,
            dependency_license=dep_license_str,
            severity="medium",
            reason=(
                "Weak copyleft dependency (e.g. LGPL/MPL) may require source disclosure of "
                "modifications depending on how it's linked — verify usage pattern."
            ),
        )

    if dep_category == LicenseCategory.UNKNOWN:
        return LicenseConflict(
            package=package,
            dependency_license=dep_license_str or "(none declared)",
            severity="medium",
            reason="License could not be identified from available data — manual review needed.",
        )

    return None


def check_license_conflicts(
    project_license: str, dependencies: list[tuple[str, str]]
) -> LicenseConflictResult:
    """Check a project's license against its dependencies' licenses for potential
    conflicts. Heuristic only — not legal advice.

    Args:
        project_license: SPDX identifier or expression for the project itself.
        dependencies: list of (package_name, license_string) tuples.
    """
    project_category = _resolve_expression(project_license)

    conflicts = []
    for package, dep_license_str in dependencies:
        dep_category = _resolve_expression(dep_license_str)
        conflict = _evaluate_conflict(package, project_category, dep_license_str, dep_category)
        if conflict:
            conflicts.append(conflict)

    return LicenseConflictResult(
        project_license=project_license,
        checked_count=len(dependencies),
        conflicts=conflicts,
    )