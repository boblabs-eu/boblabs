"""Loop strategy registry — maps loop_type strings to strategy classes."""

from __future__ import annotations

from typing import Any

from app.services.loop_strategies.base import LoopStrategy
from app.services.loop_strategies.critique_refine import CritiqueRefineStrategy
from app.services.loop_strategies.debate import DebateStrategy
from app.services.loop_strategies.map_reduce import MapReduceStrategy
from app.services.loop_strategies.parallel_broadcast import ParallelBroadcastStrategy
from app.services.loop_strategies.plan_execute import PlanExecuteStrategy
from app.services.loop_strategies.react import ReActStrategy
from app.services.loop_strategies.round_robin import RoundRobinStrategy
from app.services.loop_strategies.solo_agent import SoloAgentStrategy
from app.services.loop_strategies.supervisor import SupervisorStrategy
from app.services.loop_strategies.tree_of_thought import TreeOfThoughtStrategy

STRATEGY_REGISTRY: dict[str, type[LoopStrategy]] = {
    "plan_execute": PlanExecuteStrategy,
    "critique_refine": CritiqueRefineStrategy,
    "round_robin": RoundRobinStrategy,
    "debate": DebateStrategy,
    "map_reduce": MapReduceStrategy,
    "parallel_broadcast": ParallelBroadcastStrategy,
    "tree_of_thought": TreeOfThoughtStrategy,
    "react": ReActStrategy,
    "supervisor": SupervisorStrategy,
    "solo_agent": SoloAgentStrategy,
}


def get_strategy(loop_type: str, loop_config: dict[str, Any] | None = None) -> LoopStrategy:
    """Instantiate the strategy for the given loop_type.

    Raises ValueError if the loop_type is not registered.
    """
    cls = STRATEGY_REGISTRY.get(loop_type)
    if cls is None:
        available = ", ".join(sorted(STRATEGY_REGISTRY.keys()))
        raise ValueError(f"Unknown loop_type '{loop_type}'. Available: {available}")
    config = loop_config or {}
    return cls(**config)


def register_strategy(loop_type: str, cls: type[LoopStrategy]) -> None:
    """Register a new strategy class. Overwrites if exists."""
    STRATEGY_REGISTRY[loop_type] = cls


# ── Strategy prompt defaults ──────────────────────

_PROMPT_REGISTRY: dict[str, str] = {}


def _load_prompts() -> None:
    """Lazily populate the prompt registry from strategy modules."""
    if _PROMPT_REGISTRY:
        return
    from app.services.loop_strategies.plan_execute import PLAN_SYSTEM_PROMPT
    from app.services.loop_strategies.critique_refine import CRITIQUE_SYSTEM_PROMPT
    from app.services.loop_strategies.round_robin import ROUND_ROBIN_SYSTEM_PROMPT
    from app.services.loop_strategies.debate import DEBATE_SYSTEM_PROMPT
    from app.services.loop_strategies.map_reduce import MAP_REDUCE_SYSTEM_PROMPT
    from app.services.loop_strategies.parallel_broadcast import PARALLEL_BROADCAST_SYSTEM_PROMPT
    from app.services.loop_strategies.tree_of_thought import TREE_OF_THOUGHT_SYSTEM_PROMPT
    from app.services.loop_strategies.react import REACT_SYSTEM_PROMPT
    from app.services.loop_strategies.supervisor import SUPERVISOR_SYSTEM_PROMPT

    _PROMPT_REGISTRY.update({
        "plan_execute": PLAN_SYSTEM_PROMPT,
        "critique_refine": CRITIQUE_SYSTEM_PROMPT,
        "round_robin": ROUND_ROBIN_SYSTEM_PROMPT,
        "debate": DEBATE_SYSTEM_PROMPT,
        "map_reduce": MAP_REDUCE_SYSTEM_PROMPT,
        "parallel_broadcast": PARALLEL_BROADCAST_SYSTEM_PROMPT,
        "tree_of_thought": TREE_OF_THOUGHT_SYSTEM_PROMPT,
        "react": REACT_SYSTEM_PROMPT,
        "supervisor": SUPERVISOR_SYSTEM_PROMPT,
    })


def get_strategy_prompt(loop_type: str) -> str | None:
    """Return the default system prompt for a given strategy type."""
    _load_prompts()
    return _PROMPT_REGISTRY.get(loop_type)


# ── Strategy metadata (display label + description) ──
# Single source of truth for the human-friendly UI copy. The frontend dropdown
# is populated from this list via GET /api/v1/labs/strategies — DO NOT
# hardcode strategy lists in the frontend.

STRATEGY_METADATA: dict[str, dict[str, str]] = {
    "plan_execute": {
        "label": "Plan & Execute",
        "description": "Orchestrator plans steps then dispatches them to agents.",
    },
    "critique_refine": {
        "label": "Critique & Refine",
        "description": "One agent drafts; a critic refines iteratively.",
    },
    "round_robin": {
        "label": "Round Robin",
        "description": "Agents speak in turn until completion.",
    },
    "debate": {
        "label": "Debate",
        "description": "Agents argue opposing views; orchestrator synthesizes.",
    },
    "map_reduce": {
        "label": "Map-Reduce",
        "description": "Split the task in parallel sub-tasks then merge results.",
    },
    "parallel_broadcast": {
        "label": "Parallel Broadcast (no orchestrator)",
        "description": "All agents run in parallel on the same input. No orchestrator.",
    },
    "tree_of_thought": {
        "label": "Tree of Thought",
        "description": "Branching exploration of multiple reasoning paths.",
    },
    "react": {
        "label": "ReAct",
        "description": "Reasoning + acting loop with explicit thought / action / observation.",
    },
    "supervisor": {
        "label": "Supervisor",
        "description": "Supervisor agent routes work to specialist sub-agents.",
    },
    "solo_agent": {
        "label": "Solo Agent",
        "description": "Single LabAgent driven directly via native tool-calling. No orchestrator JSON layer — used by solo instances and /run_agent.",
    },
}


def list_strategies() -> list[dict[str, str]]:
    """Return all registered strategies with display metadata for the UI."""
    out: list[dict[str, str]] = []
    for loop_type in STRATEGY_REGISTRY:
        meta = STRATEGY_METADATA.get(loop_type, {})
        out.append({
            "loop_type": loop_type,
            "label": meta.get("label", loop_type.replace("_", " ").title()),
            "description": meta.get("description", ""),
        })
    return out
