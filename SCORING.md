# Risk Scoring Methodology

This document explains how `supply-chain-risk-mcp` combines vulnerability data, maintenance health, and license conflicts into a single composite risk score.

**This is a heuristic, not an empirically validated model.** The weights below were chosen based on reasoning about urgency and exploitability, not backtested against real incident data. They are a defensible starting point, documented transparently, not a claim of precision.

## The three input dimensions

Each dimension is normalized independently to a 0–100 scale, where **higher always means riskier**. This convention is applied consistently across all three so the composite math stays intuitive.

### 1. Vulnerability score (from OSV.dev)

We take the **highest CVSS score** found among all known vulnerabilities for the package/version — not an average.

**Why not average:** averaging would let one critical CVE get diluted by a pile of low-severity ones. A package with one CVSS 9.8 and four CVSS 2.0s is still a package with a critical, actively exploitable flaw. The worst finding should drive the score, not the mean.

```
vuln_score = min(highest_cvss_score * 10, 100)
```

If no CVSS score is available but a severity label is (`CRITICAL`/`HIGH`/`MODERATE`/`LOW`), we fall back to fixed scores per label, since OSV.dev's severity data is inconsistently populated across entries.

### 2. Maintenance score (from GitHub API)

Two signals combined: staleness and bus-factor risk.

**Staleness** — linear scaling based on days since the last commit, capped at 2 years:

```
staleness_score = min(100, days_since_last_commit / 730 * 100)
```

We chose linear-with-a-cap over a log curve for simplicity and because it's easy to reason about and explain — a repo untouched for 2+ years is treated as maximally stale, and everything scales proportionally below that. This is a starting point, not a claim that risk grows perfectly linearly with time.

**Bus-factor penalty** — a flat +15 penalty is added if the repo has only 1 contributor, or if contributor count couldn't be determined. A single-maintainer project carries risk (abandonment, no code review, no succession) that pure staleness doesn't capture on its own.

```
maintenance_score = min(100, staleness_score + (15 if contributor_count <= 1 or unknown else 0))
```

### 3. License score (from SPDX classification)

Licenses are bucketed into four categories (permissive / weak copyleft / strong copyleft / unknown), and the **worst conflict found** (not averaged) determines the score:

```
license_score = 100 if any HIGH severity conflict
                50  if only MEDIUM severity conflicts
                0   if no conflicts
```

See the classification and conflict-severity rules in `logic/license_rules.py` for the full category mapping and reasoning — in short, a strong-copyleft dependency (GPL/AGPL) pulled into a permissive project is HIGH severity; a weak-copyleft dependency (LGPL/MPL) or an unrecognized license is MEDIUM.

**Explicit limitation:** this is a heuristic classifier based on license category alone. Real license compatibility also depends on linking method, distribution model, and jurisdiction — none of which we can determine from package metadata. This tool flags combinations worth a human legal review; it does not make a legal determination.

## The composite score

```
composite_score = (vuln_score × 0.5) + (maintenance_score × 0.3) + (license_score × 0.2)
```

**Why these weights:**

- **Vulnerabilities: 50%** — the only dimension with a concrete, exploitable, time-sensitive consequence. A critical CVE is an active risk today.
- **Maintenance: 30%** — an unmaintained package is a leading indicator of *future* vulnerability risk, even before a CVE exists. Nobody is patching it.
- **License: 20%** — a real but different *kind* of risk (legal/compliance exposure vs. security exposure). Weighted lowest not because it's unimportant, but because mixing categories of risk into one number is already a simplification, and giving it equal weight to active security exposure would overstate its urgency relative to an exploitable vulnerability.

## Score bands

```
0–20   → LOW
21–50  → MEDIUM
51–75  → HIGH
76–100 → CRITICAL
```

## Escalation rule 

The composite score is a **weighted average**, which means, by construction, no single dimension can push the composite above its own weight's ceiling. A perfect CVSS 10.0 vulnerability contributes at most `100 × 0.5 = 50` to the composite — never enough on its own to reach the CRITICAL band (76+), even though a critical, actively exploitable vulnerability clearly warrants that label regardless of how healthy the rest of the package looks.

To fix this, the **band** (not the composite score itself) is escalated independently when a single dimension is severe enough on its own:

- `vuln_score >= 90` (CVSS 9.0+, matching NVD's own "Critical" severity rating) → band floor set to **CRITICAL**
- `vuln_score >= 70` (CVSS 7.0+, NVD's "High" rating) → band floor set to **HIGH**
- `license_score == 100` (a HIGH severity license conflict) → band floor set to **HIGH**

The `composite_score` field is left untouched by escalation — it always reflects the true weighted average, so it remains useful for ranking/comparing packages against each other. The `band` field is what gets escalated, since that's the human-readable label people act on.

**Example:** a package with a single CVSS 9.8 vulnerability, otherwise perfectly maintained and license-clean, scores `composite_score ≈ 49` (MEDIUM by the raw formula) but is reported as `band = CRITICAL` due to escalation. Both numbers are shown in the output so the reasoning is legible, not hidden behind one opaque score.

## Attribution: `primary_driver`

Every result includes a plain-language explanation of what dominated the score, computed by comparing each dimension's *weighted* contribution (score × weight), not its raw value — a maintenance_score of 100 weighted at 0.3 can outweigh a vuln_score of 30 weighted at 0.5 (30 vs. 15), so the comparison has to happen after weighting, not before.

## Known limitations

- Weights (50/30/20) are a reasoned starting point, not empirically tuned against real incident/breach data.
- Staleness uses linear scaling; a log curve or a more nuanced decay function might better reflect how risk actually compounds over time, but that requires more evidence than we currently have to justify.
- License conflict detection is category-based, not a full legal compatibility analysis (see limitation above).
- GitHub's issues API doesn't cleanly separate issues from pull requests in the "oldest open issue" lookup, so that figure may occasionally reflect a stale PR instead.
- The composite score treats all three dimensions as independent and additive; in reality they can be correlated (e.g. unmaintained packages are also less likely to get CVEs patched quickly, which the vuln score doesn't currently account for).