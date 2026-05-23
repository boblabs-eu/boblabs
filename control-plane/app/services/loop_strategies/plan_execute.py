"""Bob Manager — Plan & Execute loop strategy.

The default strategy: Orchestrator decomposes the goal into sub-tasks,
dispatches them to agents, collects results, and decides whether to
continue or finalize.
"""

from __future__ import annotations

import json
import logging
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
    build_messages_from_history,
    build_strategy_system,
    format_agents,
)

if TYPE_CHECKING:
    from app.models.orchestrator import Lab, LabAgent

logger = logging.getLogger(__name__)

PLAN_SYSTEM_PROMPT = """You are the Orchestrator of a multi-agent lab called "{lab_name}".

## Your Role
You coordinate a team of specialized agents to accomplish the user's goal.
You MUST respond ONLY with valid JSON matching the schema below. No extra text.

## Available Agents
{agent_descriptions}

## Plan Schema
{{
  "reasoning": "Your step-by-step reasoning about what to do next",
  "tasks": [
    {{
      "agent": "Agent Name (must match exactly)",
      "instruction": "Clear, specific instruction for this agent",
      "depends_on": []
    }}
  ],
  "done": false,
  "summary": null
}}

When the goal is FULLY achieved and you have reviewed ALL agent results, respond with:
{{
  "reasoning": "Why the work is complete",
  "tasks": [],
  "done": true,
  "summary": "Final comprehensive answer to the user"
}}

## Rules
1. Break complex tasks into small, focused sub-tasks.
2. Each task targets exactly ONE agent by name.
3. Keep instructions specific and actionable.
4. Review agent results carefully before marking done.
5. If an agent's result is insufficient, create a follow-up task with clear corrections.
6. NEVER invent agents. Only use agents listed above.
7. Respond with VALID JSON only.
8. NEVER set "done": true on the first iteration. You MUST dispatch tasks to agents first.
9. ONLY set "done": true AFTER you have received and reviewed results from ALL agents you dispatched tasks to.
10. If you just dispatched tasks, you MUST set "done": false — you will see agent results in the next iteration.
11. Use ALL available agents when the task requires multiple perspectives or capabilities.
12. Check <output_files> to avoid re-doing work agents already completed.
13. If >50% of tasks failed, re-plan with clearer instructions before continuing.

## Task Dependencies
Tasks with empty "depends_on" run in parallel. Add agent names to "depends_on" to sequence tasks:
  {{"agent": "Researcher", "instruction": "...", "depends_on": []}}
  {{"agent": "Coder", "instruction": "Use Researcher's findings to...", "depends_on": ["Researcher"]}}

## CRITICAL: You cannot act — only delegate
You are a COORDINATOR. You CANNOT execute tools, write files, run code, or perform any action yourself.
The ONLY way to get work done is by dispatching tasks to agents via the "tasks" array.
NEVER say you will do something and then set done=true without dispatching a task for it.
"""


class PlanExecuteStrategy(LoopStrategy):
    """Orchestrator plans → agents execute → collect → decide → repeat."""

    def __init__(self, **kwargs):
        self._last_results: list[TaskResult] = []
        self._injections: list[str] = []

    async def initialize(self, lab: Lab, agents: list[LabAgent]) -> None:
        self._last_results = []
        self._injections = []

    async def next_step(self, context: LoopContext) -> LoopAction:
        agent_descs = format_agents(context.agents)
        base = PLAN_SYSTEM_PROMPT.format(
            lab_name=context.lab.name,
            agent_descriptions=agent_descs,
        )
        system = build_strategy_system(base, context)

        messages = [{"role": "system", "content": system}]
        messages += build_messages_from_history(
            context, self._last_results, self._injections,
        )
        self._injections.clear()

        return _PendingLLMCall(messages=messages)

    async def on_results(self, context: LoopContext, results: list[TaskResult]) -> None:
        self._last_results = results

    async def on_inject(self, context: LoopContext, message: str) -> None:
        self._injections.append(message)


class _PendingLLMCall:
    """Internal marker: the strategy needs an LLM call before deciding.

    The LabRunner will:
    1. Detect this marker
    2. Call the orchestrator LLM with these messages
    3. Parse the JSON response into a proper LoopAction
    """
    def __init__(self, messages: list[dict]):
        self.messages = messages


def parse_orchestrator_response(raw: str, *, iteration: int = 0, has_results: bool = False, has_pending_inject: bool = False) -> LoopAction:
    """Parse the orchestrator LLM's JSON response into a LoopAction.

    ``iteration`` and ``has_results`` are used as a safety check: the
    orchestrator must not mark ``done`` on the very first iteration or
    when no agent results have ever been received.
    """
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
        # Try to extract a valid JSON object. Some models leak chain-of-thought
        # prose around the JSON; we try from each '{' position and keep the
        # largest valid object found (preferring those near the end of text).
        decoder = json.JSONDecoder()
        candidates: list[dict] = []
        for i, ch in enumerate(text):
            if ch != "{":
                continue
            try:
                obj, _end = decoder.raw_decode(text[i:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                candidates.append(obj)
        # Prefer a candidate that looks like an orchestrator action.
        action_like = [
            c for c in candidates
            if any(k in c for k in ("done", "tasks", "reasoning", "summary"))
        ]
        if action_like:
            data = action_like[-1]
        elif candidates:
            data = candidates[-1]
        if data is None:
            logger.error("Failed to parse orchestrator response as JSON: %s", text[:200])
            return PauseAction(reason=f"Orchestrator produced invalid JSON: {text[:200]}")

    if data.get("done"):
        # Safety: don't allow done before any agent has reported back
        if iteration == 0 or not has_results:
            logger.warning(
                "Orchestrator tried to mark done at iteration %d (has_results=%s) — overriding",
                iteration, has_results,
            )
            # Re-interpret as a plan if tasks are present, else pause
            tasks_raw = data.get("tasks", [])
            if tasks_raw:
                return PlanAction(tasks=[
                    TaskItem(
                        agent_name=t.get("agent", ""),
                        instruction=t.get("instruction", ""),
                        depends_on=t.get("depends_on", []),
                    ) for t in tasks_raw
                ])
            return PauseAction(reason="Orchestrator tried to finish before agents responded. Waiting for results.")
        # Safety: don't allow done with no tasks right after a user inject
        if has_pending_inject and not data.get("tasks"):
            logger.warning(
                "Orchestrator tried to mark done without dispatching tasks after user inject — overriding (lab iteration %d)",
                iteration,
            )
            return PauseAction(
                reason="You received a user instruction but did not dispatch any tasks. "
                       "You CANNOT perform actions yourself — you must create tasks for agents. "
                       "Please re-read the user instruction and dispatch appropriate tasks."
            )
        return SynthesizeAction(summary=data.get("summary", ""))

    tasks = []
    for t in data.get("tasks", []):
        tasks.append(TaskItem(
            agent_name=t.get("agent", ""),
            instruction=t.get("instruction", ""),
            depends_on=t.get("depends_on", []),
        ))

    if not tasks:
        return PauseAction(reason="Orchestrator produced empty task list without marking done.")

    return PlanAction(tasks=tasks)
