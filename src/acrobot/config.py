"""Bot configuration, loaded from `.github/acrobot.yml` in the target repo.

Missing file or missing keys fall back to defaults, so consumers can adopt the
bot with zero config and tune later.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from acrobot.schemas import Severity


class ModelsConfig(BaseModel):
    triage: str = "gemini-2.5-flash-lite"
    review: str = "gemini-2.5-flash"


class RateLimitConfig(BaseModel):
    """Free-tier caps. These are config, not constants — Google adjusts
    free-tier limits over time; check ai.google.dev/gemini-api/docs/rate-limits
    rather than trusting the defaults."""

    rpm: int = 10
    rpd: int = 250


class BotConfig(BaseModel):
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    rate_limits: RateLimitConfig = Field(default_factory=RateLimitConfig)
    triage_threshold: int = Field(default=4, ge=0, le=10)
    confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    max_comments: int = 10
    severity_floor: Severity = "warning"
    max_patch_bytes: int = 100_000
    max_tokens_per_request: int = 8_000
    ignore: list[str] = Field(
        default_factory=lambda: ["**/*.lock", "**/generated/**", "**/*.min.*"]
    )

    @classmethod
    def load(cls, path: Path | None) -> "BotConfig":
        if path is None or not path.exists():
            return cls()
        return cls.model_validate(yaml.safe_load(path.read_text()) or {})
