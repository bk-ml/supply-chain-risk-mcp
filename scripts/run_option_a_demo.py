"""
One-command setup and demo for supply-chain-risk-mcp (Option A).

Runs, in order:
  1. pip install -e .          (with a warning if not in a virtualenv)
  2. python demo.py            (fast, zero-config CLI proof it works)
  3. MCP Inspector              (interactive browser UI — blocks until you close it)

Usage:
    python scripts/run_option_a_demo.py
    python scripts/run_option_a_demo.py --skip-inspector   # steps 1-2 only
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _print_step(n: int, total: int, title: str) -> None:
    print(f"\n{'=' * 70}\nStep {n}/{total}: {title}\n{'=' * 70}")


def _in_virtualenv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _run(cmd: list[str], **kwargs) -> int:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=REPO_ROOT, **kwargs).returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-inspector", action="store_true",
                         help="Run install + demo.py only, skip launching MCP Inspector")
    args = parser.parse_args()

    total_steps = 2 if args.skip_inspector else 3

    if not _in_virtualenv():
        print("WARNING: you don't appear to be in a virtual environment.")
        print("This will install into your global/system Python.")
        response = input("Continue anyway? [y/N] ").strip().lower()
        if response != "y":
            print("Aborted. Create a virtualenv first, e.g.:")
            print("  python -m venv .venv && source .venv/bin/activate")
            sys.exit(1)

    _print_step(1, total_steps, "Installing supply-chain-risk-mcp (pip install -e .)")
    rc = _run([sys.executable, "-m", "pip", "install", "-e", "."])
    if rc != 0:
        print("Install failed — see output above.")
        sys.exit(rc)

    _print_step(2, total_steps, "Running demo.py (zero-config, no API keys needed)")
    rc = _run([sys.executable, str(REPO_ROOT / "demo.py")])
    if rc != 0:
        print("Demo script failed — see output above.")
        sys.exit(rc)

    if args.skip_inspector:
        print("\nDone (--skip-inspector was set). To explore interactively, run:")
        print("  npx @modelcontextprotocol/inspector python server.py")
        return

    _print_step(3, total_steps, "Launching MCP Inspector (interactive browser UI)")
    if shutil.which("npx") is None:
        print("npx not found — MCP Inspector requires Node.js.")
        print("Install Node.js from https://nodejs.org, then run:")
        print("  npx @modelcontextprotocol/inspector python server.py")
        sys.exit(1)

    print("Opening MCP Inspector in your browser. Press Ctrl+C here to stop it.")
    _run(["npx", "@modelcontextprotocol/inspector", sys.executable, str(REPO_ROOT / "server.py")])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nStopped.")
        sys.exit(0)