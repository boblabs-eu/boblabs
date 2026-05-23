"""Bob Manager — Parallel Broadcast loop strategy.

The user's prompt is fanned out to **every active agent in parallel**.
There is NO orchestrator LLM call: the strategy itself decides the plan
(one task per agent, all with empty `depends_on`, so the Lab Runner
dispatches them concurrently).

Use case: "Same prompt, N independent specialist outputs." Example:
the Social Media app uses one agent per platform (X / LinkedIn /
Instagram / Facebook) and each writes its own platform-specific post
without any coordination overhead.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.loop_strategies.base import (
    LoopAction,
    LoopContext,
    LoopStrategy,
    PlanAction,
    SynthesizeAction,
    TaskItem,
    TaskResult,
)

if TYPE_CHECKING:
    from app.models.orchestrator import Lab, LabAgent

logger = logging.getLogger(__name__)

# Exposed via _PROMPT_REGISTRY for UI purposes; never sent to an LLM
# because this strategy never invokes an orchestrator model.
PARALLEL_BROADCAST_SYSTEM_PROMPT = (
    "Parallel Broadcast — the user prompt is sent verbatim to every active "
    "agent in parallel. No orchestrator LLM is involved; each agent works "
    "independently from its own system prompt."
)


def _latest_user_prompt(context: LoopContext) -> str:
    """Return the broadcast instruction for this run.

    Priority:
        1. the most recent user-typed message (interactive lab)
        2. ``lab.orchestrator_prompt`` — repurposed in this strategy as the
           single broadcast instruction sent verbatim to every agent (since
           there is no orchestrator LLM call to consume it)
        3. a generic fallback
    """
    user_msgs = [m for m in context.messages if m.sender_type == "user"]
    if user_msgs:
        return user_msgs[-1].content or ""
    orch_prompt = (getattr(context.lab, "orchestrator_prompt", "") or "").strip()
    if orch_prompt:
        return orch_prompt
    return "Produce your platform-specific output per your system prompt."


class ParallelBroadcastStrategy(LoopStrategy):
    """Fan the user prompt to every agent in parallel, then finish."""

    def __init__(self, **kwargs):
        # Once we have dispatched + collected, we synthesize and stop.
        self._dispatched: bool = False
        self._results: list[TaskResult] = []
        self._pending_injections: list[str] = []

    async def initialize(self, lab: "Lab", agents: list["LabAgent"]) -> None:
        self._dispatched = False
        self._results = []
        self._pending_injections = []

    async def next_step(self, context: LoopContext) -> LoopAction:
        # If a fresh user injection arrived after the first wave, broadcast again.
        if self._dispatched and self._pending_injections:
            prompt = self._pending_injections.pop(0)
            self._results = []
            return self._broadcast(context, prompt)

        if self._dispatched:
            return SynthesizeAction(summary=self._build_summary(context))

        prompt = _latest_user_prompt(context)
        return self._broadcast(context, prompt)

    def _broadcast(self, context: LoopContext, prompt: str) -> LoopAction:
        active = [a for a in context.agents if getattr(a, "is_active", True)]
        if not active:
            return SynthesizeAction(summary="No active agents to broadcast to.")

        tasks = [
            TaskItem(
                agent_name=a.name,
                instruction=prompt,
                depends_on=[],
            )
            for a in active
        ]
        self._dispatched = True
        logger.info(
            "parallel_broadcast: dispatching prompt to %d agents in parallel: %s",
            len(tasks), [t.agent_name for t in tasks],
        )
        return PlanAction(tasks=tasks)

    async def on_results(self, context: LoopContext, results: list[TaskResult]) -> None:
        self._results.extend(results)

    async def on_inject(self, context: LoopContext, message: str) -> None:
        # Queue mid-run injections; processed on the next next_step() call.
        self._pending_injections.append(message)

    def _build_summary(self, context: LoopContext) -> str:
        if not self._results:
            return "Parallel broadcast finished with no agent outputs."
        lines = [
            f"Parallel broadcast — {len(self._results)} agent output(s):",
            "",
        ]
        for r in self._results:
            if r.error:
                lines.append(f"### {r.agent_name} — ERROR")
                lines.append(r.error)
            else:
                lines.append(f"### {r.agent_name}")
                lines.append((r.response or "").strip() or "(empty response)")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"
