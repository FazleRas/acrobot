"""Chunker grouping/budgeting and postprocess noise controls."""

from acrobot.config import BotConfig
from acrobot.diff.chunker import ReviewUnit, build_units, estimate_tokens
from acrobot.diff.parser import Chunk, parse_patch
from acrobot.pipeline.postprocess import postprocess
from acrobot.schemas import Finding

PATCH_TWO_HUNKS = (
    "@@ -1,3 +1,4 @@\n"
    " def f():\n"
    "+    a = 1\n"
    "     return a\n"
    " \n"
    "@@ -10,3 +11,4 @@\n"
    " def g():\n"
    "+    b = 2\n"
    "     return b\n"
    " \n"
)


def _chunk(path: str, content: str, lines: dict[int, str]) -> Chunk:
    return Chunk(path=path, hunk_header="@@ -1 +1 @@", content=content, new_lines=lines)


def _finding(severity: str, confidence: float) -> tuple[Finding, ReviewUnit]:
    finding = Finding(
        path="a.py",
        line=1,
        severity=severity,  # type: ignore[arg-type]
        category="bug",
        confidence=confidence,
        comment="x",
    )
    return finding, ReviewUnit(path="a.py", chunks=[])


class TestBuildUnits:
    def test_same_file_hunks_grouped_into_one_unit(self):
        chunks = parse_patch("a.py", PATCH_TWO_HUNKS)
        assert len(chunks) == 2
        units = build_units(chunks)
        assert len(units) == 1
        assert units[0].path == "a.py"
        # Merged line map spans both hunks.
        assert 2 in units[0].new_lines and 12 in units[0].new_lines

    def test_units_never_span_files(self):
        chunks = parse_patch("a.py", PATCH_TWO_HUNKS) + parse_patch("b.py", PATCH_TWO_HUNKS)
        units = build_units(chunks)
        assert sorted(u.path for u in units) == ["a.py", "b.py"]

    def test_budget_splits_same_file_units(self):
        big = "x" * 300  # ~100 estimated tokens per chunk
        chunks = [_chunk("a.py", big, {i: "line"}) for i in range(1, 5)]
        units = build_units(chunks, max_tokens_per_request=150)
        assert len(units) == 4  # each chunk alone busts the shared budget

    def test_oversized_single_hunk_still_ships_alone(self):
        huge = "x" * 60_000
        units = build_units([_chunk("a.py", huge, {1: "line"})], max_tokens_per_request=100)
        assert len(units) == 1 and len(units[0].chunks) == 1

    def test_estimate_is_conservative_for_code(self):
        code = "def f(x):\n    return x + 1\n"
        assert estimate_tokens(code) >= len(code) // 4  # never undercounts vs ~4 chars/token


class TestPostprocess:
    def test_confidence_and_severity_filters(self):
        config = BotConfig()  # confidence 0.6, floor "warning"
        findings = [
            _finding("critical", 0.9),
            _finding("warning", 0.3),  # below confidence bar
            _finding("nit", 0.9),  # below severity floor
        ]
        kept = postprocess(findings, config)
        assert [f.severity for f, _ in kept] == ["critical"]

    def test_cap_keeps_most_important_not_first_seen(self):
        config = BotConfig(max_comments=2)
        findings = [
            _finding("nit", 0.99),
            _finding("warning", 0.7),
            _finding("critical", 0.65),
            _finding("warning", 0.9),
        ]
        config = config.model_copy(update={"severity_floor": "nit"})
        kept = postprocess(findings, config)
        assert [f.severity for f, _ in kept] == ["critical", "warning"]
        assert kept[1][0].confidence == 0.9

    def test_nit_floor_lets_nits_through(self):
        config = BotConfig(severity_floor="nit")
        kept = postprocess([_finding("nit", 0.9)], config)
        assert len(kept) == 1
