"""Cheap-model pass: score each unit for review-worthiness before the
expensive model spends rate-limit budget on it."""

from acrobot.diff.chunker import ReviewUnit
from acrobot.llm.provider import Provider
from acrobot.ratelimit import RateLimiter


def triage(provider: Provider, limiter: RateLimiter, model: str,
           units: list[ReviewUnit], threshold: int) -> list[ReviewUnit]:
    raise NotImplementedError("weekend 4")
