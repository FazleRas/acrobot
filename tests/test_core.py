"""Tests for the implemented core: fingerprints, diff parsing, filters, rate limiter."""

import pytest

from acrobot.config import BotConfig
from acrobot.diff.filters import should_review
from acrobot.diff.parser import parse_patch
from acrobot.pipeline.fingerprint import extract_fingerprints, fingerprint, marker
from acrobot.ratelimit import DailyBudgetExhausted, RateLimiter

SAMPLE_PATCH = (
    "@@ -1,4 +1,5 @@\n"
    " def sharpe(returns):\n"
    "-    return returns.mean() / returns.std()\n"
    "+    ann = returns.mean() * 252\n"
    "+    return ann / (returns.std() * 252 ** 0.5)\n"
    " \n"
)


class TestFingerprint:
    def test_stable_across_line_shifts(self):
        # Same content, same category → same fingerprint regardless of position.
        assert fingerprint("a.py", "  x = 1  ", "bug") == fingerprint("a.py", "x = 1", "bug")

    def test_distinct_inputs_distinct_fingerprints(self):
        base = fingerprint("a.py", "x = 1", "bug")
        assert fingerprint("b.py", "x = 1", "bug") != base
        assert fingerprint("a.py", "x = 2", "bug") != base
        assert fingerprint("a.py", "x = 1", "security") != base

    def test_roundtrip_through_comment_marker(self):
        fp = fingerprint("a.py", "x = 1", "bug")
        body = f"Looks like an off-by-one.\n\n{marker(fp)}"
        assert extract_fingerprints([body, "no marker here"]) == {fp}


class TestParsePatch:
    def test_wraps_github_patch_and_maps_new_lines(self):
        chunks = parse_patch("strategies/momentum.py", SAMPLE_PATCH)
        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.path == "strategies/momentum.py"
        # Added lines land at their new-file line numbers.
        assert chunk.new_lines[2] == "    ann = returns.mean() * 252"
        assert chunk.new_lines[3] == "    return ann / (returns.std() * 252 ** 0.5)"
        # Removed lines never appear on side RIGHT.
        assert all("returns.mean() / returns.std()" not in v for v in chunk.new_lines.values())

    def test_lines_for_range(self):
        chunk = parse_patch("a.py", SAMPLE_PATCH)[0]
        assert "ann = returns.mean() * 252" in chunk.lines_for(2, 3)


class TestFilters:
    def test_skips_lockfiles_removed_and_binary(self):
        config = BotConfig()
        assert not should_review("uv.lock", "modified", "@@ -1 +1 @@", config)
        assert not should_review("src/app.py", "removed", "@@ -1 +0,0 @@", config)
        assert not should_review("logo.png", "modified", None, config)
        assert not should_review("dist/bundle.min.js", "modified", "@@ -1 +1 @@", config)

    def test_reviews_normal_source_change(self):
        assert should_review("src/app.py", "modified", SAMPLE_PATCH, BotConfig())


class TestRateLimiter:
    def test_rpd_exhaustion_raises(self):
        limiter = RateLimiter(rpm=100, rpd=2, clock=lambda: 0.0, sleep=lambda s: None)
        limiter.acquire()
        limiter.acquire()
        with pytest.raises(DailyBudgetExhausted):
            limiter.acquire()

    def test_rpm_window_blocks_then_frees(self):
        now = {"t": 0.0}
        slept: list[float] = []

        def sleep(seconds: float) -> None:
            slept.append(seconds)
            now["t"] += seconds

        limiter = RateLimiter(rpm=2, rpd=100, clock=lambda: now["t"], sleep=sleep)
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()  # third call must wait for the window to roll
        assert slept and slept[0] == pytest.approx(60.0)
        assert limiter.remaining_today == 97
