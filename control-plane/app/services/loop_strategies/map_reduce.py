"""Bob Manager — Map-Reduce loop strategy.

Flow:
1. Orchestrator splits the task into independent, parallelizable chunks (MAP).
2. Each chunk is dispatched to an agent.
3. All agent results are collected.
4. A reducer agent (or the orchestrator) combines the results (REDUCE).
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

MAP_REDUCE_SYSTEM_PROMPT = """You are the Orchestrator of a multi-agent lab called "{lab_name}".
You coordinate agents in a Map-Reduce pattern.

## Your Role
1. **MAP phase**: Split the task into independent chunks. Dispatch each chunk to an agent (all run in parallel).
2. **REDUCE phase**: Once all map tasks complete, dispatch a "reduce" task to a single agent to combine/synthesize all results.

You MUST respond ONLY with valid JSON. No extra text.

## Available Agents
{agent_descriptions}

## Response Schema
{{
  "reasoning": "Explain your map-reduce logic",
  "phase": "map | reduce | done",
  "tasks": [
    {{
      "agent": "Agent Name",
      "instruction": "Clear chunk instruction or reduce instruction",
      "depends_on": []
    }}
  ],
  "done": false,
  "summary": null
}}

When reduce is complete:
{{
  "reasoning": "Map-reduce complete — results synthesized",
  "phase": "done",
  "tasks": [],
  "done": true,
  "summary": "Final combined result from the reduce step"
}}

## Rules
1. In MAP, create multiple parallel tasks — one per chunk. Use empty `depends_on`.
2. In REDUCE, create ONE task that receives all MAP outputs. Include all MAP agent names in `depends_on`.
3. MAP tasks should be independent — no task should depend on another MAP task.
4. The reducer should receive a clear summary of ALL map results in its instruction.
5. NEVER set "done": true before the REDUCE step has completed.
6. If the task cannot be parallelized, fall back to sequential planning.
7. Respond with VALID JSON only.
8. Check <output_files> to avoid re-doing completed work.

## CRITICAL: You cannot act — only delegate
You are a COORDINATOR. You CANNOT execute tools, write files, run code, or perform any action yourself.
The ONLY way to get work done is by dispatching tasks to agents via the "tasks" array.
NEVER say you will do something and then set done=true without dispatching a task for it.
"""


class MapReduceStrategy(LoopStrategy):
    """Split → parallel map → reduce → done."""

    def __init__(self, **kwargs):
        self._last_results: list[TaskResult] = []
        self._injections: list[str] = []

    async def initialize(self, lab: Lab, agents: list[LabAgent]) -> None:
        self._last_results = []
        self._injections = []

    async def next_step(self, context: LoopContext) -> LoopAction:
        from app.services.loop_strategies.plan_execute import _PendingLLMCall

        agent_descs = format_agents(context.agents)
        base = MAP_REDUCE_SYSTEM_PROMPT.format(
            lab_name=context.lab.name,
            agent_descriptions=agent_descs,
        )
        system = build_strategy_system(base, context)

        messages = [{"role": "system", "content": system}]
        messages += build_messages_from_history(
            context, self._last_results, self._injections,
            prompt_suffix="MAP results are in. Proceed with REDUCE or plan another MAP if needed.",
            first_iter_prompt="Begin the MAP phase. Split the task into parallel chunks.",
        )
        self._injections.clear()

        return _PendingLLMCall(messages=messages)

    async def on_results(self, context: LoopContext, results: list[TaskResult]) -> None:
        self._last_results = results

    async def on_inject(self, context: LoopContext, message: str) -> None:
        self._injections.append(message)
