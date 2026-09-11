"""Minimal GitHub REST client: auth, pagination, retries.

Deliberately hand-rolled over httpx instead of PyGithub — the bot only needs
four endpoints, and owning pagination/retry keeps the dependency surface small.
"""

import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

# Transient statuses worth a retry. 403 is included only when GitHub marks it
# as a secondary rate limit (retry-after header) — a plain 403 is a permissions
# error and retrying it just burns time.
_RETRY_STATUSES = {429, 500, 502, 503, 504}
# Cap the honored retry-after so a large header value can't wedge a CI job.
_MAX_RETRY_SLEEP = 60.0


class GitHubClient:
    def __init__(
        self,
        token: str,
        repo: str,
        base_url: str = "https://api.github.com",
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """`repo` is the full name, e.g. "FazleRas/AlphaLab". `transport` and
        `sleep` are injection seams for tests."""
        self._repo = repo
        self._sleep = sleep
        self._http = httpx.Client(
            transport=transport,
            base_url=f"{base_url}/repos/{repo}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    @staticmethod
    def _should_retry(response: httpx.Response) -> bool:
        if response.status_code in _RETRY_STATUSES:
            return True
        return response.status_code == 403 and "retry-after" in response.headers

    def _request(
        self, method: str, path: str, *, retries: int = 3, **kwargs: Any
    ) -> httpx.Response:
        for attempt in range(retries + 1):
            response = self._http.request(method, path, **kwargs)
            if attempt < retries and self._should_retry(response):
                retry_after = float(response.headers.get("retry-after", 2**attempt))
                self._sleep(min(retry_after, _MAX_RETRY_SLEEP))
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
