"""Triage gate: threshold routing and — critically — fail-open semantics."""

import pytest
from pydantic import BaseModel

from acrobot.diff.chunker import build_units
from acrobot.diff.parser import parse_patch
from acrobot.llm.provider import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponse,
    Usage,
)
from acrobot.pipeline.triage import triage
from acrobot.ratelimit import RateLimiter
from acrobot.schemas import TriageResult

PATCH = (
    "@@ -1,2 +1,3 @@\n"
    " def f():\n"
    "+    x = 1\n"
    "     return None\n"
)


def _units(count: int):
    units = []
    for i in range(count):
        units.extend(build_units(parse_patch(f"file_{i}.py", PATCH)))
    return units


def _limiter(rpd: int = 100) -> RateLimiter:
    return RateLimiter(rpm=1000, rpd=rpd, clock=lambda: 0.0, sleep=lambda s: None)


class ScoringProvider:
    """Returns scripted scores in order; records the reasoning flag."""

    def __init__(self, scores: list[int]) -> None:
        self._scores = iter(scores)
        self.calls = 0
        self.reasoning_flags: list[bool] = []

    def generate(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        schema: type[BaseModel],
        reasoning: bool = False,
    ) -> ProviderResponse:
        assert schema is TriageResult
        self.calls += 1
        self.reasoning_flags.append(reasoning)
        return ProviderResponse(
            parsed=TriageResult(score=next(self._scores)), usage=Usage(), model=model
        )


class FailingProvider:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls = 0

    def generate(self, **kwargs):  # noqa: ANN003
        self.calls += 1
        raise self._exc


class TestTriageRouting:
    def test_threshold_splits_kept_and_skipped(self):
        provider = ScoringProvider(scores=[8, 2, 4])
        outcome = triage(provider, _limiter(), "lite", _units(3), threshold=4)
        assert [u.path for u in outcome.kept] == ["file_0.py", "file_2.py"]
        assert [(u.path, s) for u, s in outcome.skipped] == [("file_1.py", 2)]

    def test_triage_never_uses_reasoning(self):
        provider = ScoringProvider(scores=[5])
        triage(provider, _limiter(), "lite", _units(1), threshold=4)
        assert provider.reasoning_flags == [False]

    def test_threshold_zero_disables_triage_entirely(self):
        provider = ScoringProvider(scores=[])
        outcome = triage(provider, _limiter(), "lite", _units(2), threshold=0)
        assert provider.calls == 0
        assert len(outcome.kept) == 2


class TestTriageFailsOpen:
    def test_provider_error_keeps_unit(self):
        provider = FailingProvider(ProviderError("boom"))
        outcome = triage(provider, _limiter(), "lite", _units(2), threshold=4)
        assert len(outcome.kept) == 2
        assert outcome.errored == 2

    def test_per_minute_rate_limit_keeps_unit(self):
        provider = FailingProvider(
            ProviderRateLimitError("q", retry_after=8.0, is_daily=False)
        )
        outcome = triage(provider, _limiter(), "lite", _units(1), threshold=4)
        assert len(outcome.kept) == 1
        assert outcome.errored == 1

    def test_daily_rate_limit_fails_open_for_rest_without_more_calls(self):
        provider = FailingProvider(
            ProviderRateLimitError("q", retry_after=1.0, is_daily=True)
        )
        outcome = triage(provider, _limiter(), "lite", _units(3), threshold=4)
        assert provider.calls == 1  # stopped calling after the daily signal
        assert len(outcome.kept) == 3  # every unit still reaches review

    def test_local_budget_exhaustion_fails_open_for_rest(self):
        provider = ScoringProvider(scores=[9, 9, 9])
        outcome = triage(provider, _limiter(rpd=1), "lite", _units(3), threshold=4)
        assert provider.calls == 1
        assert len(outcome.kept) == 3

    def test_auth_error_propagates_not_swallowed(self):
        provider = FailingProvider(ProviderAuthError("dead key"))
        with pytest.raises(ProviderAuthError):
            triage(provider, _limiter(), "lite", _units(1), threshold=4)
