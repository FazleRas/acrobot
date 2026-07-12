# False-positive ledger

Confirmed false positives and instructive misses from live self-review runs,
dated and linked. This is the raw material for the weekend-3 eval harness:
each entry becomes a labeled case (the diff plus the *correct* expected output),
so prompt/model changes can be regression-tested against real mistakes instead
of hypotheticals.

Legend: **FP** = false positive (flagged a non-issue) · **BLIND** = correct in
isolation but wrong given context the bot couldn't see.

---

## 1. API-key detection: status-code advice was wrong — FP
- **Where:** PR #2 review, `gemini_provider.py` error handling
- **Claimed:** the `"api key" in str(exc)` string match is brittle; rely on
  status codes 401/403 instead.
- **Why it's wrong:** Google returns **400 `API_KEY_INVALID`** for a bad key,
  not 401/403. Following the advice would have broken invalid-key detection —
  the exact failure that motivated the code an hour earlier.
- **Correct label:** no change required (the brittleness concern is fair but
  the suggested fix regresses behavior). Middle ground shipped in PR #4:
  case-insensitive match + comment.

## 2. Sibling-hunk blindness: asked for a test that already existed — BLIND
- **Where:** PR #4 review, `gemini_provider.py`
- **Claimed:** add a test mocking an `APIError` with an "api key" message.
- **Why it's a miss:** that test was three hunks down in the same PR. The bot
  reviewed one hunk at a time and couldn't see it.
- **Correct label:** no finding. **Directly motivated the PR #6 chunker**
  (group same-file hunks into one request). Still possible across *files* —
  the standing argument for the v2 whole-codebase context layer.

## 3. Sibling-hunk blindness, again: postprocess tests — BLIND
- **Where:** PR #6 review, `postprocess.py`
- **Claimed:** add tests for cap behavior, tie-breaking, partial filtering.
- **Why it's a miss:** most existed in `test_chunker_postprocess.py` in the
  same PR. The remaining genuine gaps (empty list, threshold boundaries) were
  worth adding and shipped in the quota-hardening PR.
- **Correct label:** partial — most requested tests already present.

## 4. `__new__` test helper called "fragile" — half-credit
- **Where:** PR #4 review, `test_error_paths.py`
- **Claimed:** the `__new__`-bypass test helper is fragile; instantiate
  normally and patch instead.
- **Why it's half-right:** the instinct was sound, but the suggested fix
  (normal instantiation) needs real credentials. The right fix was a
  constructor injection seam (`GeminiProvider(client=...)`), added in the
  quota-hardening PR — which resolves the concern properly.
- **Correct label:** valid concern, wrong fix.

## 5. Claimed `ProviderAuthError` is swallowed by `except ProviderError` — BLIND
- **Where:** PR #9 review, `pipeline/triage.py`
- **Claimed (severity `critical`):** the generic `except ProviderError` block
  catches `ProviderAuthError`, so dead keys fail open instead of aborting;
  import it and catch it first.
- **Why it's wrong:** `ProviderAuthError` is deliberately **not** a
  `ProviderError` subclass — exactly so no generic handler can ever swallow
  it. That fact lives in `llm/provider.py`, a file the reviewed unit doesn't
  include. `test_auth_error_propagates_not_swallowed` proves the behavior.
- **Correct label:** no finding. Cross-file blindness, instance #4 — and the
  first one that would have prompted a *harmful* "fix" (reordering catches to
  handle an exception that can't arrive) rather than just redundant work.

---

## Patterns
- **4 of 5 are context-blindness, not reasoning errors.** The model is right
  about the code in front of it and wrong about the code it can't see. That is
  the single strongest data point for the v2 roadmap. Case #5 escalates the
  stakes: cross-file blindness can now generate confidently-wrong `critical`
  findings about class hierarchies defined elsewhere.
- **Severity mis-calibration:** everything tends to come back tagged higher
  than a human would rate it (validation nits posted as `critical`). Tuning
  target for the eval harness, not a code fix.
