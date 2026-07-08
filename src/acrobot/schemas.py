"""LLM output schemas.

These are enforced via structured outputs — the model returns JSON validated
against these classes. The pipeline never regex-parses LLM prose.
"""

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "warning", "nit"]
Category = Literal["bug", "security", "performance", "readability", "test-gap"]

SEVERITY_ORDER: dict[str, int] = {"critical": 2, "warning": 1, "nit": 0}


class Finding(BaseModel):
    path: str
    line: int  # line number in the new file version (diff side RIGHT)
    end_line: int | None = None  # set for multi-line comments
    severity: Severity
    category: Category
    confidence: float = Field(ge=0.0, le=1.0)
    comment: str  # markdown, posted verbatim as the inline comment body


class FindingList(BaseModel):
    findings: list[Finding]


class TriageResult(BaseModel):
    """Cheap-model score for one chunk: is this worth the review model's budget?"""

    score: int = Field(ge=0, le=10)
    reason: str = ""
