"""Record/replay Provider calls at the protocol boundary.

Cassettes are keyed by a hash of everything model-facing (model, system
prompt, user prompt, schema name). A replay hit means the pipeline sent a
byte-identical request, so CI exercises the whole machinery — parsing,
chunking, anchoring, scoring — deterministically and for free. A miss means
someone changed the model-facing surface; a recording of the *old* prompt
can't say how the model answers the *new* one, so the runner fails loudly
with re-record instructions instead of reporting stale numbers.

Recording lives at the Provider boundary on purpose: cassettes stay valid for
any future adapter, which makes them the request corpus for the provider
benchmark.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from acrobot.llm.provider import Provider, ProviderResponse, Usage


class CassetteMiss(RuntimeError):
    """Replay requested for a call that was never recorded."""


def _key(model: str, system: str, prompt: str, schema_name: str) -> str:
    # JSON-encoding preserves field boundaries unambiguously — a separator
    # character appearing inside an input can't blur two fields together.
    payload = json.dumps([model, system, prompt, schema_name])
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


class CassetteProvider:
    """Provider that replays recorded responses, or records through `inner`.

    `inner=None` is strict-replay mode: any unrecorded call raises
    CassetteMiss. With an inner provider, hits still replay (so re-recording
    only spends budget on calls that actually changed) and misses are
    forwarded and recorded.
    """

    def __init__(self, path: Path, inner: Provider | None = None) -> None:
        self._path = path
        self._inner = inner
        # Tolerate an existing-but-empty file (truncated or interrupted write);
        # treat it as an empty cassette rather than crashing on json.loads("").
        text = path.read_text() if path.exists() else ""
        self._entries: dict[str, Any] = json.loads(text) if text.strip() else {}
        self.replayed = 0
        self.recorded = 0

    def generate(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        schema: type[BaseModel],
        reasoning: bool = False,
    ) -> ProviderResponse:
        key = _key(model, system, prompt, schema.__name__)
        entry = self._entries.get(key)
        if entry is not None:
            self.replayed += 1
            return ProviderResponse(
                parsed=schema.model_validate(entry["parsed"]),
                usage=Usage(**entry["usage"]),
                model=entry["model"],
            )
        if self._inner is None:
            raise CassetteMiss(
                f"no recording in {self._path.name} for a {schema.__name__} call to "
                f"{model} — the model-facing prompt changed. Re-record with "
                f"`uv run evals/runner.py --live`, review the new report, and commit "
                f"the updated cassettes."
            )
        response = self._inner.generate(
            model=model, system=system, prompt=prompt, schema=schema, reasoning=reasoning
        )
        self._entries[key] = {
            "model": response.model,
            "parsed": response.parsed.model_dump(),
            "usage": vars(response.usage),
        }
        self.recorded += 1
        return response

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._entries, indent=2, sort_keys=True) + "\n")
