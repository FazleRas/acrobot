"""GitHub client retry policy and degraded-run review posting."""

import httpx

from acrobot.github.client import GitHubClient
from acrobot.github.reviews import post_review


class _Sequence:
    """MockTransport handler that serves canned responses in order and
    records every request it saw."""

    def __init__(self, *responses: httpx.Response) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responses.pop(0)


def _client(seq: _Sequence, sleeps: list[float]) -> GitHubClient:
    return GitHubClient(
        token="t", repo="o/r", transport=httpx.MockTransport(seq), sleep=sleeps.append
    )


class TestRetryPolicy:
    def test_retries_5xx_then_succeeds(self):
        seq = _Sequence(
            httpx.Response(500), httpx.Response(504), httpx.Response(200, json={"ok": 1})
        )
        sleeps: list[float] = []
        assert _client(seq, sleeps).get("/x") == {"ok": 1}
        assert len(seq.requests) == 3
        assert sleeps == [1.0, 2.0]  # exponential backoff when no retry-after

    def test_403_with_retry_after_is_secondary_rate_limit(self):
        seq = _Sequence(
            httpx.Response(403, headers={"retry-after": "7"}), httpx.Response(200, json=[])
        )
        sleeps: list[float] = []
        assert _client(seq, sleeps).get("/x") == []
        assert sleeps == [7.0]

    def test_plain_403_is_not_retried(self):
        seq = _Sequence(httpx.Response(403, json={"message": "forbidden"}))
        sleeps: list[float] = []
        try:
            _client(seq, sleeps).get("/x")
        except httpx.HTTPStatusError as exc:
            assert exc.response.status_code == 403
        else:
            raise AssertionError("expected HTTPStatusError")
        assert len(seq.requests) == 1
        assert sleeps == []

    def test_retry_after_is_capped(self):
        seq = _Sequence(
            httpx.Response(429, headers={"retry-after": "3600"}), httpx.Response(200, json={})
        )
        sleeps: list[float] = []
        _client(seq, sleeps).get("/x")
        assert sleeps == [60.0]


class TestPostReviewDegraded:
    def _post(self, comments: list, degraded: bool) -> list[httpx.Request]:
        seq = _Sequence(httpx.Response(200, json={"id": 1}))
        post_review(_client(seq, []), 1, "sha", "summary", comments, degraded=degraded)
        return seq.requests

    def test_clean_run_with_no_findings_stays_silent(self):
        assert self._post([], degraded=False) == []

    def test_degraded_run_posts_summary_even_without_comments(self):
        requests = self._post([], degraded=True)
        assert len(requests) == 1
        assert b'"comments": []' in requests[0].content or b'"comments":[]' in requests[0].content
