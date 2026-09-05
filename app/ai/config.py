"""AI-analyst configuration and version tags (Phase 5 — source of truth).

Class-based model abstraction (Master Plan §0.1-2): business logic references a
``ModelClass`` (HAIKU/SONNET/OPUS); the exact ``model_id`` is resolved from this
versioned config at runtime and recorded on every verdict for audit (§16). Model
IDs are NEVER hardcoded in business logic. Defaults are currently-valid Claude
IDs and are re-verified when the real provider is wired (a later phase).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

AI_ANALYST_VERSION = "ai-v1"
PROMPT_VERSION = "analyst-v1"


class ModelClass(StrEnum):
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"


@dataclass(frozen=True)
class AIConfig:
    """Analyst model resolution + operational policy. Not calibrated."""

    analyst_model_class: ModelClass = ModelClass.SONNET  # main analysis (§6)
    haiku_model_id: str = "claude-haiku-4-5-20251001"
    sonnet_model_id: str = "claude-sonnet-4-6"
    opus_model_id: str = "claude-opus-4-8"
    analyst_enabled: bool = True
    timeout_seconds: float = 20.0
    uncertain_policy: str = "hold"  # only "hold" supported in P5 (§6)

    def __post_init__(self) -> None:
        for name in ("haiku_model_id", "sonnet_model_id", "opus_model_id"):
            if not getattr(self, name):
                raise ValueError(f"{name} must be non-empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if self.uncertain_policy != "hold":
            raise ValueError("uncertain_policy must be 'hold' in Phase 5")

    def resolve_model_id(self, model_class: ModelClass) -> str:
        return {
            ModelClass.HAIKU: self.haiku_model_id,
            ModelClass.SONNET: self.sonnet_model_id,
            ModelClass.OPUS: self.opus_model_id,
        }[model_class]

    @property
    def analyst_model_id(self) -> str:
        """The exact runtime-resolved model_id for the analyst role."""
        return self.resolve_model_id(self.analyst_model_class)

    @property
    def version_tag(self) -> str:
        return (
            f"{AI_ANALYST_VERSION}|prompt{PROMPT_VERSION}"
            f"|cls{self.analyst_model_class.value}|id{self.analyst_model_id}"
            f"|en{int(self.analyst_enabled)}|to{self.timeout_seconds}"
        )
