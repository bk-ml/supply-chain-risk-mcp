"""
One-command setup and demo for the multi-agent PR dependency risk reviewer
(Option B).

Runs, in order:
  1. pip install -e ".[agents]"   (with a warning if not in a virtualenv)
  2. Checks GEMINI_API_KEY is set (via .env or environment)
  3. Runs one real case end-to-end through the full Orchestrator
  4. Optionally regenerates the eval report from existing results

Requires a GEMINI_API_KEY (free tier available at https://aistudio.google.com).
Unlike Option A, this makes real LLM calls and costs quota — this script
runs exactly ONE case, not the full 18-case eval suite (see evals/run_evals.py
for that).

Usage:
    python scripts/run_option_b_demo.py
    python scripts/run_option_b_demo.py --skip-report
"""

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


def _print_step(n: int, total: int, title: str) -> None:
    print(f"\n{'=' * 70}\nStep {n}/{total}: {title}\n{'=' * 70}")


def _in_virtualenv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _run(cmd: list[str], **kwargs) -> int:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=REPO_ROOT, **kwargs).returncode


async def _run_one_demo_case():
    # Imported here, after install, so this script doesn't hard-fail if the
    # agents extra isn't installed yet when this file is first parsed.
    from orchestration.llm_backend import GeminiBackend
    from orchestration.triage_agent import TriageAgent
    from orchestration.research_agent import ResearchAgent
    from orchestration.synthesis_agent import SynthesisAgent
    from orchestration.orchestrator import Orchestrator
    from orchestration.schemas import PRDiffInput

    diff_text = """diff --git a/package.json b/package.json
index 1234567..89abcde 100644
--- a/package.json
+++ b/package.json
@@ -10,7 +10,7 @@
   "dependencies": {
     "express": "^4.18.2",
-    "lodash": "^4.17.20",
+    "lodash": "^4.17.21",
   }
"""
    pr_diff = PRDiffInput(
        repo_owner="lodash", repo_name="lodash",
        diff_text=diff_text, changed_files=["package.json"], project_license="MIT",
    )

    backend = GeminiBackend(api_key=os.environ["GEMINI_API_KEY"])
    orchestrator = Orchestrator(
        triage_agent=TriageAgent(backend),
        research_agent=ResearchAgent(),
        synthesis_agent=SynthesisAgent(backend),
    )

    print("Running: Triage -> Research -> Synthesis on a real lodash version bump...")
    output, triage_result = await orchestrator.run(pr_diff)

    print(f"\nTriage classified this as: {triage_result.intent.value} "
          f"(confidence={triage_result.confidence:.2f})")
    print(f"\nFinal assessment:\n{output.model_dump_json(indent=2)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-report", action="store_true",
                         help="Skip regenerating evals/report.md at the end")
    args = parser.parse_args()

    total_steps = 3 if args.skip_report else 4

    if not _in_virtualenv():
        print("WARNING: you don't appear to be in a virtual environment.")
        print("This will install into your global/system Python.")
        response = input("Continue anyway? [y/N] ").strip().lower()
        if response != "y":
            print("Aborted. Create a virtualenv first, e.g.:")
            print("  python -m venv .venv && source .venv/bin/activate")
            sys.exit(1)

    _print_step(1, total_steps, 'Installing with the "agents" extra (pip install -e ".[agents]")')
    rc = _run([sys.executable, "-m", "pip", "install", "-e", ".[agents]"])
    if rc != 0:
        print("Install failed — see output above.")
        sys.exit(rc)

    _print_step(2, total_steps, "Checking for GEMINI_API_KEY")
    load_dotenv(REPO_ROOT / ".env")
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY not found in environment or .env file.")
        print("Get a free key at https://aistudio.google.com, then add to .env:")
        print("  GEMINI_API_KEY=your_key_here")
        sys.exit(1)
    print("Found GEMINI_API_KEY.")

    _print_step(3, total_steps, "Running one real case through the full multi-agent pipeline")
    print("Note: this makes real Gemini API calls and uses real quota "
          "(~2 calls for this single case).")
    asyncio.run(_run_one_demo_case())

    if args.skip_report:
        print("\nDone (--skip-report was set).")
        return

    _print_step(4, total_steps, "Regenerating evals/report.md from existing results")
    rc = _run([sys.executable, str(REPO_ROOT / "evals" / "generate_report.py")])
    if rc == 0:
        print("\nSee evals/report.md for the full 18-case eval suite results.")
        print("To re-run the full suite yourself: python evals/run_evals.py")


if __name__ == "__main__":
    main()