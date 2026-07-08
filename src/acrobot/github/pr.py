"""Fetch PR metadata, changed files, and existing bot comments."""

from acrobot.github.client import GitHubClient


def fetch_changed_files(gh: GitHubClient, pr_number: int) -> list[dict]:
    """GET /pulls/{n}/files (paginated). Each item carries filename, status, patch."""
    return list(gh.paginate(f"/pulls/{pr_number}/files", per_page=100))


def fetch_existing_comment_bodies(gh: GitHubClient, pr_number: int) -> list[str]:
    """Bodies of existing review comments, for fingerprint-based idempotency."""
    return [c["body"] for c in gh.paginate(f"/pulls/{pr_number}/comments", per_page=100)]
