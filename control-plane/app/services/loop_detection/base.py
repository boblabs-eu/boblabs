"""Anti-loop detection — base contracts and dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

Severity = Literal["green", "yellow", "orange", "red"]


@dataclass
class ToolCall:
    name: str
    arguments: dict


@dataclass
class MessageRecord:
    """One observed message in an actor's recent history."""

    message_id: UUID
    actor_key: str  # "orchestrator" or "agent:<name>"
    content: str
    tool_call: ToolCall | None
    created_at: datetime
    embedding: list[float] | None = None  # filled in by background embedder


@dataclass
class LoopSignal:
    name: str  # "semantic_similarity" | "tool_call_repeat"
    score: int  # 0..100 contribution
    detail: str  # human-readable explanation


@dataclass
class LoopReport:
    detected: bool
    severity: Severity
    score: int  # max signal score
    signals: list[LoopSignal] = field(default_factory=list)
    loop_message_ids: list[UUID] = field(default_factory=list)


class LoopDetector(Protocol):
    """A loop detector inspects an actor's recent messages and returns a report."""

    name: str

    def check(self, *, actor_key: str, history: list[MessageRecord]) -> LoopReport: ...
