"""Content-based finding fingerprints for idempotent comment posting.

Fingerprints hash the *content* of the flagged lines rather than line numbers,
so they survive the diff shifting when new commits land on the PR. Each posted
comment embeds its fingerprint in a hidden HTML marker; on re-runs we skip any
finding whose fingerprint already exists on the PR.
"""

import hashlib
import re
from collections.abc import Iterable

_MARKER_RE = re.compile(r"<!-- acrobot:fp:([0-9a-f]{16}) -->")


def fingerprint(path: str, flagged_lines: str, category: str) -> str:
    normalized = "\n".join(line.strip() for line in flagged_lines.strip().splitlines())
    digest = hashlib.sha256(f"{path}\0{normalized}\0{category}".encode())
    return digest.hexdigest()[:16]


def marker(fp: str) -> str:
    return f"<!-- acrobot:fp:{fp} -->"


def extract_fingerprints(comment_bodies: Iterable[str]) -> set[str]:
    found: set[str] = set()
    for body in comment_bodies:
        found.update(_MARKER_RE.findall(body))
    return found
