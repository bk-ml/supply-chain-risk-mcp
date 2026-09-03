"""
Thin wrapper around the MCP client SDK: spawns server.py as a subprocess over
stdio, and exposes typed async methods per tool instead of raw MCP JSON-RPC
calls. Keeps protocol-handling in one place, same spirit as Option A's
clients/ modules being isolated from server.py.

IMPORTANT — two distinct failure modes, handled differently:
1. TRANSPORT failures: the MCP connection itself breaks (server didn't start,
   process died, malformed response). These raise MCPTransportError.
2. DOMAIN failures: the tool call succeeded at the protocol level, but
   server.py's own error convention kicked in — the JSON result has
   {"error": true, "error_type": ..., "message": ...}. These are NOT
   exceptions here; they're returned as a normal (dict, is_error=True) result
   for the caller (Research Agent) to inspect and turn into a ToolCallError
   with error_type=DOMAIN.

UNVERIFIED: the client-side spawn/session API below is a best-effort draft
against the `mcp` SDK, not confirmed against a real run. server.py already
hit one breaking v2.0.0 change on the *server* side; the client-side API may
have shifted too. Treat this file as needing a real end-to-end smoke test
before trusting it, not as known-good.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

# Path to server.py at the repo root — adjust if your layout differs.
_SERVER_PY_PATH = Path(__file__).resolve().parent.parent / "server.py"


class MCPTransportError(Exception):
    """Connection/protocol-level failure — server didn't start, died, or
    returned something the client couldn't parse. Distinct from a domain
    error surfaced deliberately by server.py's own error convention."""


class ToolResult:
    """Wraps a tool call's outcome. is_error reflects server.py's own
    {"error": true, ...} convention, not a transport failure."""

    def __init__(self, data: dict):
        self.data = data
        self.is_error: bool = bool(data.get("error"))
        self.error_type: str | None = data.get("error_type")
        self.message: str | None = data.get("message")


class MCPToolClient:
    """One instance per orchestrator run (or per eval case) — spawns
    server.py fresh each time. Use as an async context manager:

        async with MCPToolClient() as client:
            result = await client.get_risk_score(...)
    """

    def __init__(self, server_path: Path = _SERVER_PY_PATH, github_token: str | None = None):
        self._server_path = server_path
        self._github_token = github_token
        self._session: ClientSession | None = None
        self._stdio_cm = None

    async def __aenter__(self) -> "MCPToolClient":
        env = {}
        if self._github_token:
            env["GITHUB_TOKEN"] = self._github_token

        server_params = StdioServerParameters(
            command="python",
            args=[str(self._server_path)],
            env=env or None,
        )

        try:
            self._stdio_cm = stdio_client(server_params)
            read_stream, write_stream = await self._stdio_cm.__aenter__()
            self._session = ClientSession(read_stream, write_stream)
            await self._session.__aenter__()
            await self._session.initialize()
        except Exception as e:
            raise MCPTransportError(f"Failed to start/initialize MCP server: {e}") from e

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session is not None:
            await self._session.__aexit__(exc_type, exc_val, exc_tb)
        if self._stdio_cm is not None:
            await self._stdio_cm.__aexit__(exc_type, exc_val, exc_tb)

    async def _call_tool(self, tool_name: str, arguments: dict) -> ToolResult:
        if self._session is None:
            raise MCPTransportError("MCPToolClient used outside of 'async with' context")

        try:
            raw_result = await self._session.call_tool(tool_name, arguments)
        except Exception as e:
            raise MCPTransportError(f"Transport failure calling '{tool_name}': {e}") from e

        try:
            # MCP tool results carry content blocks; our tools return a single
            # JSON-serializable dict via model_dump(mode="json"), so we expect
            # one text content block containing that JSON.
            content_blocks = raw_result.content
            if not content_blocks:
                raise MCPTransportError(f"'{tool_name}' returned no content blocks")
            text = content_blocks[0].text
            data = json.loads(text)
        except (AttributeError, json.JSONDecodeError, IndexError) as e:
            raise MCPTransportError(
                f"Failed to parse response from '{tool_name}': {e}"
            ) from e

        return ToolResult(data)

    # ---------- Typed methods, one per tool in server.py ----------

    async def check_vulnerabilities(
        self, package_name: str, ecosystem: str, version: str | None = None
    ) -> ToolResult:
        return await self._call_tool(
            "check_vulnerabilities",
            {"package_name": package_name, "ecosystem": ecosystem, "version": version},
        )

    async def get_dependency_graph(
        self, package_name: str, ecosystem: str, version: str
    ) -> ToolResult:
        return await self._call_tool(
            "get_dependency_graph",
            {"package_name": package_name, "ecosystem": ecosystem, "version": version},
        )

    async def get_maintenance_health(self, owner: str, repo: str) -> ToolResult:
        return await self._call_tool(
            "get_maintenance_health", {"owner": owner, "repo": repo}
        )

    async def check_license_conflicts(
        self, project_license: str, package_name: str, ecosystem: str, version: str
    ) -> ToolResult:
        return await self._call_tool(
            "check_license_conflicts",
            {
                "project_license": project_license,
                "package_name": package_name,
                "ecosystem": ecosystem,
                "version": version,
            },
        )

    async def get_risk_score(
        self,
        owner: str,
        repo: str,
        package_name: str,
        ecosystem: str,
        version: str,
        project_license: str = "MIT",
    ) -> ToolResult:
        return await self._call_tool(
            "get_risk_score",
            {
                "owner": owner,
                "repo": repo,
                "package_name": package_name,
                "ecosystem": ecosystem,
                "version": version,
                "project_license": project_license,
            },
        )