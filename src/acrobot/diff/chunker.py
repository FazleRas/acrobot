"""Group parsed hunks into per-file review units under a token budget.

Grouping same-file hunks into one request does two jobs at once: the review
model sees related changes together (fewer blind-spot false positives — a
finding answered by a sibling hunk is visible now), and big PRs consume fewer
requests from the free-tier daily budget.

Units never span files: keeping one file per request preserves the invariant
that the pipeline — not the model — owns the file path a finding lands on.

Token counts are a deterministic character-based estimate. The provider's
real tokenizer would cost an API request per measurement, and requests are
exactly the resource being conserved — so we overestimate locally instead
(~3 chars/token is conservative for code).
"""

from dataclasses import dataclass
from functools import cached_property

from acrobot.diff.parser import Chunk


def estimate_tokens(text: str) -> int:
    return len(text) // 3 + 1


@dataclass
class ReviewUnit:
    """One review request: one file, one or more of its hunks."""

    path: str
    chunks: list[Chunk]

    @cached_property
    def new_lines(self) -> dict[int, str]:
        """Merged new-file line map across all hunks (line numbers are unique
        within a file, so plain dict union is safe)."""
        merged: dict[int, str] = {}
        for chunk in self.chunks:
            merged.update(chunk.new_lines)
        return merged

    def lines_for(self, start: int, end: int | None = None) -> str:
        end = end or start
        return "\n".join(self.new_lines[n] for n in range(start, end + 1) if n in self.new_lines)


def build_units(chunks: list[Chunk], max_tokens_per_request: int = 8000) -> list[ReviewUnit]:
    """Pack each file's hunks into as few units as fit the budget.

    A single hunk larger than the budget still ships alone — the file-size
    filter upstream bounds the worst case, and a too-big request degrades to
    a provider error for that unit, not a crash.
    """
    by_path: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        by_path.setdefault(chunk.path, []).append(chunk)

    units: list[ReviewUnit] = []
    for path, file_chunks in by_path.items():
        current: list[Chunk] = []
        current_tokens = 0
        for chunk in file_chunks:
            cost = estimate_tokens(chunk.content)
            if current and current_tokens + cost > max_tokens_per_request:
                units.append(ReviewUnit(path=path, chunks=current))
                current, current_tokens = [], 0
            current.append(chunk)
            current_tokens += cost
        units.append(ReviewUnit(path=path, chunks=current))
    return units
