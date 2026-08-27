"""Real end-to-end test: spawns server.py over stdio and hits live APIs
(OSV.dev, GitHub, deps.dev). Slow and network-dependent by design — this is
the only test that actually validates the client-side MCP SDK usage against
reality, which unit tests with a fake session cannot do.

Marked so it's excluded from the default fast test run. Run explicitly with:
    pytest tests/test_mcp_client_integration.py -v -m integration
or include it with:
    pytest -m integration
"""

import pytest

from orchestration.mcp_client import MCPToolClient

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_real_get_risk_score_known_good_package():
    async with MCPToolClient() as client:
        result = await client.get_risk_score(
            owner="expressjs", repo="express",
            package_name="express", ecosystem="npm", version="4.18.2",
            project_license="MIT",
        )

    assert result.is_error is False
    assert "composite_score" in result.data
    assert "band" in result.data
    assert result.data["maintenance_health"]["owner"] == "expressjs"


@pytest.mark.asyncio
async def test_real_domain_error_on_nonexistent_repo():
    async with MCPToolClient() as client:
        result = await client.get_maintenance_health(owner="nobody", repo="doesnt-exist-xyz-123")

    assert result.is_error is True
    assert result.error_type == "not_found"