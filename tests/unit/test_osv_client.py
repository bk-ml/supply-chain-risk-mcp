import httpx
import pytest

from clients.osv_client import (
    OSVAPIError,
    RateLimitError,
    query_vulnerabilities,
)


@pytest.mark.asyncio
async def test_query_returns_empty_when_no_vulnerabilities(mocker):
    mock_response = httpx.Response(200, json={"vulns": []})
    mocker.patch("httpx.AsyncClient.post", return_value=mock_response)

    result = await query_vulnerabilities("some-clean-package", "PyPI")

    assert result.vulnerability_count == 0
    assert result.package == "some-clean-package"


@pytest.mark.asyncio
async def test_query_parses_multiple_severities(mocker):
    mock_json = {
        "vulns": [
            {
                "id": "GHSA-xxxx-xxxx-xxxx",
                "summary": "Test high severity vuln",
                "severity": [{"type": "CVSS_V3", "score": "7.5"}],
                "aliases": ["CVE-2024-11111"],
            },
            {
                "id": "GHSA-yyyy-yyyy-yyyy",
                "summary": "Test vuln with only a label",
                "database_specific": {"severity": "CRITICAL"},
                "aliases": [],
            },
        ]
    }
    mock_response = httpx.Response(200, json=mock_json)
    mocker.patch("httpx.AsyncClient.post", return_value=mock_response)

    result = await query_vulnerabilities("some-risky-package", "npm", version="1.2.3")

    assert result.vulnerability_count == 2
    assert result.vulnerabilities[0].cvss_score == 7.5
    assert result.vulnerabilities[1].severity_label == "CRITICAL"


@pytest.mark.asyncio
async def test_rate_limit_raises_specific_exception(mocker):
    mock_response = httpx.Response(429, text="rate limited")
    mocker.patch("httpx.AsyncClient.post", return_value=mock_response)

    with pytest.raises(RateLimitError):
        await query_vulnerabilities("any-package", "npm")


@pytest.mark.asyncio
async def test_unexpected_error_status_raises_generic_exception(mocker):
    mock_response = httpx.Response(500, text="server error")
    mocker.patch("httpx.AsyncClient.post", return_value=mock_response)

    with pytest.raises(OSVAPIError):
        await query_vulnerabilities("any-package", "npm")