"""Solo Agent strategy — drives a single LabAgent via native tool-calling.

Designed for Labs with exactly one LabAgent: operator-UI "agent instances"
(``acl.tag == 'agent_instance'``), consumer-app ``/run_agent`` ephemeral
runs, and consumer-app cron tick spawns.

The strategy skips the orchestrator JSON layer entirely. It emits a single
``PlanAction`` targeting the lone agent with the user's seed message; the
LabRunner's existing agent dispatch path (``lab_runner.py:740-880``) then
handles native tool-calling, RAG/web3/server tool augmentation, and the
agent's own multi-step tool loop. When the agent returns its final answer,
the strategy emits ``SynthesizeAction`` with the response — bypassing the
``parse_orchestrator_response`` JSON gate that caused parse failures under
tool errors.

Mid-run injections (operator-UI ``POST /labs/{id}/inject``) are queued and
dispatched as fresh tasks to the agent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.loop_strategies.base import (
    LoopAction,
    LoopContext,
    LoopStrategy,
    PauseAction,
    PlanAction,
    SynthesizeAction,
    TaskItem,
    TaskResult,
)

if TYPE_CHECKING:
    from app.models.orchestrator import Lab, LabAgent


class SoloAgentStrategy(LoopStrategy):
    """Single LabAgent driven by native tool-calling. No orchestrator."""

    def __init__(self) -> None:
        self._target_name: str = ""
        self._last_response: str | None = None
        self._last_error: str | None = None
        self._injections: list[str] = []

    async def initialize(self, lab: "Lab", agents: list["LabAgent"]) -> None:
        if len(agents) != 1:
            raise ValueError(
                f"solo_agent requires exactly 1 LabAgent on lab {lab.id}, got {len(agents)}"
            )
        self._target_name = agents[0].name
        self._last_response = None
        self._last_error = None
        self._injections = []

    async def next_step(self, context: LoopContext) -> LoopAction:
        # Iteration 0: dispatch the seed (user-typed messages + any standing injections)
        if context.iteration == 0:
            seed = self._collect_seed(context)
            if not seed:
                return PauseAction(reason="solo_agent: no initial user message")
            return PlanAction(tasks=[TaskItem(agent_name=self._target_name, instruction=seed)])

        # Subsequent iterations: dispatch any new mid-run injection
        if self._injections:
            instruction = "\n\n".join(self._injections)
            self._injections.clear()
            return PlanAction(
                tasks=[TaskItem(agent_name=self._target_name, instruction=instruction)]
            )

        # No new input — emit the agent's last response as the final answer
        if self._last_response is not None:
            return SynthesizeAction(summary=self._last_response)
        if self._last_error is not None:
            return SynthesizeAction(summary=f"ERROR: {self._last_error}")

        return PauseAction(reason="solo_agent: no agent result yet")

    async def on_results(self, context: LoopContext, results: list[TaskResult]) -> None:
        if not results:
            return
        r = results[0]
        if r.error:
            self._last_error = r.error
            self._last_response = None
        else:
            self._last_response = r.response
            self._last_error = None

    async def on_inject(self, context: LoopContext, message: str) -> None:
        self._injections.append(message)

    # ── helpers ────────────────────────────────────────────────────────

    def _collect_seed(self, context: LoopContext) -> str:
        """Gather the iteration-0 instruction from user-typed messages.

        Two channels feed in:
        - ``context.messages`` with ``sender_type == 'user'`` — written by
          ``/run_agent`` (``message_type='user_inject'``) and by the
          consumer-app cron driver. These are NOT picked up by
          ``msg_repo.get_injections`` (which filters on ``'inject'``), so
          they only surface via the message history channel.
        - ``context.user_injections`` — populated from rows with
          ``message_type == 'inject'`` (operator-UI ``POST /labs/{id}/inject``).
        """
        parts: list[str] = []
        for m in context.messages:
            if m.sender_type == "user" and (m.content or "").strip():
                parts.append(m.content)
        for inj in context.user_injections:
            if inj and inj not in parts:
                parts.append(inj)
        return "\n\n".join(parts).strip()
