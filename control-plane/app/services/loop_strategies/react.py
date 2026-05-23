"""Bob Manager — ReAct loop strategy.

Flow (Reasoning + Acting):
1. Orchestrator THINKS about what to do (reasoning step).
2. Orchestrator dispatches an ACTION to an agent.
3. Orchestrator OBSERVES the result.
4. Repeat Think → Act → Observe until goal is met.

This is a tight, single-agent-at-a-time loop optimized for tasks that
need careful step-by-step reasoning with tool use.
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

REACT_SYSTEM_PROMPT = """You are the Orchestrator of a multi-agent lab called "{lab_name}".
You follow the ReAct (Reasoning + Acting) pattern.

## Your Role
Each iteration you do THREE things:
1. **Thought**: Reason about what information you have and what you still need.
2. **Action**: Dispatch EXACTLY ONE task to ONE agent.
3. **Observation**: (Next iteration) Review the result and think again.

You MUST respond ONLY with valid JSON. No extra text.

## Available Agents
{agent_descriptions}

## Response Schema
{{
  "thought": "Your detailed reasoning about the current state and what action to take",
  "tasks": [
    {{
      "agent": "Agent Name",
      "instruction": "Specific action for this agent",
      "depends_on": []
    }}
  ],
  "done": false,
  "summary": null
}}

When the goal is fully achieved:
{{
  "thought": "I have gathered/produced everything needed. The goal is complete because...",
  "tasks": [],
  "done": true,
  "summary": "Final comprehensive answer"
}}

## Rules
1. Dispatch EXACTLY ONE task per iteration (single-action loop).
2. Your "thought" must explain WHY you chose this specific action.
3. Think step by step — don't skip ahead.
4. Each observation (agent result) informs the next thought.
5. NEVER set "done": true before you have seen at least one agent result.
6. If an action fails, reason about WHY and try a different approach.
7. Respond with VALID JSON only.
8. Check <output_files> to track what has been produced so far.

## CRITICAL: You cannot act — only delegate
You are a COORDINATOR. You CANNOT execute tools, write files, run code, or perform any action yourself.
The ONLY way to get work done is by dispatching tasks to agents via the "tasks" array.
NEVER say you will do something and then set done=true without dispatching a task for it.
"""


class ReActStrategy(LoopStrategy):
    """Think → Act → Observe, one step at a time."""

    def __init__(self, **kwargs):
        self._last_results: list[TaskResult] = []
        self._injections: list[str] = []
        self._trace: list[dict] = []  # reasoning trace

    async def initialize(self, lab: Lab, agents: list[LabAgent]) -> None:
        self._last_results = []
        self._injections = []
        self._trace = []

    async def next_step(self, context: LoopContext) -> LoopAction:
        from app.services.loop_strategies.plan_execute import _PendingLLMCall

        agent_descs = format_agents(context.agents)
        base = REACT_SYSTEM_PROMPT.format(
            lab_name=context.lab.name,
            agent_descriptions=agent_descs,
        )
        system = build_strategy_system(base, context)

        # Include reasoning trace for continuity
        if self._trace:
            system += "\n<reasoning_trace>\n"
            for step in self._trace[-10:]:
                system += f"Step {step['step']}: Thought: {step['thought']}\n"
                system += f"  Action → {step['agent']}: {step['instruction'][:200]}\n"
                if step.get("observation"):
                    system += f"  Observation: {step['observation'][:300]}\n"
            system += "</reasoning_trace>\n"

        messages = [{"role": "system", "content": system}]
        messages += build_messages_from_history(
            context, self._last_results, self._injections,
            prompt_suffix="Observe the result. Think, then choose your next action.",
            first_iter_prompt="Begin reasoning. What is the first step to achieve the goal?",
        )
        self._injections.clear()

        return _PendingLLMCall(messages=messages)

    async def on_results(self, context: LoopContext, results: list[TaskResult]) -> None:
        self._last_results = results
        # Record observation in trace
        for r in results:
            if self._trace:
                self._trace[-1]["observation"] = r.response[:500] if not r.error else f"ERROR: {r.error}"
            self._trace.append({
                "step": len(self._trace) + 1,
                "thought": "(pending)",
                "agent": r.agent_name,
                "instruction": r.instruction,
            })

    async def on_inject(self, context: LoopContext, message: str) -> None:
        self._injections.append(message)
