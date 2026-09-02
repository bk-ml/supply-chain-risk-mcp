"""Client for the GitHub public REST API. Works without auth (60 req/hr);
set GITHUB_TOKEN env var for a higher limit (5,000 req/hr).
"""

import os
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel

GITHUB_API_BASE = "https://api.github.com"


class GitHubClientError(Exception):
    """Base exception for all GitHub client errors."""


class RepoNotFoundError(GitHubClientError):
    """Raised when the repo doesn't exist or isn't public."""


class RateLimitError(GitHubClientError):
    """Raised when GitHub's rate limit is exhausted."""


class GitHubAPIError(GitHubClientError):
    """Raised for any other unexpected API failure."""


class RepoHealth(BaseModel):
    owner: str
    repo: str
    stars: int
    default_branch: str
    last_commit_date: datetime | None
    days_since_last_commit: int | None
    contributor_count: int | None       # None if lookup failed (non-fatal)
    open_issue_count: int               # note: GitHub conflates issues + PRs here
    oldest_open_issue_age_days: int | None


def _build_headers(token: str | None) -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _check_rate_limit(response: httpx.Response) -> None:
    if response.status_code == 429:
        raise RateLimitError("GitHub secondary rate limit hit. Try again shortly.")
    if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
        reset = response.headers.get("X-RateLimit-Reset")
        raise RateLimitError(
            f"GitHub primary rate limit exhausted (resets at unix time {reset}). "
            "Set GITHUB_TOKEN for a higher limit."
        )


def _parse_last_page_count(link_header: str | None) -> int | None:
    """GitHub's Link header's rel="last" page number doubles as a cheap total count
    when per_page=1. Returns None if there's no Link header (i.e. 0 or 1 results)."""
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="last"' in part:
            url_part = part.split(";")[0].strip().strip("<>")
            query = url_part.split("?")[-1]
            for kv in query.split("&"):
                if kv.startswith("page="):
                    return int(kv.split("=")[1])
    return None


async def get_repo_health(owner: str, repo: str, token: str | None = None) -> RepoHealth:
    """Fetch repo activity/health signals: last commit age, contributor count,
    star count, and open issue backlog age.

    Raises:
        RepoNotFoundError: repo doesn't exist or isn't public.
        RateLimitError: GitHub rate limit hit on the core repo lookup.
        GitHubAPIError: any other unexpected failure on the core repo lookup.
    """
    token = token or os.environ.get("GITHUB_TOKEN")
    headers = _build_headers(token)

    async with httpx.AsyncClient(timeout=10.0, headers=headers, follow_redirects=True) as client:
        try:
            repo_resp = await client.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}")
        except httpx.TimeoutException as e:
            raise GitHubAPIError(f"Request to GitHub timed out: {e}") from e
        except httpx.RequestError as e:
            raise GitHubAPIError(f"Network error contacting GitHub: {e}") from e

        _check_rate_limit(repo_resp)
        
        if repo_resp.status_code == 404:
            raise RepoNotFoundError(f"{owner}/{repo} not found or not public")
        if repo_resp.status_code >= 400:
            raise GitHubAPIError(f"GitHub returned status {repo_resp.status_code}: {repo_resp.text}")
        if repo_resp.status_code >= 300:
            raise GitHubAPIError(
                f"Unexpected status {repo_resp.status_code} for {owner}/{repo} "
                f"(after redirect handling): {repo_resp.text}"
            )

        repo_data = repo_resp.json()

        pushed_at_raw = repo_data.get("pushed_at")
        last_commit_date = (
            datetime.fromisoformat(pushed_at_raw.replace("Z", "+00:00")) if pushed_at_raw else None
        )
        days_since_last_commit = (
            (datetime.now(timezone.utc) - last_commit_date).days if last_commit_date else None
        )

        # Contributor count — non-fatal if it fails
        contributor_count = None
        try:
            contrib_resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contributors",
                params={"per_page": 1, "anon": "true"},
            )
            if contrib_resp.status_code == 200:
                link_count = _parse_last_page_count(contrib_resp.headers.get("Link"))
                contributor_count = link_count if link_count is not None else len(contrib_resp.json())
        except httpx.RequestError:
            pass

        # Oldest open issue age — non-fatal if it fails
        oldest_open_issue_age_days = None
        try:
            issues_resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues",
                params={"state": "open", "sort": "created", "direction": "asc", "per_page": 1},
            )
            if issues_resp.status_code == 200:
                issues = issues_resp.json()
                if issues:
                    created = datetime.fromisoformat(issues[0]["created_at"].replace("Z", "+00:00"))
                    oldest_open_issue_age_days = (datetime.now(timezone.utc) - created).days
        except httpx.RequestError:
            pass

    return RepoHealth(
        owner=owner,
        repo=repo,
        stars=repo_data.get("stargazers_count", 0),
        default_branch=repo_data.get("default_branch", "main"),
        last_commit_date=last_commit_date,
        days_since_last_commit=days_since_last_commit,
        contributor_count=contributor_count,
        open_issue_count=repo_data.get("open_issues_count", 0),
        oldest_open_issue_age_days=oldest_open_issue_age_days,
    )