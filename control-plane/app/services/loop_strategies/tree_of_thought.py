"""Bob Manager — Tree of Thought loop strategy.

Flow:
1. Orchestrator generates multiple initial approaches (branches).
2. Each branch is explored by an agent for one step.
3. Orchestrator evaluates all branches, prunes weak ones, and
   expands promising ones.
4. Repeat until one branch reaches a satisfactory solution.
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

TREE_OF_THOUGHT_SYSTEM_PROMPT = """You are the Orchestrator of a multi-agent lab called "{lab_name}".
You coordinate agents using a Tree of Thought pattern.

## Your Role
Explore multiple solution paths simultaneously:
1. **Branch**: Generate 2–4 distinct approaches to the problem.
2. **Explore**: Dispatch each approach to an agent for one step of execution.
3. **Evaluate**: Review all branch results. Score each branch (0–10) for viability.
4. **Prune & Expand**: Drop branches scoring ≤3. Expand branches ≥7. Optionally fork good branches.
5. **Converge**: When one branch clearly leads, follow it to completion.

You MUST respond ONLY with valid JSON. No extra text.

## Available Agents
{agent_descriptions}

## Response Schema
{{
  "reasoning": "Analysis of all active branches and their viability",
  "phase": "branch | explore | evaluate | converge | done",
  "branches": [
    {{
      "id": "A",
      "description": "Short description of this approach",
      "score": 7,
      "status": "active | pruned | converged"
    }}
  ],
  "tasks": [
    {{
      "agent": "Agent Name",
      "instruction": "Explore branch A: <specific instruction>",
      "depends_on": []
    }}
  ],
  "done": false,
  "summary": null
}}

When the winning branch is complete:
{{
  "reasoning": "Branch X converged successfully with score 9/10",
  "phase": "done",
  "branches": [...],
  "tasks": [],
  "done": true,
  "summary": "Final result from the winning branch"
}}

## Rules
1. Start with 2–4 branches exploring different approaches.
2. Each branch should be meaningfully different, not trivial variations.
3. Always evaluate and score branches explicitly before expanding.
4. Prune branches with score ≤3 to save budget.
5. NEVER prune ALL branches — at least one must survive.
6. NEVER set "done": true before exploring at least 2 branches.
7. Respond with VALID JSON only.
8. Check <output_files> to avoid re-doing completed work.

## CRITICAL: You cannot act — only delegate
You are a COORDINATOR. You CANNOT execute tools, write files, run code, or perform any action yourself.
The ONLY way to get work done is by dispatching tasks to agents via the "tasks" array.
NEVER say you will do something and then set done=true without dispatching a task for it.
"""


class TreeOfThoughtStrategy(LoopStrategy):
    """Branching exploration with evaluation and pruning."""

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
        base = TREE_OF_THOUGHT_SYSTEM_PROMPT.format(
            lab_name=context.lab.name,
            agent_descriptions=agent_descs,
        )
        system = build_strategy_system(base, context)

        # Provide exploration history
        if self._all_results:
            system += "\n<exploration_history>\n"
            for r in self._all_results[-30:]:
                if r.error:
                    system += f"- {r.agent_name}: ERROR: {r.error}\n"
                else:
                    system += f"- {r.agent_name}: {r.response[:400]}\n"
            system += "</exploration_history>\n"

        messages = [{"role": "system", "content": system}]
        messages += build_messages_from_history(
            context,
            self._last_results,
            self._injections,
            prompt_suffix="Evaluate branches. Which to prune, expand, or converge?",
            first_iter_prompt="Begin with the branching phase. Propose 2-4 distinct approaches.",
        )
        self._injections.clear()

        return _PendingLLMCall(messages=messages)

    async def on_results(self, context: LoopContext, results: list[TaskResult]) -> None:
        self._last_results = results
        self._all_results.extend(results)
        trim_results(self._all_results)

    async def on_inject(self, context: LoopContext, message: str) -> None:
        self._injections.append(message)
