"""Bob Manager — Supervisor loop strategy.

Flow:
1. A primary "worker" agent executes the task.
2. A "supervisor" agent reviews each step and can approve, redirect,
   or request corrections.
3. The worker implements corrections and re-submits.
4. Repeat until the supervisor approves the final output.

Useful for high-stakes tasks that need quality gates.
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
    trim_results,
)

if TYPE_CHECKING:
    from app.models.orchestrator import Lab, LabAgent

logger = logging.getLogger(__name__)

SUPERVISOR_SYSTEM_PROMPT = """You are the Orchestrator of a multi-agent lab called "{lab_name}".
You coordinate agents using a Supervisor pattern.

## Your Role
You alternate between a WORKER and a SUPERVISOR:
1. **Work phase**: Dispatch the task to a worker agent.
2. **Review phase**: Send the worker's output to a supervisor agent for review.
3. **Correction phase**: If the supervisor rejects, send corrections back to the worker.
4. Repeat until the supervisor approves.

Assign agents as workers or supervisors based on their skills and roles.

You MUST respond ONLY with valid JSON. No extra text.

## Available Agents
{agent_descriptions}

## Response Schema
{{
  "reasoning": "Your assessment of the current phase",
  "phase": "work | review | correct | done",
  "tasks": [
    {{
      "agent": "Agent Name",
      "instruction": "Task or review instruction",
      "depends_on": []
    }}
  ],
  "done": false,
  "summary": null
}}

When the supervisor approves and the work is finalized:
{{
  "reasoning": "Supervisor approved the work. Quality requirements met.",
  "phase": "done",
  "tasks": [],
  "done": true,
  "summary": "Final approved output"
}}

## Rules
1. The worker agent should do the actual work (coding, writing, analysis).
2. The supervisor should ONLY review and provide feedback — not implement.
3. Pass the worker's FULL output to the supervisor, plus the original requirements.
4. Pass the supervisor's FULL feedback to the worker along with their previous work.
5. Usually 1–3 correction cycles are enough. Don't over-iterate.
6. NEVER set "done": true before the supervisor has reviewed at least once.
7. If you have 3+ agents, use one as supervisor and others as workers on different parts.
8. Respond with VALID JSON only.
9. Check <output_files> to avoid re-doing completed work.

## CRITICAL: You cannot act — only delegate
You are a COORDINATOR. You CANNOT execute tools, write files, run code, or perform any action yourself.
The ONLY way to get work done is by dispatching tasks to agents via the "tasks" array.
NEVER say you will do something and then set done=true without dispatching a task for it.
"""


class SupervisorStrategy(LoopStrategy):
    """Worker produces → supervisor reviews → corrections → repeat."""

    def __init__(self, **kwargs):
        self._last_results: list[TaskResult] = []
        self._injections: list[str] = []
        self._all_results: list[TaskResult] = []

    async def initialize(self, lab: Lab, agents: list[LabAgent]) -> None:
        self._last_results = []
        self._injections = []
        self._all_results = []

    async def next_step(self, context: LoopContext) -> LoopAction:
        from app.services.loop_strategies.plan_execute import _PendingLLMCall

        agent_descs = format_agents(context.agents)
        base = SUPERVISOR_SYSTEM_PROMPT.format(
            lab_name=context.lab.name,
            agent_descriptions=agent_descs,
        )
        system = build_strategy_system(base, context)

        # Include review history
        if self._all_results:
            system += "\n<review_history>\n"
            for r in self._all_results[-20:]:
                if r.error:
                    system += f"- {r.agent_name}: ERROR: {r.error}\n"
                else:
                    system += f"- {r.agent_name}: {r.response[:400]}\n"
            system += "</review_history>\n"

        messages = [{"role": "system", "content": system}]
        messages += build_messages_from_history(
            context, self._last_results, self._injections,
            prompt_suffix="Review the results. What's the next phase?",
            first_iter_prompt="Begin with the work phase. Assign the initial task to a worker agent.",
        )
        self._injections.clear()

        return _PendingLLMCall(messages=messages)

    async def on_results(self, context: LoopContext, results: list[TaskResult]) -> None:
        self._last_results = results
        self._all_results.extend(results)
        trim_results(self._all_results)

    async def on_inject(self, context: LoopContext, message: str) -> None:
        self._injections.append(message)
