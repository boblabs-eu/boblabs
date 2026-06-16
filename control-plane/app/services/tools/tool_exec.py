"""Sandboxed code execution tools: python_exec, shell_exec."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from app.services.sandbox_client import signed_post_json

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

TOOLS = {
    "python_exec": {
        "description": "Execute Python code in a sandboxed environment. Returns stdout and stderr.",
        "parameters": {
            "code": {"type": "string", "description": "Python code to execute", "required": True},
        },
    },
    "shell_exec": {
        "description": "Execute a whitelisted shell command. Allowed: mkdir,curl, wget, python3, pip, cat, head, tail, grep, awk, sed, sort, ls, find, jq, etc.",
        "parameters": {
            "command": {
                "type": "string",
                "description": "Shell command to execute",
                "required": True,
            },
        },
    },
}


async def python_exec(executor: ToolExecutor, args: dict) -> dict:
    code = args.get("code", "")
    if not code:
        return {"success": False, "output": "python_exec requires 'code'"}

    try:
        sandbox_url = await executor.get_sandbox_url()
        return await signed_post_json(
            sandbox_url,
            "/python_exec",
            {
                "lab_id": str(executor.lab_id),
                "code": code,
                "timeout_sec": executor.timeout_sec,
                "max_output_kb": executor.max_output_bytes // 1024,
            },
            timeout=executor.timeout_sec + 5,
        )
    except httpx.TimeoutException:
        return {
            "success": False,
            "output": f"Python execution timed out after {executor.timeout_sec}s",
        }
    except Exception as e:
        logger.exception("Sandbox python_exec failed for lab %s", executor.lab_id)
        return {"success": False, "output": f"Sandbox error: {e}"}


async def shell_exec(executor: ToolExecutor, args: dict) -> dict:
    command = args.get("command", "")
    if not command:
        return {"success": False, "output": "shell_exec requires 'command'"}

    try:
        sandbox_url = await executor.get_sandbox_url()
        return await signed_post_json(
            sandbox_url,
            "/shell_exec",
            {
                "lab_id": str(executor.lab_id),
                "command": command,
                "timeout_sec": executor.timeout_sec,
                "max_output_kb": executor.max_output_bytes // 1024,
            },
            timeout=executor.timeout_sec + 5,
        )
    except httpx.TimeoutException:
        return {
            "success": False,
            "output": f"Shell execution timed out after {executor.timeout_sec}s",
        }
    except Exception as e:
        logger.exception("Sandbox shell_exec failed for lab %s", executor.lab_id)
        return {"success": False, "output": f"Sandbox error: {e}"}


HANDLERS = {
    "python_exec": python_exec,
    "shell_exec": shell_exec,
}
