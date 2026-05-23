"""Tool domain modules — auto-discovery.

Each ``tool_*.py`` file in this package exports two dicts:

    TOOLS: dict[str, dict]
        Tool-name → JSON-schema descriptor.

    HANDLERS: dict[str, Callable[[ToolExecutor, dict], Awaitable[dict]]]
        Tool-name → async handler that receives (executor, args) and returns
        {"success": bool, "output": str, ...}.

Adding a new built-in tool = creating (or editing) a ``tool_*.py`` file.
"""

import importlib
import pkgutil
from typing import Any, Callable

BUILTIN_TOOLS: dict[str, dict[str, Any]] = {}
TOOL_HANDLERS: dict[str, Callable] = {}


def _discover() -> None:
    for _importer, modname, _ispkg in pkgutil.iter_modules(__path__):
        if not modname.startswith("tool_"):
            continue
        mod = importlib.import_module(f"{__name__}.{modname}")
        for name, schema in getattr(mod, "TOOLS", {}).items():
            if name in BUILTIN_TOOLS:
                raise ValueError(f"Duplicate tool '{name}' registered in {modname}")
            BUILTIN_TOOLS[name] = schema
        for name, handler in getattr(mod, "HANDLERS", {}).items():
            if name in TOOL_HANDLERS:
                raise ValueError(f"Duplicate handler '{name}' registered in {modname}")
            TOOL_HANDLERS[name] = handler


_discover()
