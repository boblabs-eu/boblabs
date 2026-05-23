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


def parse_workflow_string(content: str, fmt: str = "yaml") -> dict[str, Any]:
    """Parse a workflow definition from a string.

    Args:
        content: Workflow content.
        fmt: 'yaml' or 'json'.

    Returns:
        Validated workflow dict.
    """
    if fmt == "yaml":
        data = yaml.safe_load(content)
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
