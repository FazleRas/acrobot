# ai-review-bot

An AI code review bot for GitHub pull requests. When a PR opens, a GitHub
Action fires, the bot parses the changed hunks, triages them with a cheap
model, reviews the survivors with a reasoning model, and posts inline review
comments — with structured outputs, content-based idempotency, client-side
rate limiting, and an eval harness that measures whether the reviews are
actually any good.

Built around a hard constraint: the **Gemini free tier**. The scarce resource
is rate-limit budget, not dollars — which forced the triage tier, the
two-clock rate limiter, and cassette-based eval replay. Full reasoning in
[docs/architecture.md](docs/architecture.md).

## Status

Early scaffold — pipeline wiring in progress.

- [x] Repo skeleton: package layout, CI, composite action
- [x] Diff parsing (GitHub patch → anchored chunks), file filters
- [x] Provider protocol + Gemini adapter (structured outputs, reasoning flag)
- [x] Rate limiter (RPM sliding window + RPD daily budget)
- [x] Comment fingerprinting for idempotent re-runs
- [x] Review pass + comment posting (anchor validation, idempotent re-runs, partial-review degradation)
- [ ] Chunker, postprocessing, end-to-end hardening (weekend 2)
- [ ] Eval harness: labeled cases, cassettes, CI regression (weekend 3)
- [ ] Triage tier + rate-limiter hardening + provider benchmark (weekend 4)
- [ ] v2: repository context layer (RAG over the codebase)

## Usage (once v1 lands)

```yaml
# .github/workflows/review.yml in your repo
name: AI Review
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
concurrency:
  group: reviewbot-${{ github.event.pull_request.number }}
  cancel-in-progress: true
permissions:
  contents: read
  pull-requests: write
jobs:
  review:
    if: github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4   # needed so the action can read .github/reviewbot.yml
      - uses: FazleRas/ai-review-bot@v1
        with:
          gemini_api_key: ${{ secrets.GEMINI_API_KEY }}
```

Optional tuning via `.github/reviewbot.yml`:

```yaml
models:
  triage: gemini-2.5-flash-lite
  review: gemini-2.5-flash
triage_threshold: 4
confidence_threshold: 0.6
max_comments: 10
severity_floor: warning
ignore:
  - "**/*.lock"
  - "**/generated/**"
```

## Development

```sh
uv sync
uv run pytest
uv run ruff check . && uv run mypy
```
