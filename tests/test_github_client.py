import httpx
import pytest

from clients.github_client import (
    GitHubAPIError,
    RateLimitError,
    RepoNotFoundError,
    _parse_last_page_count,
    get_repo_health,
)


def _repo_response():
    return httpx.Response(
        200,
        json={
            "stargazers_count": 42000,
            "default_branch": "main",
            "pushed_at": "2026-08-01T12:00:00Z",
            "open_issues_count": 350,
        },
    )


def _contributors_response():
    return httpx.Response(
        200,
        json=[{"login": "someone"}],
        headers={"Link": '<https://api.github.com/...&page=87>; rel="last"'},
    )


def _issues_response():
    return httpx.Response(200, json=[{"created_at": "2024-01-15T00:00:00Z"}])


@pytest.mark.asyncio
async def test_get_repo_health_happy_path(mocker):
    mocker.patch(
        "httpx.AsyncClient.get",
        side_effect=[_repo_response(), _contributors_response(), _issues_response()],
    )

    result = await get_repo_health("facebook", "react")

    assert result.stars == 42000
    assert result.contributor_count == 87
    assert result.oldest_open_issue_age_days is not None
    assert result.days_since_last_commit is not None


@pytest.mark.asyncio
async def test_repo_not_found_raises(mocker):
    mocker.patch("httpx.AsyncClient.get", return_value=httpx.Response(404, text="not found"))

    with pytest.raises(RepoNotFoundError):
        await get_repo_health("nobody", "doesnt-exist-xyz")


@pytest.mark.asyncio
async def test_primary_rate_limit_detected_via_header(mocker):
    resp = httpx.Response(403, text="rate limited", headers={"X-RateLimit-Remaining": "0"})
    mocker.patch("httpx.AsyncClient.get", return_value=resp)

    with pytest.raises(RateLimitError):
        await get_repo_health("someowner", "somerepo")


@pytest.mark.asyncio
async def test_plain_403_without_rate_limit_header_is_not_misreported(mocker):
    """A 403 for e.g. a private repo should NOT be reported as a rate limit."""
    resp = httpx.Response(403, text="forbidden")  # no X-RateLimit-Remaining header
    mocker.patch("httpx.AsyncClient.get", return_value=resp)

    with pytest.raises(GitHubAPIError):
        await get_repo_health("someowner", "privaterepo")


def test_parse_last_page_count_from_link_header():
    link = '<https://api.github.com/repositories/123/contributors?per_page=1&page=2>; rel="next", <https://api.github.com/repositories/123/contributors?per_page=1&page=87>; rel="last"'
    assert _parse_last_page_count(link) == 87


def test_parse_last_page_count_returns_none_without_link_header():
    assert _parse_last_page_count(None) is None