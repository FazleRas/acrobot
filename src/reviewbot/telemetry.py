"""Per-stage token/cost/latency tracking.

Actual spend on the free tier is $0; the hypothetical column keeps the paid-tier
economics measured anyway, so every run doubles as pricing research. Written to
GITHUB_STEP_SUMMARY as a markdown table at the end of each run.
"""

import os
from dataclasses import dataclass, field

from reviewbot.llm.provider import Usage

# (input, output) USD per 1M tokens. Static snapshot (2026-07) for the
# "what this run would have cost" column — refresh when quoting numbers.
HYPOTHETICAL_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
}


def hypothetical_cost(model: str, usage: Usage) -> float | None:
    pricing = HYPOTHETICAL_PRICING_PER_MTOK.get(model)
    if pricing is None:
        return None
    input_price, output_price = pricing
    output_tokens = usage.output_tokens + usage.thinking_tokens
    return (usage.input_tokens * input_price + output_tokens * output_price) / 1_000_000


@dataclass
class StageStats:
    requests: int = 0
    usage: Usage = field(default_factory=Usage)
    seconds: float = 0.0


class RunTelemetry:
    def __init__(self) -> None:
        self.stages: dict[str, StageStats] = {}

    def record(self, stage: str, model: str, usage: Usage, seconds: float) -> None:
        stats = self.stages.setdefault(f"{stage} ({model})", StageStats())
        stats.requests += 1
        stats.usage.input_tokens += usage.input_tokens
        stats.usage.output_tokens += usage.output_tokens
        stats.usage.thinking_tokens += usage.thinking_tokens
        stats.seconds += seconds

    def write_step_summary(self) -> None:
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if not path or not self.stages:
            return
        lines = [
            "## reviewbot run",
            "",
            "| stage | requests | in tok | out tok | think tok | s | actual | hypothetical |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for name, stats in self.stages.items():
            model = name.split("(")[-1].rstrip(")")
            cost = hypothetical_cost(model, stats.usage)
            cost_cell = f"${cost:.4f}" if cost is not None else "—"
            usage = stats.usage
            lines.append(
                f"| {name} | {stats.requests} | {usage.input_tokens} | {usage.output_tokens} "
                f"| {usage.thinking_tokens} | {stats.seconds:.1f} | $0.00 | {cost_cell} |"
            )
        with open(path, "a") as handle:
            handle.write("\n".join(lines) + "\n")
