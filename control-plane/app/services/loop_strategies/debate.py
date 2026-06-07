"""Bob Manager — Debate loop strategy.

Flow:
1. Orchestrator poses a question/task to multiple agents.
2. Each agent argues for their approach independently.
3. Agents see each other's arguments and provide rebuttals.
4. Orchestrator judges the debate and picks a winner or synthesizes
   the best elements from all sides.
5. Winning approach is optionally executed by the appropriate agent.
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

DEBATE_SYSTEM_PROMPT = """You are the Orchestrator of a multi-agent lab called "{lab_name}".
You run a Debate pattern where agents argue different approaches.

## Your Role
1. **Round 1 — Opening statements**: Ask each agent to propose their approach.
2. **Round 2+ — Rebuttals**: Share all proposals, ask agents to critique others' approaches.
3. **Judgment**: Evaluate arguments, pick the best approach or synthesize a hybrid.
4. **Execution**: Dispatch the winning approach to the appropriate agent(s) for implementation.

You MUST respond ONLY with valid JSON. No extra text.

## Available Agents
{agent_descriptions}

## Response Schema
{{
  "reasoning": "Your analysis of the debate so far",
  "phase": "propose | rebut | judge | execute | done",
  "tasks": [
    {{
      "agent": "Agent Name",
      "instruction": "Instruction for this agent",
      "depends_on": []
    }}
  ],
  "done": false,
  "summary": null
}}

When the debate is resolved and work is complete:
{{
  "reasoning": "Summary of winning argument and why",
  "phase": "done",
  "tasks": [],
  "done": true,
  "summary": "Final result — synthesized winning approach and its output"
}}

## Rules
1. Start with "propose" — have ALL agents state their approach.
2. In "rebut" — share ALL proposals and ask agents to critique each other.
3. Usually 1–2 rebuttal rounds are enough.
4. In "judge" — pick the winner or synthesize the best of each.
5. In "execute" — dispatch the chosen approach for implementation.
6. NEVER set "done": true before seeing proposals AND at least one rebuttal.
7. Respond with VALID JSON only.
8. Check <output_files> to avoid re-doing completed work.

## CRITICAL: You cannot act — only delegate
You are a COORDINATOR. You CANNOT execute tools, write files, run code, or perform any action yourself.
The ONLY way to get work done is by dispatching tasks to agents via the "tasks" array.
NEVER say you will do something and then set done=true without dispatching a task for it.
"""


class DebateStrategy(LoopStrategy):
    """Multi-agent debate → judge → execute."""

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
        base = DEBATE_SYSTEM_PROMPT.format(
            lab_name=context.lab.name,
            agent_descriptions=agent_descs,
        )
        system = build_strategy_system(base, context)

        # Include debate history in system for accumulated context
        if self._all_results:
            system += "\n<debate_history>\n"
            for r in self._all_results[-30:]:
                if r.error:
                    system += f"- {r.agent_name}: ERROR: {r.error}\n"
                else:
                    system += f"- {r.agent_name}: {r.response[:400]}\n"
            system += "</debate_history>\n"

        messages = [{"role": "system", "content": system}]
        messages += build_messages_from_history(
            context, self._last_results, self._injections,
            prompt_suffix="Review the arguments. What's the next phase of the debate?",
            first_iter_prompt="Begin the debate. Open with proposals from all agents.",
        )
        self._injections.clear()

        return _PendingLLMCall(messages=messages)

    async def on_results(self, context: LoopContext, results: list[TaskResult]) -> None:
        self._last_results = results
        self._all_results.extend(results)
        trim_results(self._all_results)

    async def on_inject(self, context: LoopContext, message: str) -> None:
        self._injections.append(message)
