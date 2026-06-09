"""Anti-loop detection — concrete detector implementations."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from .base import LoopReport, LoopSignal, MessageRecord


def _cosine(a: list[float], b: list[float]) -> float:
    # Embeddings are normalized in EmbeddingService → cosine == dot product.
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


class SemanticLoopDetector:
    """Cosine similarity over message embeddings for the same actor.

    Fires when at least `trigger_count` of the most recent messages cross
    the similarity threshold against any earlier message in the window.
    """

    name = "semantic_similarity"

    def __init__(self, *, threshold: float = 0.90, trigger_count: int = 3, history_size: int = 5):
        self.threshold = threshold
        self.trigger_count = trigger_count
        self.history_size = history_size

    def check(self, *, actor_key: str, history: list[MessageRecord]) -> LoopReport:
        # Need enough embedded messages
        embedded = [m for m in history if m.embedding is not None][-self.history_size :]
        if len(embedded) < self.trigger_count:
            return LoopReport(detected=False, severity="green", score=0)

        # Compare each pair (i, j) within the window
        looping_ids: list = []
        max_sim = 0.0
        n = len(embedded)
        for i in range(n):
            for j in range(i + 1, n):
                sim = _cosine(embedded[i].embedding, embedded[j].embedding)
                if sim >= self.threshold:
                    if embedded[i].message_id not in looping_ids:
                        looping_ids.append(embedded[i].message_id)
                    if embedded[j].message_id not in looping_ids:
                        looping_ids.append(embedded[j].message_id)
                    if sim > max_sim:
                        max_sim = sim

        if len(looping_ids) < self.trigger_count:
            return LoopReport(detected=False, severity="green", score=0)

        # Score: linear ramp from threshold→1.0 onto 60→100
        ramp = (max_sim - self.threshold) / max(1e-6, 1.0 - self.threshold)
        score = int(60 + max(0.0, min(1.0, ramp)) * 40)
        severity = "red" if score >= 80 else "orange" if score >= 60 else "yellow"

        return LoopReport(
            detected=True,
            severity=severity,
            score=score,
            signals=[
                LoopSignal(
                    name=self.name,
                    score=score,
                    detail=f"{len(looping_ids)} messages with cosine similarity ≥ {self.threshold:.2f} "
                    f"(max {max_sim:.3f}) within last {n} embedded messages",
                )
            ],
            loop_message_ids=list(looping_ids),
        )


def _tool_call_hash(tc) -> str:
    payload = {"name": tc.name, "args": tc.arguments}
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ToolRepeatDetector:
    """Same tool call (name + canonical args) repeated `trigger_count` times.

    Cheap; doesn't require embeddings.
    """

    name = "tool_call_repeat"

    def __init__(self, *, trigger_count: int = 3, history_size: int = 5):
        self.trigger_count = trigger_count
        self.history_size = history_size

    def check(self, *, actor_key: str, history: list[MessageRecord]) -> LoopReport:
        recent = [m for m in history if m.tool_call is not None][-self.history_size :]
        if len(recent) < self.trigger_count:
            return LoopReport(detected=False, severity="green", score=0)

        hashes = [_tool_call_hash(m.tool_call) for m in recent]
        counts = Counter(hashes)
        top_hash, top_count = counts.most_common(1)[0]
        if top_count < self.trigger_count:
            return LoopReport(detected=False, severity="green", score=0)

        loop_ids = [m.message_id for m, h in zip(recent, hashes) if h == top_hash]
        # Score: 60 at exactly trigger_count → 100 at 2× trigger_count or more
        ratio = (top_count - self.trigger_count) / max(1, self.trigger_count)
        score = int(60 + min(1.0, ratio) * 40)
        severity = "red" if score >= 80 else "orange" if score >= 60 else "yellow"

        tool_name = recent[hashes.index(top_hash)].tool_call.name
        return LoopReport(
            detected=True,
            severity=severity,
            score=score,
            signals=[
                LoopSignal(
                    name=self.name,
                    score=score,
                    detail=f"Tool '{tool_name}' called {top_count} times with identical arguments",
                )
            ],
            loop_message_ids=loop_ids,
        )


class CompositeDetector:
    """Run all child detectors; return the worst severity, merge loop ids."""

    name = "composite"

    def __init__(self, detectors: list):
        self.detectors = detectors

    def check(self, *, actor_key: str, history: list[MessageRecord]) -> LoopReport:
        signals: list[LoopSignal] = []
        loop_ids: list = []
        max_score = 0
        worst: str = "green"
        for d in self.detectors:
            try:
                r = d.check(actor_key=actor_key, history=history)
            except Exception:
                continue
            if r.detected:
                signals.extend(r.signals)
                for mid in r.loop_message_ids:
                    if mid not in loop_ids:
                        loop_ids.append(mid)
                if r.score > max_score:
                    max_score = r.score
                if _severity_rank(r.severity) > _severity_rank(worst):
                    worst = r.severity

        return LoopReport(
            detected=worst != "green",
            severity=worst,
            score=max_score,
            signals=signals,
            loop_message_ids=loop_ids,
        )


def _severity_rank(s: str) -> int:
    return {"green": 0, "yellow": 1, "orange": 2, "red": 3}.get(s, 0)


def build_default_detector() -> CompositeDetector:
    return CompositeDetector(
        [
            ToolRepeatDetector(),
            SemanticLoopDetector(),
        ]
    )
