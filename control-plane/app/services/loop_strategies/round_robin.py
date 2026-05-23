"""Bob Manager — Round Robin loop strategy.

Flow:
1. Orchestrator sends the task to each agent in order.
2. Each agent sees the accumulated results from previous agents.
3. After all agents have responded, the orchestrator decides whether
   to do another round or finalize.
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

ROUND_ROBIN_SYSTEM_PROMPT = """You are the Orchestrator of a multi-agent lab called "{lab_name}".
You coordinate agents in a Round Robin pattern.

## Your Role
Each iteration you send tasks to agents one at a time (or in small batches).
Each subsequent agent sees the accumulated results from all previous agents.
After a full round through all agents, you review and decide whether another round is needed.

You MUST respond ONLY with valid JSON. No extra text.

## Available Agents
{agent_descriptions}

## Response Schema
{{
  "reasoning": "Explain your round-robin orchestration logic",
  "round": 1,
  "tasks": [
    {{
      "agent": "Agent Name (must match exactly)",
      "instruction": "Instruction including context from previous agents if applicable",
      "depends_on": []
    }}
  ],
  "done": false,
  "summary": null
}}

When all rounds are complete and the goal is met:
{{
  "reasoning": "Why no more rounds are needed",
  "round": 2,
  "tasks": [],
  "done": true,
  "summary": "Final synthesized answer combining all agent contributions"
}}

## Rules
1. In each iteration, send a task to ONE or a FEW agents (not all at once in round 1).
2. Include relevant context from previous agents' results in the instruction.
3. Cycle through all agents before starting a new round.
4. NEVER set "done": true on the first pass through agents.
5. ONLY set "done": true after you have seen results from ALL agents at least once.
6. Keep track of which agents have responded and which haven't.
7. Respond with VALID JSON only.
8. Check <output_files> to avoid re-doing work agents already completed.

## CRITICAL: You cannot act — only delegate
You are a COORDINATOR. You CANNOT execute tools, write files, run code, or perform any action yourself.
The ONLY way to get work done is by dispatching tasks to agents via the "tasks" array.
NEVER say you will do something and then set done=true without dispatching a task for it.
"""


class RoundRobinStrategy(LoopStrategy):
    """Agent-by-agent round robin with accumulated context."""

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
        base = ROUND_ROBIN_SYSTEM_PROMPT.format(
            lab_name=context.lab.name,
            agent_descriptions=agent_descs,
        )
        system = build_strategy_system(base, context)

        # Append accumulated results from all rounds
        if self._all_results:
            system += "\n<accumulated_results>\n"
            for r in self._all_results[-20:]:
                if r.error:
                    system += f"- {r.agent_name}: ERROR: {r.error}\n"
                else:
                    system += f"- {r.agent_name}: {r.response[:300]}\n"
            system += "</accumulated_results>\n"

        messages = [{"role": "system", "content": system}]
        messages += build_messages_from_history(
            context, self._last_results, self._injections,
            prompt_suffix="Continue the round robin. Who's next?",
        )
        self._injections.clear()

        return _PendingLLMCall(messages=messages)

    async def on_results(self, context: LoopContext, results: list[TaskResult]) -> None:
        self._last_results = results
        self._all_results.extend(results)

    async def on_inject(self, context: LoopContext, message: str) -> None:
        self._injections.append(message)
