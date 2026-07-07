"""Review pass: reasoning-enabled model emits structured Findings per chunk.

Each finding stays paired with the chunk it came from — downstream anchor
validation and fingerprinting need the chunk's new-file line map, and we never
trust the model to report its own file path.
"""

import time
from dataclasses import dataclass, field
from importlib.resources import files

from reviewbot.diff.parser import Chunk
from reviewbot.llm.provider import Provider, ProviderError
from reviewbot.ratelimit import DailyBudgetExhausted, RateLimiter
from reviewbot.schemas import Finding, FindingList
from reviewbot.telemetry import RunTelemetry


@dataclass
class ReviewOutcome:
    findings: list[tuple[Finding, Chunk]] = field(default_factory=list)
    chunks_reviewed: int = 0
    chunks_errored: int = 0
    budget_exhausted: bool = False


def _system_prompt() -> str:
    return files("reviewbot.llm.prompts").joinpath("review_system.md").read_text()


def _user_prompt(chunk: Chunk) -> str:
    # The numbered new-file listing is what keeps anchors honest: the model
    # cites these numbers instead of counting diff lines itself.
    numbered = "\n".join(f"{n:>5} | {text}" for n, text in sorted(chunk.new_lines.items()))
    return (
        f"File: `{chunk.path}`\n\n"
        f"Diff hunk:\n```diff\n{chunk.content}```\n\n"
        f"New-file line numbers you may anchor findings to:\n"
        f"```\n{numbered}\n```"
    )


def review(
    provider: Provider,
    limiter: RateLimiter,
    model: str,
    chunks: list[Chunk],
    telemetry: RunTelemetry | None = None,
) -> ReviewOutcome:
    outcome = ReviewOutcome()
    system = _system_prompt()
    for chunk in chunks:
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
                prompt=_user_prompt(chunk),
                schema=FindingList,
                reasoning=True,
            )
        except ProviderError as exc:
            print(f"reviewbot: provider error on {chunk.path} {chunk.hunk_header}: {exc}")
            outcome.chunks_errored += 1
            continue
        if telemetry is not None:
            telemetry.record("review", model, response.usage, time.monotonic() - started)
        outcome.chunks_reviewed += 1
        for finding in response.parsed.findings:
            finding.path = chunk.path  # pipeline knows the path; the model doesn't get a vote
            outcome.findings.append((finding, chunk))
    return outcome
