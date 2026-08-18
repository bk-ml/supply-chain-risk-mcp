"""Client for the deps.dev API (Google). No auth required.

API docs: https://docs.deps.dev/api/v3/
"""

from urllib.parse import quote

import httpx
from pydantic import BaseModel

DEPS_DEV_BASE = "https://api.deps.dev/v3"

# Dependency graphs are only available for these ecosystems (per deps.dev docs)
SUPPORTED_ECOSYSTEMS = {"NPM", "CARGO", "MAVEN", "PYPI"}


class DepsDevClientError(Exception):
    """Base exception for all deps.dev client errors."""


class PackageNotFoundError(DepsDevClientError):
    """Raised when the package/version combination doesn't exist."""


class RateLimitError(DepsDevClientError):
    """Raised when deps.dev returns a 429."""


class UnsupportedEcosystemError(DepsDevClientError):
    """Raised when the ecosystem doesn't support dependency graph queries."""


class DepsDevAPIError(DepsDevClientError):
    """Raised for any other unexpected API failure."""


class DependencyNode(BaseModel):
    system: str
    name: str
    version: str
    bundled: bool = False


class DependencyGraphResult(BaseModel):
    system: str
    name: str
    version: str
    nodes: list[DependencyNode]

    @property
    def dependency_count(self) -> int:
        # subtract 1: the first node is always the root package itself
        return max(len(self.nodes) - 1, 0)


async def get_dependency_graph(
    system: str, name: str, version: str
) -> DependencyGraphResult:
    """Fetch the resolved dependency graph for a package version from deps.dev.

    Raises:
        UnsupportedEcosystemError: ecosystem doesn't support dependency graphs.
        PackageNotFoundError: no such package/version.
        RateLimitError: deps.dev rate limit hit.
        DepsDevAPIError: any other unexpected failure.
    """
    system_upper = system.upper()
    if system_upper not in SUPPORTED_ECOSYSTEMS:
        raise UnsupportedEcosystemError(
            f"deps.dev dependency graphs aren't available for '{system}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_ECOSYSTEMS))}"
        )

    # Package names can contain slashes (e.g. @colors/colors) so must be URL-encoded
    encoded_name = quote(name, safe="")
    encoded_version = quote(version, safe="")
    url = (
        f"{DEPS_DEV_BASE}/systems/{system_upper}/packages/{encoded_name}"
        f"/versions/{encoded_version}:dependencies"
    )

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url)
        except httpx.TimeoutException as e:
            raise DepsDevAPIError(f"Request to deps.dev timed out: {e}") from e
        except httpx.RequestError as e:
            raise DepsDevAPIError(f"Network error contacting deps.dev: {e}") from e

    if response.status_code == 404:
        raise PackageNotFoundError(f"{system}/{name}@{version} not found on deps.dev")
    if response.status_code == 429:
        raise RateLimitError("deps.dev rate limit exceeded. Try again shortly.")
    if response.status_code >= 400:
        raise DepsDevAPIError(f"deps.dev returned status {response.status_code}: {response.text}")

    data = response.json()
    raw_nodes = data.get("nodes", [])

    nodes = [
        DependencyNode(
            system=n["versionKey"]["system"],
            name=n["versionKey"]["name"],
            version=n["versionKey"]["version"],
            bundled=n.get("bundled", False),
        )
        for n in raw_nodes
    ]

    return DependencyGraphResult(system=system_upper, name=name, version=version, nodes=nodes)


class PackageVersionInfo(BaseModel):
    system: str
    name: str
    version: str
    license: str | None   # raw SPDX string/expression as returned by deps.dev, may be None


async def get_version_info(system: str, name: str, version: str) -> PackageVersionInfo:
    """Fetch metadata for a specific package version, primarily for its license.

    Raises:
        PackageNotFoundError: no such package/version.
        RateLimitError: deps.dev rate limit hit.
        DepsDevAPIError: any other unexpected failure.
    """
    system_upper = system.upper()
    encoded_name = quote(name, safe="")
    encoded_version = quote(version, safe="")
    url = f"{DEPS_DEV_BASE}/systems/{system_upper}/packages/{encoded_name}/versions/{encoded_version}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url)
        except httpx.TimeoutException as e:
            raise DepsDevAPIError(f"Request to deps.dev timed out: {e}") from e
        except httpx.RequestError as e:
            raise DepsDevAPIError(f"Network error contacting deps.dev: {e}") from e

    if response.status_code == 404:
        raise PackageNotFoundError(f"{system}/{name}@{version} not found on deps.dev")
    if response.status_code == 429:
        raise RateLimitError("deps.dev rate limit exceeded. Try again shortly.")
    if response.status_code >= 400:
        raise DepsDevAPIError(f"deps.dev returned status {response.status_code}: {response.text}")

    data = response.json()
    licenses = data.get("licenses", [])
    license_str = " OR ".join(licenses) if licenses else None

    return PackageVersionInfo(system=system_upper, name=name, version=version, license=license_str)