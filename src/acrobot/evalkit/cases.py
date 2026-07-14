"""Eval case definitions: labeled diffs the reviewer is measured against.

A case is a YAML file in evals/cases/ pointing at a fixture (the JSON payload
of GET /pulls/{n}/files — exactly what the pipeline eats in production) plus
labels: findings a good reviewer must produce, and files where any finding at
all is a confirmed false positive.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from acrobot.schemas import Category


class ExpectedFinding(BaseModel):
    path: str
    line: int
    line_tolerance: int = 2
    category: Category | None = None  # None = any category counts as a match
    must_mention: list[str] = Field(default_factory=list)  # any-of, case-insensitive


class EvalCase(BaseModel):
    name: str
    description: str = ""
    source: str = ""  # provenance, e.g. "acrobot PR #3"
    fixture: str  # filename under evals/fixtures/
    expected_findings: list[ExpectedFinding] = Field(default_factory=list)
    clean_files: list[str] = Field(default_factory=list)


def load_cases(cases_dir: Path) -> list[EvalCase]:
    cases = []
    for path in sorted(cases_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        cases.append(EvalCase(name=path.stem, **data))
    return cases
