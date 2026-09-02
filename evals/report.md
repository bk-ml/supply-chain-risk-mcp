# Eval Results

**18/18 passed** (18/18 of the full suite has been run so far)

- Total estimated LLM calls across run cases: 29
- Total latency: 233.2s (avg 13.0s/case)
- 3 of 18 defined cases require zero LLM calls (deterministic short-circuit paths)

Note: expected outcomes for cases involving real packages/repos (e.g. risk_level bands) are checked categorically, not as exact scores — vulnerability databases and repo health change over time, so a case passing today reflects real, current data, not a fixed fixture.

| Case | Guardrail | Result | Risk Level | Latency | Est. LLM Calls |
|---|---|---|---|---|---|
| `empty_diff_no_changed_files` | — | ✅ PASS | NOT_APPLICABLE | 0.0s | 0 |
| `garbled_diff_low_confidence` | low_confidence_refusal | ✅ PASS | UNABLE_TO_ASSESS | 12.0s | 1 |
| `gpl_dependency_into_mit_project` | — | ✅ PASS | LOW | 13.8s | 2 |
| `input_rejection_missing_required_fields` | input_rejection | ✅ PASS | — | 0.0s | 0 |
| `license_file_change` | — | ✅ PASS | UNABLE_TO_ASSESS | 3.2s | 2 |
| `lockfile_hash_only_churn` | — | ✅ PASS | NOT_APPLICABLE | 16.7s | 2 |
| `multiple_packages_one_diff` | — | ✅ PASS | HIGH | 50.5s | 2 |
| `new_dependency_cargo` | — | ✅ PASS | LOW | 17.4s | 2 |
| `new_dependency_maven` | — | ✅ PASS | LOW | 17.3s | 2 |
| `new_dependency_pypi` | — | ✅ PASS | HIGH | 9.9s | 2 |
| `no_relevant_changes_code_only` | — | ✅ PASS | NOT_APPLICABLE | 0.0s | 0 |
| `nonexistent_github_repo` | honest_refusal_on_tool_failure | ✅ PASS | UNABLE_TO_ASSESS | 4.7s | 2 |
| `nonexistent_package_real_repo` | — | ✅ PASS | LOW | 28.3s | 2 |
| `package_added_and_removed_same_diff` | — | ✅ PASS | UNABLE_TO_ASSESS | 7.2s | 2 |
| `version_bump_well_maintained_package` | — | ✅ PASS | MEDIUM | 19.4s | 2 |
| `version_downgrade` | — | ✅ PASS | UNABLE_TO_ASSESS | 16.3s | 2 |
| `vuln_known_bad_package` | — | ✅ PASS | HIGH | 13.3s | 2 |
| `whitespace_only_manifest_change` | — | ✅ PASS | NOT_APPLICABLE | 2.9s | 2 |
