import httpx
import pytest

from clients.deps_dev_client import (
    PackageNotFoundError,
    RateLimitError,
    UnsupportedEcosystemError,
    get_dependency_graph,
    get_version_info
)


@pytest.mark.asyncio
async def test_get_dependency_graph_parses_nodes(mocker):
    mock_json = {
        "nodes": [
            {"versionKey": {"system": "NPM", "name": "react", "version": "18.2.0"}, "bundled": False},
            {"versionKey": {"system": "NPM", "name": "loose-envify", "version": "1.4.0"}, "bundled": False},
        ]
    }
    mocker.patch("httpx.AsyncClient.get", return_value=httpx.Response(200, json=mock_json))

    result = await get_dependency_graph("npm", "react", "18.2.0")

    assert result.dependency_count == 1  # 2 nodes minus the root
    assert result.nodes[1].name == "loose-envify"


@pytest.mark.asyncio
async def test_unsupported_ecosystem_raises_before_any_request(mocker):
    mock_get = mocker.patch("httpx.AsyncClient.get")

    with pytest.raises(UnsupportedEcosystemError):
        await get_dependency_graph("nuget", "SomePackage", "1.0.0")

    mock_get.assert_not_called()  # should fail fast, no wasted network call


@pytest.mark.asyncio
async def test_package_not_found_raises_specific_exception(mocker):
    mocker.patch("httpx.AsyncClient.get", return_value=httpx.Response(404, text="not found"))

    with pytest.raises(PackageNotFoundError):
        await get_dependency_graph("npm", "definitely-not-a-real-package-xyz", "1.0.0")


@pytest.mark.asyncio
async def test_rate_limit_raises_specific_exception(mocker):
    mocker.patch("httpx.AsyncClient.get", return_value=httpx.Response(429, text="rate limited"))

    with pytest.raises(RateLimitError):
        await get_dependency_graph("npm", "react", "18.2.0")


@pytest.mark.asyncio
async def test_package_name_with_slash_gets_url_encoded(mocker):
    mock_get = mocker.patch(
        "httpx.AsyncClient.get",
        return_value=httpx.Response(200, json={"nodes": []}),
    )

    await get_dependency_graph("npm", "@colors/colors", "1.5.0")

    called_url = mock_get.call_args[0][0]
    assert "%2F" in called_url  # slash must be encoded, not passed raw

@pytest.mark.asyncio
async def test_get_version_info_parses_license(mocker):
    mocker.patch("httpx.AsyncClient.get", return_value=httpx.Response(200, json={"licenses": ["MIT"]}))

    result = await get_version_info("npm", "react", "18.2.0")

    assert result.license == "MIT"


@pytest.mark.asyncio
async def test_get_version_info_handles_missing_license(mocker):
    mocker.patch("httpx.AsyncClient.get", return_value=httpx.Response(200, json={}))

    result = await get_version_info("npm", "some-pkg", "1.0.0")

    assert result.license is None