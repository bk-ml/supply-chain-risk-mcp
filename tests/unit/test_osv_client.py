import httpx
import pytest

from clients.osv_client import (
    OSVAPIError,
    RateLimitError,
    query_vulnerabilities,
    _normalize_ecosystem_for_osv
)

def test_normalize_ecosystem_maps_known_names():
    assert _normalize_ecosystem_for_osv("npm") == "npm"
    assert _normalize_ecosystem_for_osv("pypi") == "PyPI"
    assert _normalize_ecosystem_for_osv("cargo") == "crates.io"
    assert _normalize_ecosystem_for_osv("maven") == "Maven"
 
 
def test_normalize_ecosystem_is_case_insensitive_on_input():
    assert _normalize_ecosystem_for_osv("PyPI") == "PyPI"
    assert _normalize_ecosystem_for_osv("PYPI") == "PyPI"
 
 
def test_normalize_ecosystem_passes_through_unknown_unchanged():
    assert _normalize_ecosystem_for_osv("some-unknown-ecosystem") == "some-unknown-ecosystem"

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
 
 
@pytest.mark.asyncio
async def test_query_vulnerabilities_sends_osv_canonical_ecosystem_string(mocker):
    captured_body = {}
 
    async def fake_post(self, url, json=None):
        captured_body.update(json)
        return httpx.Response(200, json={"vulns": []}, request=httpx.Request("POST", url))
 
    mocker.patch("httpx.AsyncClient.post", fake_post)
 
    await query_vulnerabilities("pyjwt", "pypi", "2.8.0")
 
    # This is the actual regression check: the request body sent to OSV.dev
    # must use OSV's canonical "PyPI", not our internal lowercase "pypi".
    assert captured_body["package"]["ecosystem"] == "PyPI"
 
 
@pytest.mark.asyncio
async def test_query_vulnerabilities_result_preserves_original_ecosystem_string(mocker):
    async def fake_post(self, url, json=None):
        return httpx.Response(200, json={"vulns": []}, request=httpx.Request("POST", url))
 
    mocker.patch("httpx.AsyncClient.post", fake_post)
 
    result = await query_vulnerabilities("pyjwt", "pypi", "2.8.0")
 
    # The result's ecosystem field should reflect OUR naming convention
    # (lowercase "pypi"), not OSV's translated "PyPI" — downstream code
    # (PackageRef, Research/Synthesis Agents) expects our own convention.
    assert result.ecosystem == "pypi"
 