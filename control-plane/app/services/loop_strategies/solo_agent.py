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
        self._seed_parts: set[str] = set()

    async def initialize(self, lab: "Lab", agents: list["LabAgent"]) -> None:
        if len(agents) != 1:
            raise ValueError(
                f"solo_agent requires exactly 1 LabAgent on lab {lab.id}, got {len(agents)}"
            )
        self._target_name = agents[0].name
        self._last_response = None
        self._last_error = None
        self._injections = []
        self._seed_parts = set()

    async def next_step(self, context: LoopContext) -> LoopAction:
        # Iteration 0: dispatch the seed (user-typed messages + any standing injections)
        if context.iteration == 0:
            seed = self._collect_seed(context)
            if not seed:
                return PauseAction(reason="solo_agent: no initial user message")
            return PlanAction(tasks=[TaskItem(agent_name=self._target_name, instruction=seed)])

        # Subsequent iterations: dispatch any new mid-run injection.
        # The runner delivers injection rows through BOTH channels — on_inject
        # (queued here) and context.user_injections (consumed by the iteration-0
        # seed) — so the seed's own texts re-surface in self._injections at
        # iteration 1. Filter them out or the agent gets the same task twice
        # (harmless-but-wasteful for native agents, actively harmful for
        # stateful backends like Hermes whose session is interrupted/redone).
        if self._injections:
            pending = [
                i for i in self._injections if i.strip() and i.strip() not in self._seed_parts
            ]
            self._injections.clear()
            if pending:
                return PlanAction(
                    tasks=[TaskItem(agent_name=self._target_name, instruction="\n\n".join(pending))]
                )

        # No new input — emit the agent's last response as the final answer
        if self._last_response is not None:
            return SynthesizeAction(summary=self._last_response)
        if self._last_error is not None:
            return SynthesizeAction(summary=f"ERROR: {self._last_error}")

        # Fresh runner resumed at iteration >= 1 (inject into a completed
        # instance): the iteration-0 seed never ran in THIS runner, and the
        # message may not surface via on_inject at all (rows written as
        # message_type='user_inject' are invisible to get_injections). Seed
        # from user messages newer than the lab's last result/synthesis —
        # same cut-off as _collect_seed. Self-limiting: once a task result
        # lands, _last_response/_last_error is set and this branch is dead.
        unanswered = self._collect_unanswered(context)
        if unanswered:
            return PlanAction(
                tasks=[TaskItem(agent_name=self._target_name, instruction=unanswered)]
            )

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

    def _collect_unanswered(self, context: LoopContext) -> str:
        """User messages newer than the lab's last result/synthesis.

        Resume-only path: a runner spawned by injecting into a completed
        lab starts at iteration >= 1, so ``_collect_seed`` never runs.
        Everything at-or-before the last result/synthesis was answered in
        a prior run and must NOT be re-sent (stateful backends like Hermes
        already hold the conversation in their session).
        """
        last_done_idx = -1
        for i, m in enumerate(context.messages):
            if (m.sender_type == "agent" and m.message_type == "result") or (
                m.message_type == "synthesis"
            ):
                last_done_idx = i
        parts = [
            m.content
            for i, m in enumerate(context.messages)
            if i > last_done_idx and m.sender_type == "user" and (m.content or "").strip()
        ]
        return "\n\n".join(parts).strip()

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
        # Only seed with user content NEWER than the last agent result.
        # Injecting into a completed lab restarts the runner at iteration 0,
        # and without this cut-off the seed re-collects every historical user
        # message — re-sending already-answered tasks (wasteful for native
        # agents, actively confusing for stateful backends like Hermes that
        # would redo the old task instead of reading the new message).
        last_result_idx = -1
        for i, m in enumerate(context.messages):
            if m.sender_type == "agent" and m.message_type == "result":
                last_result_idx = i

        parts: list[str] = []
        answered: set[str] = set()
        for i, m in enumerate(context.messages):
            if m.sender_type == "user" and (m.content or "").strip():
                if i > last_result_idx:
                    parts.append(m.content)
                else:
                    answered.add(m.content.strip())
        for inj in context.user_injections:
            # Injection rows also appear as user messages above; this channel
            # only back-fills rows outside the recent-messages window — skip
            # anything already collected or already answered in a prior run.
            if inj and inj not in parts and inj.strip() not in answered:
                parts.append(inj)
        # Remember the seed's constituent texts so the duplicate on_inject
        # deliveries of the same rows are dropped at iteration 1 (see next_step).
        self._seed_parts = {p.strip() for p in parts if p.strip()} | answered
        return "\n\n".join(parts).strip()
