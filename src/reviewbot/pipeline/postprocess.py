"""Config-driven noise controls between the review pass and comment posting.

Anchor validation and fingerprint dedupe live in github/reviews.py (they need
GitHub-shaped state); this stage is pure judgment: drop what the consumer said
they don't want to see, then keep the most important findings under the cap.
"""

from reviewbot.config import BotConfig
from reviewbot.diff.chunker import ReviewUnit
from reviewbot.schemas import SEVERITY_ORDER, Finding


def postprocess(
    findings: list[tuple[Finding, ReviewUnit]], config: BotConfig
) -> list[tuple[Finding, ReviewUnit]]:
    floor = SEVERITY_ORDER[config.severity_floor]
    kept = [
        (finding, unit)
        for finding, unit in findings
        if finding.confidence >= config.confidence_threshold
        and SEVERITY_ORDER[finding.severity] >= floor
    ]
    # Highest severity first, confidence breaking ties — so the cap trims
    # the least important findings, not whichever came last.
    kept.sort(
        key=lambda pair: (SEVERITY_ORDER[pair[0].severity], pair[0].confidence),
        reverse=True,
    )
    return kept[: config.max_comments]
