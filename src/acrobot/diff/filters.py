"""Decide which changed files are worth reviewing at all."""

import fnmatch

from acrobot.config import BotConfig

# Filenames that are machine-written regardless of config globs.
_GENERATED_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Cargo.lock",
    "go.sum",
}


def should_review(filename: str, status: str, patch: str | None, config: BotConfig) -> bool:
    """`status` and `patch` come straight from GET /pulls/{n}/files items."""
    if status == "removed":
        return False  # nothing on side RIGHT to comment on
    if patch is None:
        return False  # binary or too-large-for-API file
    if len(patch.encode()) > config.max_patch_bytes:
        return False
    basename = filename.rsplit("/", 1)[-1]
    if basename in _GENERATED_NAMES:
        return False
    return not any(fnmatch.fnmatch(filename, glob) for glob in config.ignore)
