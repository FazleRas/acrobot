"""ACROBOT eval runner — measures the reviewer against labeled cases.

Default mode replays committed cassettes: deterministic, free, runs in CI on
every PR. `--live` makes real API calls (spends free-tier budget) and records
or refreshes the cassettes; run it after any prompt/model change, review the
new report, and commit the updated cassettes alongside the change.

Triage is deliberately bypassed — this harness measures the reviewer.

Usage:
  uv run evals/runner.py                    # cassette replay
  uv run evals/runner.py --live             # real calls + record
  uv run evals/runner.py --case pr3_planted_bugs
"""

import argparse
import json
import os
import sys
from pathlib import Path

from acrobot.config import BotConfig
from acrobot.diff.chunker import build_units
from acrobot.diff.filters import should_review
from acrobot.diff.parser import Chunk, parse_patch
from acrobot.evalkit.cases import EvalCase, load_cases
from acrobot.evalkit.cassette import CassetteMiss, CassetteProvider
from acrobot.evalkit.scoring import CaseScore, score
from acrobot.llm.gemini_provider import GeminiProvider
from acrobot.pipeline.review import review
from acrobot.ratelimit import RateLimiter
from acrobot.telemetry import RunTelemetry, hypothetical_cost

EVALS_DIR = Path(__file__).resolve().parent


def run_case(
    case: EvalCase,
    config: BotConfig,
    live: bool,
    limiter: RateLimiter,
    telemetry: RunTelemetry,
) -> CaseScore:
    fixture = json.loads((EVALS_DIR / "fixtures" / case.fixture).read_text())
    chunks: list[Chunk] = []
    for item in fixture:
        if should_review(item["filename"], item["status"], item.get("patch"), config):
            chunks.extend(parse_patch(item["filename"], item["patch"]))
    units = build_units(chunks, config.max_tokens_per_request)

    provider = CassetteProvider(
        EVALS_DIR / "cassettes" / f"{case.name}.json",
        inner=GeminiProvider() if live else None,
    )
    outcome = review(provider, limiter, config.models.review, units, telemetry)
    if outcome.budget_exhausted or outcome.units_errored:
        raise RuntimeError(
            f"{case.name}: incomplete run (budget_exhausted={outcome.budget_exhausted}, "
            f"errored={outcome.units_errored}) — metrics would be misleading; "
            f"retry when quota allows"
        )
    if live:
        provider.save()
    return score(case, [finding for finding, _ in outcome.findings])


def render_report(scores: list[CaseScore], telemetry: RunTelemetry) -> str:
    lines = [
        "## ACROBOT eval report",
        "",
        "| case | expected | TP | FN | FP | extra | recall |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in scores:
        recall = f"{s.recall:.0%}" if s.recall is not None else "—"
        lines.append(
            f"| {s.name} | {s.expected} | {len(s.tp)} | {len(s.fn)} | {len(s.fp)} "
            f"| {len(s.extra)} | {recall} |"
        )
    tp = sum(len(s.tp) for s in scores)
    fn = sum(len(s.fn) for s in scores)
    fp = sum(len(s.fp) for s in scores)
    extra = sum(len(s.extra) for s in scores)
    lines += [
        "",
        f"**Recall** {tp}/{tp + fn}"
        + (f" = {tp / (tp + fn):.0%}" if tp + fn else " (no labels)"),
        f"**Precision (known)** {tp}/{tp + fp}"
        + (f" = {tp / (tp + fp):.0%}" if tp + fp else " (n/a)")
        + " — counts only confirmed labels; `extra` findings are unlabeled territory",
        f"**Strict precision** {tp}/{tp + fp + extra}"
        + (f" = {tp / (tp + fp + extra):.0%}" if tp + fp + extra else " (n/a)")
        + " — treats every unlabeled finding as wrong (lower bound)",
    ]
    for stage, stats in telemetry.stages.items():
        model = stage.split("(")[-1].rstrip(")")
        cost = hypothetical_cost(model, stats.usage)
        cost_text = f"${cost:.4f}" if cost is not None else "—"
        lines.append(
            f"**{stage}** {stats.requests} request(s), "
            f"{stats.usage.input_tokens}in/{stats.usage.output_tokens}out/"
            f"{stats.usage.thinking_tokens}think tokens, hypothetical {cost_text}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="real API calls; records/refreshes cassettes"
    )
    parser.add_argument("--case", help="run a single case by name")
    args = parser.parse_args(argv)

    config = BotConfig()
    cases = load_cases(EVALS_DIR / "cases")
    if args.case:
        cases = [c for c in cases if c.name == args.case]
        if not cases:
            print(f"no case named {args.case!r}", file=sys.stderr)
            return 1
    if not cases:
        print("no cases found in evals/cases/", file=sys.stderr)
        return 1

    # Replay needs no throttle; live mode respects the same caps as production.
    limiter = (
        RateLimiter(rpm=config.rate_limits.review.rpm, rpd=config.rate_limits.review.rpd)
        if args.live
        else RateLimiter(rpm=1_000_000, rpd=1_000_000)
    )
    telemetry = RunTelemetry()

    scores = []
    try:
        for case in cases:
            scores.append(run_case(case, config, args.live, limiter, telemetry))
    except CassetteMiss as exc:
        print(f"eval: {exc}", file=sys.stderr)
        return 1

    report = render_report(scores, telemetry)
    print(report)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as handle:
            handle.write(report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
