"""Action entry point: read the pull_request event, run the pipeline, post one review.

Weekend-1 happy path: fetch → filter → parse → review → post. No chunk merging
or triage tier yet — every surviving hunk goes straight to the review model.
"""

import json
import os
import sys
from pathlib import Path

from reviewbot.config import BotConfig
from reviewbot.diff.filters import should_review
from reviewbot.diff.parser import Chunk, parse_patch
from reviewbot.github.client import GitHubClient
from reviewbot.github.pr import fetch_changed_files, fetch_existing_comment_bodies
from reviewbot.github.reviews import build_comments, post_review
from reviewbot.llm.gemini_provider import GeminiProvider
from reviewbot.pipeline.fingerprint import extract_fingerprints
from reviewbot.pipeline.review import review
from reviewbot.ratelimit import RateLimiter
from reviewbot.telemetry import RunTelemetry


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not (event_path and repo and token):
        print("reviewbot: needs GITHUB_EVENT_PATH, GITHUB_REPOSITORY, GITHUB_TOKEN (Actions env)")
        return 1

    event = json.loads(Path(event_path).read_text())
    pr = event.get("pull_request")
    if pr is None:
        print("reviewbot: not a pull_request event, nothing to do")
        return 0
    if pr.get("draft"):
        print("reviewbot: draft PR, skipping")
        return 0

    config = BotConfig.load(Path(os.environ.get("REVIEWBOT_CONFIG", ".github/reviewbot.yml")))
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
    print(f"reviewbot: {len(changed)} files -> {len(chunks)} hunks ({filtered} files filtered)")
    if not chunks:
        return 0

    outcome = review(provider, limiter, config.models.review, chunks, telemetry)
    existing = extract_fingerprints(fetch_existing_comment_bodies(gh, number))
    comments = build_comments(outcome.findings, existing)

    summary = [
        f"🤖 AI review: {len(comments)} finding(s) across {outcome.chunks_reviewed} hunk(s)."
    ]
    if outcome.budget_exhausted:
        summary.append("⚠️ Daily free-tier budget ran out mid-review — this is a partial review.")
    if outcome.chunks_errored:
        summary.append(f"{outcome.chunks_errored} hunk(s) skipped due to provider errors.")
    post_review(gh, number, pr["head"]["sha"], "\n\n".join(summary), comments)

    telemetry.write_step_summary()
    print(f"reviewbot: posted {len(comments)} comment(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
