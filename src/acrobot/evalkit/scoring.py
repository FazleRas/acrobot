"""Match actual findings against a case's labels and bucket the results.

Buckets:
  * tp    — matched an expected finding (greedy one-to-one)
  * fn    — expected finding nothing matched (a miss)
  * fp    — finding on a file labeled clean (a confirmed false positive)
  * extra — unmatched finding on unlabeled territory. Deliberately its own
    bucket: it could be a real bug we never labeled (happened on day one) or
    a false positive, so it pollutes neither precision definition. The report
    surfaces both a strict and a known-only precision.
"""

from dataclasses import dataclass, field

from acrobot.evalkit.cases import EvalCase, ExpectedFinding
from acrobot.schemas import Finding


def matches(expected: ExpectedFinding, actual: Finding) -> bool:
    if actual.path != expected.path:
        return False
    if abs(actual.line - expected.line) > expected.line_tolerance:
        return False
    if expected.category is not None and actual.category != expected.category:
        return False
    if expected.must_mention:
        comment = actual.comment.lower()
        if not any(term.lower() in comment for term in expected.must_mention):
            return False
    return True


@dataclass
class CaseScore:
    name: str
    tp: list[Finding] = field(default_factory=list)
    fn: list[ExpectedFinding] = field(default_factory=list)
    fp: list[Finding] = field(default_factory=list)
    extra: list[Finding] = field(default_factory=list)

    @property
    def expected(self) -> int:
        return len(self.tp) + len(self.fn)

    @property
    def recall(self) -> float | None:
        return len(self.tp) / self.expected if self.expected else None


def score(case: EvalCase, findings: list[Finding]) -> CaseScore:
    result = CaseScore(name=case.name)
    remaining = list(findings)
    for expected in case.expected_findings:
        hit = next((f for f in remaining if matches(expected, f)), None)
        if hit is None:
            result.fn.append(expected)
        else:
            result.tp.append(hit)
            remaining.remove(hit)  # greedy 1:1 — one finding can't satisfy two labels
    clean = set(case.clean_files)
    for finding in remaining:
        (result.fp if finding.path in clean else result.extra).append(finding)
    return result
