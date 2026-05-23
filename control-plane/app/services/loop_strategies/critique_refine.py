"""Bob Manager — Critique & Refine loop strategy.

Flow:
1. Orchestrator assigns a task to a "creator" agent.
2. A "critic" agent reviews the output and provides feedback.
3. The creator refines the work using the critique.
4. Repeat until the orchestrator is satisfied.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.loop_strategies.base import (
    LoopAction,
    LoopContext,
    LoopStrategy,
    TaskResult,
    build_messages_from_history,
    build_strategy_system,
    format_agents,
)

if TYPE_CHECKING:
    from app.models.orchestrator import Lab, LabAgent

logger = logging.getLogger(__name__)

CRITIQUE_SYSTEM_PROMPT = """You are the Orchestrator of a multi-agent lab called "{lab_name}".
You coordinate agents in a Critique & Refine loop.

## Your Role
You assign tasks using a produce → critique → refine cycle:
  1. A "creator" agent produces work.
  2. A "critic" agent reviews the output and gives specific, actionable feedback.
  3. The creator refines the work based on the critique.
  4. Repeat until quality is satisfactory.

You MUST respond ONLY with valid JSON. No extra text.

## Available Agents
{agent_descriptions}

## Response Schema
{{
  "reasoning": "Explain what phase you're in and what you expect next",
  "phase": "create | critique | refine | done",
  "tasks": [
    {{
      "agent": "Agent Name (must match exactly)",
      "instruction": "Clear instruction for this agent",
      "depends_on": []
    }}
  ],
  "done": false,
  "summary": null
}}

When refinement is complete, respond with:
{{
  "reasoning": "Why the work meets the quality bar",
  "phase": "done",
  "tasks": [],
  "done": true,
  "summary": "Final polished result"
}}

## Rules
1. Start with a "create" phase — assign the initial task.
2. After creation, enter "critique" phase — have a different agent review.
3. After critique, enter "refine" phase — send feedback to the creator.
4. Repeat critique → refine until quality is good enough (usually 1-3 cycles).
5. NEVER set "done": true until you have seen at least one create AND one critique result.
6. Use ALL available agents strategically as creators or critics.
7. Respond with VALID JSON only.
8. Check <output_files> to avoid re-doing work agents already completed.

## CRITICAL: You cannot act — only delegate
You are a COORDINATOR. You CANNOT execute tools, write files, run code, or perform any action yourself.
The ONLY way to get work done is by dispatching tasks to agents via the "tasks" array.
NEVER say you will do something and then set done=true without dispatching a task for it.
"""


class CritiqueRefineStrategy(LoopStrategy):
    """Produce → critique → refine → repeat."""

    def __init__(self, **kwargs):
        self._last_results: list[TaskResult] = []
        self._injections: list[str] = []

    async def initialize(self, lab: Lab, agents: list[LabAgent]) -> None:
        self._last_results = []
        self._injections = []

    async def next_step(self, context: LoopContext) -> LoopAction:
        from app.services.loop_strategies.plan_execute import _PendingLLMCall

        agent_descs = format_agents(context.agents)
        base = CRITIQUE_SYSTEM_PROMPT.format(
            lab_name=context.lab.name,
            agent_descriptions=agent_descs,
        )
        system = build_strategy_system(base, context)

        messages = [{"role": "system", "content": system}]
        messages += build_messages_from_history(
            context, self._last_results, self._injections,
            prompt_suffix="Continue the critique & refine cycle. What's next?",
        )
        self._injections.clear()

        return _PendingLLMCall(messages=messages)

    async def on_results(self, context: LoopContext, results: list[TaskResult]) -> None:
        self._last_results = results

    async def on_inject(self, context: LoopContext, message: str) -> None:
        self._injections.append(message)
