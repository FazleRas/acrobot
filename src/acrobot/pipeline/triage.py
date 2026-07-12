"""Cheap-model gate: score each unit before the review model spends its budget.

Triage exists because the review model's free-tier pool is tiny (20/day ≈ two
medium PRs) while flash-lite's pool is large. Scoring every unit with the
cheap model and sending only the plausible ones onward stretches the scarce
pool across more PRs.

The governing rule: **triage is an optimization, never a gate that silently
loses code.** Every failure mode fails OPEN — provider error, rate limit,
exhausted triage budget — and the unit goes to review anyway. A broken triage
stage can only cost budget, never findings. The one exception is
ProviderAuthError, which propagates: a dead key should abort the run loudly,
not fail open into more dead calls.

Disable triage by setting `triage_threshold: 0` (every score passes, no
triage calls are made).
"""

import time
from dataclasses import dataclass, field
from importlib.resources import files

from acrobot.diff.chunker import ReviewUnit
from acrobot.llm.provider import Provider, ProviderError, ProviderRateLimitError
from acrobot.ratelimit import DailyBudgetExhausted, RateLimiter
from acrobot.schemas import TriageResult
from acrobot.telemetry import RunTelemetry


@dataclass
class TriageOutcome:
    kept: list[ReviewUnit] = field(default_factory=list)
    skipped: list[tuple[ReviewUnit, int]] = field(default_factory=list)  # (unit, score)
    errored: int = 0  # triage failures — failed open, unit kept


def _system_prompt() -> str:
    return files("acrobot.llm.prompts").joinpath("triage.md").read_text()


def _user_prompt(unit: ReviewUnit) -> str:
    # No numbered line listing here — triage judges risk, it doesn't anchor
    # comments. Raw hunks keep the cheap call cheap.
    hunks = "\n".join(f"```diff\n{chunk.content}```" for chunk in unit.chunks)
    return f"File: `{unit.path}`\n\n{hunks}"


def triage(
    provider: Provider,
    limiter: RateLimiter,
    model: str,
    units: list[ReviewUnit],
    threshold: int,
    telemetry: RunTelemetry | None = None,
) -> TriageOutcome:
    outcome = TriageOutcome()
    if threshold <= 0:
        outcome.kept = list(units)
        return outcome
    system = _system_prompt()
    for index, unit in enumerate(units):
        try:
            limiter.acquire()
        except DailyBudgetExhausted:
            outcome.kept.extend(units[index:])  # fail open for everything left
            break
        started = time.monotonic()
        try:
            response = provider.generate(
                model=model,
                system=system,
                prompt=_user_prompt(unit),
                schema=TriageResult,
                reasoning=False,
            )
        except ProviderRateLimitError as exc:
            if exc.is_daily:
                outcome.kept.extend(units[index:])
                break
            outcome.errored += 1
            outcome.kept.append(unit)
            continue
        except ProviderError as exc:
            print(f"acrobot: triage error on {unit.path} (failing open): {exc}")
            outcome.errored += 1
            outcome.kept.append(unit)
            continue
        if telemetry is not None:
            telemetry.record("triage", model, response.usage, time.monotonic() - started)
        if response.parsed.score >= threshold:
            outcome.kept.append(unit)
        else:
            outcome.skipped.append((unit, response.parsed.score))
    return outcome
