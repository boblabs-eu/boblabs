"""File I/O tools: file_read, file_write."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

TOOLS = {
    "file_read": {
        "description": "Read a file from the lab workspace. Path must be relative to the lab folder.",
        "parameters": {
            "path": {
                "type": "string",
                "description": "Relative file path to read",
                "required": True,
            },
        },
    },
    "file_write": {
        "description": "Write content to a file in the lab output folder. Path must be relative.",
        "parameters": {
            "path": {
                "type": "string",
                "description": "Relative file path (written to output/)",
                "required": True,
            },
            "content": {"type": "string", "description": "File content to write", "required": True},
        },
    },
}


async def file_read(executor: ToolExecutor, args: dict) -> dict:
    rel_path = args.get("path", "").strip().rstrip("/")
    if not rel_path:
        return {"success": False, "output": "file_read requires 'path'"}

    clean_path = re.sub(r"^output/", "", rel_path)

    target = None
    for base in (executor.workspace, executor.workspace / "output"):
        try:
            candidate = (base / clean_path).resolve()
            if candidate.is_relative_to(executor.workspace.resolve()) and candidate.is_file():
                target = candidate
                break
        except Exception:
            continue

    if target is None:
        try:
            candidate = (executor.workspace / rel_path).resolve()
            if candidate.is_relative_to(executor.workspace.resolve()) and candidate.is_file():
                target = candidate
        except Exception:
            pass

    # Fallback: resource files stored with UUID prefix
    if target is None:
        basename = Path(clean_path).name
        for f in executor.workspace.iterdir():
            if f.is_file() and f.name.endswith("_" + basename):
                target = f
                break

    if target is None:
        return {"success": False, "output": f"File not found: {rel_path}"}

    try:
        resolved = target.resolve()
        if not resolved.is_relative_to(executor.workspace.resolve()):
            return {"success": False, "output": "Path traversal denied."}
    except Exception:
        return {"success": False, "output": "Invalid path."}

    try:
        content = target.read_text(errors="replace")
        if len(content) > executor.max_output_bytes:
            content = content[: executor.max_output_bytes] + "\n... [truncated]"
        return {"success": True, "output": content}
    except Exception as e:
        return {"success": False, "output": f"Read error: {e}"}


async def file_write(executor: ToolExecutor, args: dict) -> dict:
    rel_path = args.get("path", "").strip()
    content = args.get("content", "")
    if not rel_path:
        return {"success": False, "output": "file_write requires 'path'"}

    rel_path = re.sub(r"^output/", "", rel_path)
    rel_path = rel_path.rstrip("/")

    if not rel_path:
        return {
            "success": False,
            "output": "file_write requires a valid file path, not just a directory.",
        }

    output_dir = executor.workspace / "output"
    output_dir.mkdir(exist_ok=True)

    try:
        target = (output_dir / rel_path).resolve()
        if not target.is_relative_to(output_dir.resolve()):
            return {
                "success": False,
                "output": "Path traversal denied. Files can only be written to output/.",
            }
    except Exception:
        return {"success": False, "output": "Invalid path."}

    is_edit = target.is_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return {
        "success": True,
        "output": f"Written {len(content)} bytes to output/{rel_path}",
        "file_event": {
            "action": "edited" if is_edit else "created",
            "path": f"output/{rel_path}",
            "size_bytes": len(content.encode("utf-8")),
        },
    }


HANDLERS = {
    "file_read": file_read,
    "file_write": file_write,
}
