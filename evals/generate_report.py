"""
Generates a results report from evals/results/*.json — a markdown summary
table (evals/report.md) for embedding in the README, plus a CSV export
(evals/results.csv) for anyone who wants to chart it themselves.

A full chart wasn't built here: for ~18 pass/fail rows, a table communicates
the same information without a rendering step, and is easier to keep
current as cases are re-run over time (regenerating a markdown table is
just re-running this script; regenerating a chart image means committing a
new binary each time).

Usage:
    python evals/generate_report.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from evals.cases import CASES

RESULTS_DIR = Path(__file__).resolve().parent / "results"
CSV_PATH = Path(__file__).resolve().parent / "results.csv"
MD_PATH = Path(__file__).resolve().parent / "report.md"


def _load_results() -> list[dict]:
    results = []
    for f in sorted(RESULTS_DIR.glob("*.json")):
        results.append(json.loads(f.read_text()))
    return results


def _write_csv(results: list[dict]) -> None:
    fieldnames = [
        "case_id", "description", "guardrail", "passed",
        "risk_level", "latency_seconds", "est_llm_calls", "error",
    ]
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            output = r.get("output") or {}
            writer.writerow({
                "case_id": r["case_id"],
                "description": r["description"],
                "guardrail": r.get("guardrail") or "",
                "passed": r.get("passed"),
                "risk_level": output.get("risk_level", ""),
                "latency_seconds": round(r.get("latency_seconds", 0), 1),
                "est_llm_calls": r.get("est_llm_calls", 0),
                "error": r.get("error") or "",
            })


def _write_markdown(results: list[dict]) -> None:
    total_defined = len(CASES)
    total_run = len(results)
    total_passed = sum(1 for r in results if r.get("passed"))
    total_llm_calls = sum(r.get("est_llm_calls", 0) for r in results)
    total_latency = sum(r.get("latency_seconds", 0) for r in results)
    free_cases = sum(1 for c in CASES if c.est_llm_calls == 0)

    lines = [
        "# Eval Results",
        "",
        f"**{total_passed}/{total_run} passed** "
        f"({total_run}/{total_defined} of the full suite has been run so far)",
        "",
        f"- Total estimated LLM calls across run cases: {total_llm_calls}",
        f"- Total latency: {total_latency:.1f}s "
        f"(avg {total_latency/total_run:.1f}s/case)" if total_run else "",
        f"- {free_cases} of {total_defined} defined cases require zero LLM calls "
        "(deterministic short-circuit paths)",
        "",
        "Note: expected outcomes for cases involving real packages/repos "
        "(e.g. risk_level bands) are checked categorically, not as exact "
        "scores — vulnerability databases and repo health change over time, "
        "so a case passing today reflects real, current data, not a fixed "
        "fixture.",
        "",
        "| Case | Guardrail | Result | Risk Level | Latency | Est. LLM Calls |",
        "|---|---|---|---|---|---|",
    ]

    for r in results:
        status = "✅ PASS" if r.get("passed") else "❌ FAIL"
        guardrail = r.get("guardrail") or "—"
        output = r.get("output") or {}
        risk_level = output.get("risk_level", "—")
        latency = f"{r.get('latency_seconds', 0):.1f}s"
        calls = r.get("est_llm_calls", 0)
        lines.append(f"| `{r['case_id']}` | {guardrail} | {status} | {risk_level} | {latency} | {calls} |")

    not_yet_run = total_defined - total_run
    if not_yet_run > 0:
        lines.append("")
        lines.append(f"_{not_yet_run} case(s) not yet run — see `evals/run_evals.py`._")

    MD_PATH.write_text("\n".join(lines) + "\n")


def main():
    results = _load_results()
    if not results:
        print("No results found. Run evals/run_evals.py first.")
        return

    _write_csv(results)
    _write_markdown(results)
    print(f"Wrote {CSV_PATH} and {MD_PATH} ({len(results)} case(s))")


if __name__ == "__main__":
    main()