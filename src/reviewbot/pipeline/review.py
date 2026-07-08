"""Review pass: reasoning-enabled model emits structured Findings per unit.

A unit is one file with one or more of its hunks (see diff/chunker.py).
Each finding stays paired with the unit it came from — downstream anchor
validation and fingerprinting need the unit's merged line map, and we never
trust the model to report its own file path.
"""

import time
from dataclasses import dataclass, field
from importlib.resources import files

from reviewbot.diff.chunker import ReviewUnit
from reviewbot.llm.provider import Provider, ProviderError
from reviewbot.ratelimit import DailyBudgetExhausted, RateLimiter
from reviewbot.schemas import Finding, FindingList
from reviewbot.telemetry import RunTelemetry


@dataclass
class ReviewOutcome:
    findings: list[tuple[Finding, ReviewUnit]] = field(default_factory=list)
    units_reviewed: int = 0
    units_errored: int = 0
    budget_exhausted: bool = False


def _system_prompt() -> str:
    return files("reviewbot.llm.prompts").joinpath("review_system.md").read_text()


def _user_prompt(unit: ReviewUnit) -> str:
    # The numbered new-file listing is what keeps anchors honest: the model
    # cites these numbers instead of counting diff lines itself.
    sections = []
    for chunk in unit.chunks:
        numbered = "\n".join(f"{n:>5} | {text}" for n, text in sorted(chunk.new_lines.items()))
        sections.append(
            f"Hunk `{chunk.hunk_header}`:\n```diff\n{chunk.content}```\n\n"
            f"New-file line numbers you may anchor findings to:\n```\n{numbered}\n```"
        )
    return f"File: `{unit.path}`\n\n" + "\n\n".join(sections)


def review(
    provider: Provider,
    limiter: RateLimiter,
    model: str,
    units: list[ReviewUnit],
    telemetry: RunTelemetry | None = None,
) -> ReviewOutcome:
    outcome = ReviewOutcome()
    system = _system_prompt()
    for unit in units:
        try:
            limiter.acquire()
        except DailyBudgetExhausted:
            outcome.budget_exhausted = True
            break
        started = time.monotonic()
        try:
            response = provider.generate(
                model=model,
                system=system,
                prompt=_user_prompt(unit),
                schema=FindingList,
                reasoning=True,
            )
        except ProviderError as exc:
            print(f"reviewbot: provider error on {unit.path}: {exc}")
            outcome.units_errored += 1
            continue
        if telemetry is not None:
            telemetry.record("review", model, response.usage, time.monotonic() - started)
        outcome.units_reviewed += 1
        for finding in response.parsed.findings:
            finding.path = unit.path  # pipeline knows the path; the model doesn't get a vote
            outcome.findings.append((finding, unit))
    return outcome
