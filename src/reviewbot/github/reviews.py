"""Validate finding anchors against the diff and post one batched review."""

from typing import Any

from reviewbot.diff.chunker import ReviewUnit
from reviewbot.github.client import GitHubClient
from reviewbot.pipeline.fingerprint import fingerprint, marker
from reviewbot.schemas import Finding


def build_comments(
    findings: list[tuple[Finding, ReviewUnit]],
    existing_fingerprints: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Turn findings into GitHub review-comment payloads.

    Drops any finding whose line numbers don't exist on side RIGHT of its own
    hunk — GitHub rejects the *entire* review if one comment anchor is invalid,
    so one hallucinated line number must not sink the run. Also skips findings
    whose content fingerprint was already posted (idempotency across re-runs).
    """
    existing = existing_fingerprints or set()
    comments: list[dict[str, Any]] = []
    seen: set[str] = set()
    for finding, unit in findings:
        start = finding.line
        end = finding.end_line if finding.end_line and finding.end_line > finding.line else None
        anchor_lines = range(start, (end or start) + 1)
        if any(n not in unit.new_lines for n in anchor_lines):
            continue

        fp = fingerprint(unit.path, unit.lines_for(start, end), finding.category)
        if fp in existing or fp in seen:
            continue
        seen.add(fp)

        comment: dict[str, Any] = {
            "path": unit.path,
            "line": end or start,
            "side": "RIGHT",
            "body": (
                f"**[{finding.severity}] {finding.category}**\n\n"
                f"{finding.comment}\n\n{marker(fp)}"
            ),
        }
        if end is not None:
            comment["start_line"] = start
            comment["start_side"] = "RIGHT"
        comments.append(comment)
    return comments


def post_review(
    gh: GitHubClient,
    pr_number: int,
    commit_sha: str,
    summary: str,
    comments: list[dict[str, Any]],
) -> None:
    """POST one review with all inline comments batched. Posting nothing when
    there are no comments is deliberate — silence is a valid review."""
    if not comments:
        return
    gh.post(
        f"/pulls/{pr_number}/reviews",
        {
            "commit_id": commit_sha,
            "event": "COMMENT",
            "body": summary,
            "comments": comments,
        },
    )
