"""Action entry point: read the pull_request event, run the pipeline, post one review.

fetch → filter → parse → chunk into per-file units → review → postprocess →
post. No triage tier yet (weekend 4) — every unit goes to the review model.
"""

import json
import os
import sys
from pathlib import Path

from acrobot.config import BotConfig
from acrobot.diff.chunker import build_units
from acrobot.diff.filters import should_review
from acrobot.diff.parser import Chunk, parse_patch
from acrobot.github.client import GitHubClient
from acrobot.github.pr import fetch_changed_files, fetch_existing_comment_bodies
from acrobot.github.reviews import build_comments, post_review
from acrobot.llm.gemini_provider import GeminiProvider
from acrobot.llm.provider import ProviderAuthError
from acrobot.pipeline.fingerprint import extract_fingerprints
from acrobot.pipeline.postprocess import postprocess
from acrobot.pipeline.review import review
from acrobot.ratelimit import RateLimiter
from acrobot.telemetry import RunTelemetry


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not (event_path and repo and token):
        print("acrobot: needs GITHUB_EVENT_PATH, GITHUB_REPOSITORY, GITHUB_TOKEN (Actions env)")
        return 1

    event = json.loads(Path(event_path).read_text())
    pr = event.get("pull_request")
    if pr is None:
        print("acrobot: not a pull_request event, nothing to do")
        return 0
    if pr.get("draft"):
        print("acrobot: draft PR, skipping")
        return 0

    config = BotConfig.load(Path(os.environ.get("ACROBOT_CONFIG", ".github/acrobot.yml")))
    gh = GitHubClient(token=token, repo=repo)
    provider = GeminiProvider()
    limiter = RateLimiter(rpm=config.rate_limits.rpm, rpd=config.rate_limits.rpd)
    telemetry = RunTelemetry()

    number = pr["number"]
    changed = fetch_changed_files(gh, number)
    chunks: list[Chunk] = []
    filtered = 0
    for item in changed:
        if should_review(item["filename"], item["status"], item.get("patch"), config):
            chunks.extend(parse_patch(item["filename"], item["patch"]))
        else:
            filtered += 1
    units = build_units(chunks, config.max_tokens_per_request)
    print(
        f"acrobot: {len(changed)} files -> {len(chunks)} hunks -> {len(units)} units "
        f"({filtered} files filtered)"
    )
    if not units:
        return 0

    try:
        outcome = review(provider, limiter, config.models.review, units, telemetry)
    except ProviderAuthError as exc:
        print(f"acrobot: {exc}", file=sys.stderr)
        return 1
    kept = postprocess(outcome.findings, config)
    suppressed = len(outcome.findings) - len(kept)
    existing = extract_fingerprints(fetch_existing_comment_bodies(gh, number))
    comments = build_comments(kept, existing)

    summary = [
        f"🤖 AI review: {len(comments)} finding(s) across {outcome.units_reviewed} unit(s)."
    ]
    if suppressed:
        summary.append(
            f"{suppressed} finding(s) below the configured confidence/severity bar were suppressed."
        )
    if outcome.budget_exhausted:
        summary.append("⚠️ Daily free-tier budget ran out mid-review — this is a partial review.")
    if outcome.units_errored:
        summary.append(f"{outcome.units_errored} unit(s) skipped due to provider errors.")
    post_review(gh, number, pr["head"]["sha"], "\n\n".join(summary), comments)

    telemetry.write_step_summary()
    print(f"acrobot: posted {len(comments)} comment(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
