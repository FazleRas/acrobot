"""Cheap-model pass: score each unit for review-worthiness before the
expensive model spends rate-limit budget on it."""

from reviewbot.diff.chunker import ReviewUnit
from reviewbot.llm.provider import Provider
from reviewbot.ratelimit import RateLimiter


def triage(provider: Provider, limiter: RateLimiter, model: str,
           units: list[ReviewUnit], threshold: int) -> list[ReviewUnit]:
    raise NotImplementedError("weekend 4")
