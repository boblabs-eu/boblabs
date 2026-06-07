"""Bob Manager — Workflow YAML/JSON parser."""

import json
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def parse_workflow_file(file_path: str) -> dict[str, Any]:
    """Parse a workflow definition from a YAML or JSON file.

    Args:
        file_path: Path to the workflow file.

    Returns:
        Parsed workflow dict with 'name', 'description', 'steps'.

    Raises:
        ValueError: If the file format is invalid.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Workflow file not found: {file_path}")

    content = path.read_text()

    if path.suffix in (".yml", ".yaml"):
        data = yaml.safe_load(content)
    elif path.suffix == ".json":
        data = json.loads(content)
    else:
        raise ValueError(f"Unsupported file format: {path.suffix}")

    return _validate_workflow(data)


class _NoAliasSafeLoader(yaml.SafeLoader):
    """D13 — block YAML anchors / aliases at parse time.

    ``yaml.safe_load`` is safe against arbitrary code execution but
    NOT against the billion-laughs / alias-bomb attack: a tiny
    document with deeply nested ``*`` references expands to gigabytes
    of in-memory dict on load. Workflow definitions never need
    anchors (steps are flat ordered lists), so we refuse them at
    load time and surface a clear error to the operator.
    """


def _reject_anchor(loader, node):
    raise yaml.constructor.ConstructorError(
        None, None,
        "YAML anchors and aliases are not allowed in workflow definitions "
        "(D13 — alias-bomb / billion-laughs guard).",
        node.start_mark,
    )


# Wire the rejector for every node kind ``*`` could reference.
_NoAliasSafeLoader.add_constructor("!", _reject_anchor)
_NoAliasSafeLoader.add_constructor(None, _reject_anchor)


def _safe_load_no_anchors(content: str):
    # PyYAML resolves `*alias` references during compose-step, so the
    # constructor hooks above can't see them by themselves. Subclass
    # the composer to refuse aliases at compose-time.
    loader = _NoAliasSafeLoader(content)
    try:
        # Walk the event stream and reject AliasEvent before composition.
        # PyYAML's compose() returns the root node; if there's an alias
        # in the stream, compose_node raises.
        original_compose_node = loader.compose_node

        def guarded_compose_node(parent, index):
            if loader.check_event(yaml.AliasEvent):
                event = loader.peek_event()
                raise yaml.constructor.ConstructorError(
                    None, None,
                    "YAML aliases (*ref) are not allowed in workflow "
                    "definitions (D13 — alias-bomb guard).",
                    event.start_mark,
                )
            return original_compose_node(parent, index)

        loader.compose_node = guarded_compose_node  # type: ignore[assignment]
        return loader.get_single_data()
    finally:
        loader.dispose()


def parse_workflow_string(content: str, fmt: str = "yaml") -> dict[str, Any]:
    """Parse a workflow definition from a string.

    Args:
        content: Workflow content.
        fmt: 'yaml' or 'json'.

    Returns:
        Validated workflow dict.
    """
    if fmt == "yaml":
        # D13 — refuse alias-bomb payloads.
        data = _safe_load_no_anchors(content)
    else:
        data = json.loads(content)

    return _validate_workflow(data)


def _validate_workflow(data: dict) -> dict[str, Any]:
    """Validate and normalize a workflow definition."""
    if not isinstance(data, dict):
        raise ValueError("Workflow must be a dict/mapping")

    name = data.get("workflow") or data.get("name")
    if not name:
        raise ValueError("Workflow must have a 'name' or 'workflow' field")

    steps = data.get("steps", [])
    if not steps:
        raise ValueError("Workflow must have at least one step")

    validated_steps = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"Step {i} must be a dict")

        step_name = step.get("name", f"step-{i+1}")
        command = step.get("run") or step.get("command")
        if not command:
            raise ValueError(f"Step '{step_name}' must have a 'run' or 'command' field")

        validated_steps.append({
            "name": step_name,
            "command": command,
            "timeout_seconds": step.get("timeout", step.get("timeout_seconds", 300)),
            "continue_on_error": step.get("continue_on_error", False),
        })

    return {
        "name": name,
        "description": data.get("description", ""),
        "steps": validated_steps,
    }
