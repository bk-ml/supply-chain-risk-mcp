"""Unit tests for MCPToolClient — mocked MCP session, no real subprocess or
network calls. Tests the wrapper's own logic: parsing tool results, and
correctly distinguishing transport failures from domain errors (server.py's
own {"error": true, ...} convention).

See test_mcp_client_integration.py for a real end-to-end test that actually
spawns server.py and hits live APIs — kept separate so the normal fast test
suite doesn't depend on network access.
"""

import json
from types import SimpleNamespace

import pytest

from orchestration.mcp_client import MCPToolClient, MCPTransportError, ToolResult


def _fake_content_block(data: dict):
    return SimpleNamespace(text=json.dumps(data))


class FakeSession:
    """Stands in for mcp.ClientSession. call_tool_return controls what the
    next call_tool() call returns; set call_tool_side_effect to raise instead."""

    def __init__(self, call_tool_return: dict | None = None, call_tool_side_effect: Exception | None = None):
        self._return_data = call_tool_return
        self._side_effect = call_tool_side_effect
        self.last_call = None

    async def call_tool(self, tool_name: str, arguments: dict):
        self.last_call = (tool_name, arguments)
        if self._side_effect:
            raise self._side_effect
        return SimpleNamespace(content=[_fake_content_block(self._return_data)])


def _client_with_fake_session(fake_session: FakeSession) -> MCPToolClient:
    client = MCPToolClient()
    client._session = fake_session  # bypass __aenter__/spawn for unit-level testing
    return client


@pytest.mark.asyncio
async def test_successful_tool_call_returns_non_error_result():
    fake = FakeSession(call_tool_return={"composite_score": 10.0, "band": "LOW"})
    client = _client_with_fake_session(fake)

    result = await client.get_risk_score(
        owner="o", repo="r", package_name="p", ecosystem="npm", version="1.0.0"
    )

    assert isinstance(result, ToolResult)
    assert result.is_error is False
    assert result.data["band"] == "LOW"
    assert fake.last_call[0] == "get_risk_score"


@pytest.mark.asyncio
async def test_domain_error_is_not_raised_as_exception():
    # server.py's own error convention — this is a DOMAIN error, not a
    # transport failure, so it must come back as a normal ToolResult.
    fake = FakeSession(call_tool_return={
        "error": True, "error_type": "not_found", "message": "nope"
    })
    client = _client_with_fake_session(fake)

    result = await client.get_maintenance_health(owner="nobody", repo="doesnt-exist")

    assert result.is_error is True
    assert result.error_type == "not_found"
    assert result.message == "nope"


@pytest.mark.asyncio
async def test_transport_failure_raises_mcp_transport_error():
    fake = FakeSession(call_tool_side_effect=ConnectionError("pipe broke"))
    client = _client_with_fake_session(fake)

    with pytest.raises(MCPTransportError):
        await client.check_vulnerabilities(package_name="left-pad", ecosystem="npm")


@pytest.mark.asyncio
async def test_malformed_response_raises_mcp_transport_error():
    class BadContentSession(FakeSession):
        async def call_tool(self, tool_name: str, arguments: dict):
            # content block with unparseable text
            return SimpleNamespace(content=[SimpleNamespace(text="not valid json")])

    client = _client_with_fake_session(BadContentSession())

    with pytest.raises(MCPTransportError):
        await client.get_dependency_graph(package_name="p", ecosystem="npm", version="1.0.0")


@pytest.mark.asyncio
async def test_calling_client_outside_context_manager_raises():
    client = MCPToolClient()  # never entered async with — _session is None
    with pytest.raises(MCPTransportError):
        await client.get_maintenance_health(owner="o", repo="r")