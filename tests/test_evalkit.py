"""The eval harness machinery: matching, scoring buckets, cassette record/replay."""

import pytest

from acrobot.evalkit.cases import EvalCase, ExpectedFinding
from acrobot.evalkit.cassette import CassetteMiss, CassetteProvider
from acrobot.evalkit.scoring import matches, score
from acrobot.llm.provider import ProviderResponse, Usage
from acrobot.schemas import Finding, FindingList


def _finding(path="a.py", line=10, category="bug", comment="off-by-one in window") -> Finding:
    return Finding(
        path=path, line=line, severity="warning", category=category,  # type: ignore[arg-type]
        confidence=0.9, comment=comment,
    )


def _expected(**overrides) -> ExpectedFinding:
    base = {"path": "a.py", "line": 10, "line_tolerance": 2}
    return ExpectedFinding(**{**base, **overrides})


class TestMatching:
    def test_line_tolerance_is_inclusive(self):
        assert matches(_expected(), _finding(line=12))
        assert not matches(_expected(), _finding(line=13))

    def test_category_none_matches_any(self):
        assert matches(_expected(category=None), _finding(category="security"))
        assert not matches(_expected(category="bug"), _finding(category="security"))

    def test_must_mention_is_any_of_case_insensitive(self):
        expected = _expected(must_mention=["Off-By-One", "window"])
        assert matches(expected, _finding(comment="classic OFF-BY-ONE here"))
        assert not matches(expected, _finding(comment="uses eval(), dangerous"))

    def test_wrong_path_never_matches(self):
        assert not matches(_expected(path="b.py"), _finding(path="a.py"))


class TestScoring:
    def _case(self, expected=None, clean=None) -> EvalCase:
        return EvalCase(
            name="t", fixture="f.json",
            expected_findings=expected or [], clean_files=clean or [],
        )

    def test_buckets(self):
        case = self._case(
            expected=[_expected(line=10), _expected(line=50)],
            clean=["docs.md"],
        )
        findings = [
            _finding(line=11),                      # tp (within tolerance of 10)
            _finding(path="docs.md", line=3),       # fp (clean file)
            _finding(path="other.py", line=7),      # extra (unlabeled)
        ]
        result = score(case, findings)
        assert len(result.tp) == 1
        assert len(result.fn) == 1 and result.fn[0].line == 50
        assert len(result.fp) == 1
        assert len(result.extra) == 1
        assert result.recall == 0.5

    def test_greedy_one_to_one(self):
        # Two identical labels, one finding: exactly one tp, one fn.
        case = self._case(expected=[_expected(), _expected()])
        result = score(case, [_finding()])
        assert len(result.tp) == 1 and len(result.fn) == 1

    def test_recall_none_when_no_labels(self):
        result = score(self._case(clean=["a.md"]), [])
        assert result.recall is None


class _CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, model, system, prompt, schema, reasoning=False):  # noqa: ANN001, ANN003
        self.calls += 1
        return ProviderResponse(
            parsed=FindingList(findings=[_finding()]),
            usage=Usage(input_tokens=10, output_tokens=5),
            model=model,
        )


class TestCassette:
    def test_record_then_strict_replay_roundtrip(self, tmp_path):
        path = tmp_path / "case.json"
        inner = _CountingProvider()
        recorder = CassetteProvider(path, inner=inner)
        first = recorder.generate(
            model="m", system="s", prompt="p", schema=FindingList, reasoning=True
        )
        recorder.save()
        assert recorder.recorded == 1

        replayer = CassetteProvider(path)  # no inner: strict replay
        replayed = replayer.generate(
            model="m", system="s", prompt="p", schema=FindingList, reasoning=True
        )
        assert replayer.replayed == 1
        assert replayed.parsed == first.parsed
        assert replayed.usage.input_tokens == 10

    def test_prompt_change_raises_cassette_miss(self, tmp_path):
        path = tmp_path / "case.json"
        recorder = CassetteProvider(path, inner=_CountingProvider())
        recorder.generate(model="m", system="s", prompt="old", schema=FindingList)
        recorder.save()

        replayer = CassetteProvider(path)
        with pytest.raises(CassetteMiss, match="Re-record"):
            replayer.generate(model="m", system="s", prompt="NEW", schema=FindingList)

    def test_empty_cassette_file_is_treated_as_empty(self, tmp_path):
        # Both findings from the bot's own review of this harness (PR #10):
        # an existing-but-empty file must not crash on load...
        path = tmp_path / "case.json"
        path.write_text("")
        provider = CassetteProvider(path, inner=_CountingProvider())
        provider.generate(model="m", system="s", prompt="p", schema=FindingList)
        assert provider.recorded == 1

    def test_field_boundaries_cannot_collide(self, tmp_path):
        # ...and a separator character inside one field must not make two
        # different requests share a cassette key.
        path = tmp_path / "case.json"
        recorder = CassetteProvider(path, inner=_CountingProvider())
        recorder.generate(model="m", system="a", prompt="b\x00c", schema=FindingList)
        recorder.save()

        replayer = CassetteProvider(path)  # strict replay
        with pytest.raises(CassetteMiss):
            replayer.generate(model="m", system="a\x00b", prompt="c", schema=FindingList)

    def test_rerecord_replays_hits_without_spending(self, tmp_path):
        path = tmp_path / "case.json"
        inner = _CountingProvider()
        recorder = CassetteProvider(path, inner=inner)
        recorder.generate(model="m", system="s", prompt="p", schema=FindingList)
        recorder.save()
        assert inner.calls == 1

        rerecord = CassetteProvider(path, inner=inner)
        rerecord.generate(model="m", system="s", prompt="p", schema=FindingList)
        assert rerecord.replayed == 1
        assert inner.calls == 1  # hit replayed even in live mode — no new spend
