"""Review pass + comment building, exercised with a fake provider."""

from pydantic import BaseModel

from acrobot.diff.chunker import build_units
from acrobot.diff.parser import parse_patch
from acrobot.github.reviews import build_comments
from acrobot.llm.provider import ProviderResponse, Usage
from acrobot.pipeline.fingerprint import extract_fingerprints
from acrobot.pipeline.review import review
from acrobot.ratelimit import RateLimiter
from acrobot.schemas import Finding, FindingList

PATCH = (
    "@@ -1,4 +1,5 @@\n"
    " def sharpe(returns):\n"
    "-    return returns.mean() / returns.std()\n"
    "+    ann = returns.mean() * 252\n"
    "+    return ann / (returns.std() * 252 ** 0.5)\n"
    " \n"
)


def _finding(line: int, end_line: int | None = None, category: str = "bug") -> Finding:
    return Finding(
        path="ignored-by-pipeline.py",
        line=line,
        end_line=end_line,
        severity="warning",
        category=category,  # type: ignore[arg-type]
        confidence=0.8,
        comment="Annualization factor applied twice.",
    )


class FakeProvider:
    """Returns one canned finding per call; counts calls."""

    def __init__(self, findings: list[Finding] | None = None) -> None:
        self.calls = 0
        self._findings = findings if findings is not None else [_finding(line=3)]

    def generate(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        schema: type[BaseModel],
        reasoning: bool = False,
    ) -> ProviderResponse:
        assert schema is FindingList
        self.calls += 1
        return ProviderResponse(
            parsed=FindingList(findings=list(self._findings)),
            usage=Usage(input_tokens=100, output_tokens=50, thinking_tokens=20),
            model=model,
        )


def _limiter(rpd: int = 100) -> RateLimiter:
    return RateLimiter(rpm=1000, rpd=rpd, clock=lambda: 0.0, sleep=lambda s: None)


class AuthFailProvider:
    def generate(self, **kwargs):  # noqa: ANN003
        from acrobot.llm.provider import ProviderAuthError

        raise ProviderAuthError("bad key")


class TestReviewPass:
    def test_auth_error_aborts_run_not_swallowed(self):
        import pytest

        from acrobot.llm.provider import ProviderAuthError

        units = build_units(parse_patch("a.py", PATCH))
        with pytest.raises(ProviderAuthError):
            review(AuthFailProvider(), _limiter(), "fake-model", units)

    def test_pairs_findings_with_chunks_and_owns_path(self):
        units = build_units(parse_patch("strategies/momentum.py", PATCH))
        outcome = review(FakeProvider(), _limiter(), "fake-model", units)
        assert outcome.units_reviewed == 1
        finding, unit = outcome.findings[0]
        # The model's self-reported path is overridden by the pipeline.
        assert finding.path == "strategies/momentum.py"
        assert unit.path == "strategies/momentum.py"

    def test_budget_exhaustion_stops_cleanly_mid_run(self):
        units = build_units(parse_patch("a.py", PATCH) + parse_patch("b.py", PATCH))
        provider = FakeProvider()
        outcome = review(provider, _limiter(rpd=1), "fake-model", units)
        assert provider.calls == 1
        assert outcome.units_reviewed == 1
        assert outcome.budget_exhausted is True
        assert len(outcome.findings) == 1  # partial results survive


class TestBuildComments:
    def _paired(self, finding: Finding):
        unit = build_units(parse_patch("strategies/momentum.py", PATCH))[0]
        return [(finding, unit)]

    def test_valid_anchor_becomes_comment_with_marker(self):
        comments = build_comments(self._paired(_finding(line=2)))
        assert len(comments) == 1
        assert comments[0]["side"] == "RIGHT"
        assert comments[0]["line"] == 2
        assert "start_line" not in comments[0]
        assert extract_fingerprints([comments[0]["body"]])  # marker embedded

    def test_hallucinated_line_dropped_not_fatal(self):
        comments = build_comments(self._paired(_finding(line=999)))
        assert comments == []

    def test_multiline_uses_start_line(self):
        comments = build_comments(self._paired(_finding(line=2, end_line=3)))
        assert comments[0]["start_line"] == 2
        assert comments[0]["line"] == 3

    def test_existing_fingerprint_skipped(self):
        first = build_comments(self._paired(_finding(line=2)))
        already_posted = extract_fingerprints([first[0]["body"]])
        rerun = build_comments(self._paired(_finding(line=2)), already_posted)
        assert rerun == []

    def test_duplicate_findings_in_same_run_deduped(self):
        unit = build_units(parse_patch("strategies/momentum.py", PATCH))[0]
        pairs = [(_finding(line=2), unit), (_finding(line=2), unit)]
        assert len(build_comments(pairs)) == 1
