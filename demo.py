"""
Standalone demo script for the supply-chain-risk-mcp server.

Spawns server.py as a real MCP server over stdio (the same way Claude
Desktop or MCP Inspector would connect to it) and calls a small, curated
sequence of real tools against real public APIs — no mocking, no fixtures.

Requires NO API keys and NO configuration. OSV.dev, GitHub (unauthenticated),
and deps.dev are all free, no-auth public APIs. Just run:

    python demo.py

This exists purely to make the project reviewable in under a minute: clone,
run one command, see real tool calls succeed and fail gracefully — without
needing to configure Claude Desktop or open MCP Inspector.
"""

import asyncio
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_PATH = Path(__file__).resolve().parent / "server.py"


def _print_header(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def _print_result(data: dict) -> None:
    print(json.dumps(data, indent=2))


async def _call_tool(session: ClientSession, tool_name: str, arguments: dict) -> dict:
    result = await session.call_tool(tool_name, arguments)
    return json.loads(result.content[0].text)


async def main():
    print("supply-chain-risk-mcp — live demo")
    print("No API keys required. All calls hit real, free, public APIs")
    print("(OSV.dev, GitHub unauthenticated, deps.dev).")

    server_params = StdioServerParameters(command="python", args=[str(SERVER_PATH)])

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # --- 1. check_vulnerabilities: a package with well-known CVEs ---
            _print_header("1. check_vulnerabilities — lodash@4.17.15 (known-vulnerable version)")
            result = await _call_tool(session, "check_vulnerabilities", {
                "package_name": "lodash", "ecosystem": "npm", "version": "4.17.15",
            })
            _print_result(result)

            # --- 2. get_risk_score: the flagship tool, combines everything ---
            _print_header("2. get_risk_score — full composite risk assessment (express@4.18.2)")
            result = await _call_tool(session, "get_risk_score", {
                "owner": "expressjs", "repo": "express",
                "package_name": "express", "ecosystem": "npm", "version": "4.18.2",
                "project_license": "MIT",
            })
            _print_result(result)

            # --- 3. Graceful failure: a GitHub repo that doesn't exist ---
            _print_header("3. get_maintenance_health — nonexistent repo (graceful error handling)")
            result = await _call_tool(session, "get_maintenance_health", {
                "owner": "nobody", "repo": "this-repo-does-not-exist-xyz-123",
            })
            _print_result(result)
            if result.get("error"):
                print("\n-> Correctly returned a structured error, not a stack trace.")

    print(f"\n{'=' * 70}")
    print("Demo complete. See README.md for the full tool list and SCORING.md")
    print("for the risk-scoring methodology.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())