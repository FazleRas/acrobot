"""Minimal GitHub REST client: auth, pagination, retries.

Deliberately hand-rolled over httpx instead of PyGithub — the bot only needs
four endpoints, and owning pagination/retry keeps the dependency surface small.
"""

import time
from collections.abc import Iterator
from typing import Any

import httpx


class GitHubClient:
    def __init__(self, token: str, repo: str, base_url: str = "https://api.github.com") -> None:
        """`repo` is the full name, e.g. "FazleRas/AlphaLab"."""
        self._repo = repo
        self._http = httpx.Client(
            base_url=f"{base_url}/repos/{repo}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    def _request(
        self, method: str, path: str, *, retries: int = 3, **kwargs: Any
    ) -> httpx.Response:
        for attempt in range(retries + 1):
            response = self._http.request(method, path, **kwargs)
            if response.status_code in (429, 502, 503) and attempt < retries:
                retry_after = float(response.headers.get("retry-after", 2**attempt))
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            return response
        raise RuntimeError("unreachable")

    def get(self, path: str, **params: Any) -> Any:
        return self._request("GET", path, params=params).json()

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", path, json=payload).json()

    def paginate(self, path: str, **params: Any) -> Iterator[dict[str, Any]]:
        """Follow RFC 5988 Link headers until the last page."""
        params.setdefault("per_page", 100)
        response = self._request("GET", path, params=params)
        while True:
            yield from response.json()
            next_url = response.links.get("next", {}).get("url")
            if not next_url:
                return
            response = self._request("GET", next_url)
