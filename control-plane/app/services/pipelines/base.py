"""Bob Manager — Abstract media pipeline base class."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Standardised result from a media pipeline execution."""

    success: bool
    media_type: str = ""          # "audio", "image", "video"
    media_url: str = ""           # data URL or remote URL
    preview_url: str = ""         # spectrogram / thumbnail (data URL)
    duration_s: float = 0.0       # media duration in seconds
    params_used: dict = field(default_factory=dict)  # the actual params sent
    error: str = ""               # error message if success=False
    raw: dict = field(default_factory=dict)  # full API response
    extra_outputs: dict = field(default_factory=dict)  # named extra files (e.g. stems)


class MediaPipeline(ABC):
    """Abstract base for non-LLM media generation pipelines.

    Subclasses must implement:
        - generate()       — run inference with validated params
        - build_params()   — transform a natural-language prompt into API params
        - health_check()   — probe the service
        - system_prompt()  — return the LLM system prompt for param generation
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    # ── Core interface ───────────────────────────────

    @abstractmethod
    async def generate(self, params: dict) -> PipelineResult:
        """Execute inference with a fully-formed parameter dict.

        The dict shape is pipeline-specific (e.g. riffusion InferenceInput).
        Returns a PipelineResult.
        """

    @abstractmethod
    def validate_params(self, params: dict) -> dict:
        """Validate and sanitise raw params (e.g. from LLM output).

        Clamps values, fills defaults, rejects invalid fields.
        Returns the cleaned dict.  Raises ValueError on irrecoverable input.
        """

    @abstractmethod
    def system_prompt(self) -> str:
        """Return the system prompt that teaches an LLM to produce
        valid params for this pipeline."""

    @abstractmethod
    def build_tool_params(self, prompt: str, extra: dict) -> dict:
        """Build pipeline-specific params from a user prompt and extra args.

        Called by the generic media_pipeline tool handler.
        Each pipeline knows how to map (prompt, extra) to its own param format.
        """

    @abstractmethod
    def tool_description(self) -> str:
        """Return a short description of this pipeline for the LLM tool schema.

        Example: 'riffusion — text-to-audio via spectrogram diffusion (supports
        start/end prompt interpolation)'
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the backend service is reachable."""

    # ── Optional overrides ───────────────────────────

    def format_summary(self, params: dict) -> str:
        """Human-readable summary of generation parameters.

        Subclasses can override for richer output.
        """
        prompt = params.get("prompt", params.get("start", {}).get("prompt", ""))
        if prompt:
            return f'**Prompt**: "{prompt[:120]}"'
        return ""
