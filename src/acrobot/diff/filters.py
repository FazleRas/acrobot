"""Decide which changed files are worth reviewing at all."""

from functools import lru_cache

import pathspec

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


@lru_cache(maxsize=8)
def _ignore_spec(patterns: tuple[str, ...]) -> pathspec.GitIgnoreSpec:
    return pathspec.GitIgnoreSpec.from_lines(patterns)


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
    # Gitignore semantics (pathspec.GitIgnoreSpec), not fnmatch: "*" stops at
    # "/", bare names match at any depth, and a leading "/" anchors to the
    # repo root. Under fnmatch, "*" crossed directories — "*.py" silently
    # matched the entire tree.
    spec = _ignore_spec((*config.ignore, *config.extend_ignore))
    return not spec.match_file(filename)
