"""Control Server tool — execute commands on linked servers via WebSocket terminal."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

from app.repositories.server_access_repo import LabServerAccessRepository
from app.websocket.hub import manager

logger = logging.getLogger(__name__)

# ANSI escape code stripper
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\x1b\[.*?[@-~]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


TOOLS = {
    "control_server": {
        "description": (
            "Execute shell commands on linked remote servers. "
            "Actions: list_servers (show available servers), "
            "execute (run a command on a server and return output), "
            "execute_all (run a command on ALL linked servers)."
        ),
        "parameters": {
            "action": {
                "type": "string",
                "description": "One of: list_servers, execute, execute_all",
                "required": True,
            },
            "server_name": {
                "type": "string",
                "description": "Target server name (required for 'execute')",
                "required": False,
            },
            "command": {
                "type": "string",
                "description": "Shell command to execute (required for 'execute' and 'execute_all')",
                "required": False,
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait for output (default: 30, max: 120)",
                "required": False,
            },
        },
    },
}


async def _open_session(server_name: str) -> tuple[str | None, str | None]:
    """Open a terminal session on a server. Returns (session_id, error)."""
    session_id = str(uuid.uuid4())

    # Register queue and session mapping
    q = manager.create_tool_terminal_queue(session_id)
    manager.map_tool_terminal_session(session_id, server_name)

    sent = await manager.send_to_agent(server_name, {
        "type": "terminal.open",
        "id": session_id,
        "payload": {
            "session_id": session_id,
            "cols": 200,
            "rows": 50,
        },
    })

    if not sent:
        manager.remove_tool_terminal_queue(session_id)
        manager.unmap_terminal_session(session_id)
        return None, f"Server '{server_name}' is not connected"

    # Wait for opened confirmation
    try:
        msg = await asyncio.wait_for(q.get(), timeout=10)
        if msg.get("type") != "opened":
            return None, f"Unexpected response from server: {msg}"
    except asyncio.TimeoutError:
        manager.remove_tool_terminal_queue(session_id)
        manager.unmap_terminal_session(session_id)
        return None, f"Timeout waiting for terminal session on '{server_name}'"

    # Wait for shell to initialize and drain banner/prompt output
    await asyncio.sleep(0.8)
    drained = 0
    while not q.empty() and drained < 100:
        try:
            q.get_nowait()
            drained += 1
        except asyncio.QueueEmpty:
            break

    return session_id, None


async def _execute_command(session_id: str, command: str, timeout: int = 30) -> str:
    """Send a command and collect output between explicit start/end markers."""
    q = manager.get_tool_terminal_queue(session_id)
    if not q:
        return "[error: no output queue for session]"

    mapping = manager.get_terminal_mapping(session_id)
    if not mapping:
        return "[error: session not mapped]"

    # Drain any leftover output first
    while not q.empty():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break

    # Unique markers — wrap command so output is bracketed cleanly
    marker_id = uuid.uuid4().hex[:12]
    start_marker = f"__BOB_START_{marker_id}__"
    end_marker = f"__BOB_END_{marker_id}__"
    # echo -n avoids extra newline; ; ensures end marker runs even if command fails
    full_command = f"echo -n '{start_marker}'; {command}; echo \"\\n{end_marker}_$?\"\n"

    await manager.send_to_agent(mapping["server_name"], {
        "type": "terminal.input",
        "id": session_id,
        "payload": {"session_id": session_id, "data": full_command},
    })

    # Collect raw stream until end marker appears (or timeout)
    buffer = ""
    deadline = asyncio.get_event_loop().time() + timeout
    saw_end = False
    exit_code: str | None = None

    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break

        try:
            msg = await asyncio.wait_for(q.get(), timeout=remaining)
            if msg.get("type") == "output":
                buffer += msg["data"]
                clean_buf = _strip_ansi(buffer)
                # Look for end marker pattern with exit code: __BOB_END_<id>_<code>
                end_match = re.search(
                    re.escape(end_marker) + r"_(\d+)", clean_buf
                )
                if end_match:
                    exit_code = end_match.group(1)
                    saw_end = True
                    break
        except asyncio.TimeoutError:
            break

    clean = _strip_ansi(buffer)

    # Extract everything between start and end markers
    start_idx = clean.find(start_marker)
    end_idx = clean.find(end_marker)

    if start_idx >= 0 and end_idx > start_idx:
        # Skip past start marker
        output = clean[start_idx + len(start_marker):end_idx]
    elif start_idx >= 0:
        output = clean[start_idx + len(start_marker):]
    else:
        # Start marker not found — return raw with markers stripped
        output = clean
    output = re.sub(re.escape(end_marker) + r"_\d+", "", output)
    output = output.replace(start_marker, "").replace(end_marker, "")

    # Strip trailing shell prompt artifacts and whitespace
    output = output.rstrip()
    # Remove leading newline from `echo -n` boundary
    output = output.lstrip("\r\n")

    if not saw_end:
        output += f"\n[warning: command did not complete within {timeout}s]"
    elif exit_code and exit_code != "0":
        output += f"\n[exit code: {exit_code}]"

    if len(output) > 50000:
        output = output[:50000] + "\n... [output truncated]"

    return output if output else "[no output]"


async def _close_session(session_id: str) -> None:
    """Close a terminal session."""
    mapping = manager.get_terminal_mapping(session_id)
    if mapping:
        await manager.send_to_agent(mapping["server_name"], {
            "type": "terminal.close",
            "id": session_id,
            "payload": {"session_id": session_id},
        })
    manager.unmap_terminal_session(session_id)
    manager.remove_tool_terminal_queue(session_id)


async def control_server(executor: ToolExecutor, args: dict) -> dict:
    """Handle control_server tool calls."""
    action = args.get("action", "")

    if action == "list_servers":
        access_repo = LabServerAccessRepository(executor.db)
        names = await access_repo.list_server_names(executor.lab_id)
        if not names:
            return {"success": True, "output": "No servers are linked to this lab."}

        # Check which are online
        connected = manager.get_connected_agents()
        lines = []
        for name in names:
            status = "online" if name in connected else "offline"
            lines.append(f"  - {name} ({status})")
        return {
            "success": True,
            "output": f"Linked servers ({len(names)}):\n" + "\n".join(lines),
        }

    elif action == "execute":
        server_name = args.get("server_name", "")
        command = args.get("command", "")
        timeout = min(int(args.get("timeout", 30)), 120)

        if not server_name:
            return {"success": False, "output": "server_name is required for 'execute'"}
        if not command:
            return {"success": False, "output": "command is required for 'execute'"}

        # Verify server is linked to this lab
        access_repo = LabServerAccessRepository(executor.db)
        allowed = await access_repo.list_server_names(executor.lab_id)
        if server_name not in allowed:
            return {"success": False, "output": f"Server '{server_name}' is not linked to this lab."}

        session_id, err = await _open_session(server_name)
        if err:
            return {"success": False, "output": err}

        try:
            output = await _execute_command(session_id, command, timeout)
            return {"success": True, "output": f"[{server_name}]\n{output}"}
        finally:
            await _close_session(session_id)

    elif action == "execute_all":
        command = args.get("command", "")
        timeout = min(int(args.get("timeout", 30)), 120)

        if not command:
            return {"success": False, "output": "command is required for 'execute_all'"}

        access_repo = LabServerAccessRepository(executor.db)
        server_names = await access_repo.list_server_names(executor.lab_id)
        if not server_names:
            return {"success": False, "output": "No servers are linked to this lab."}

        results: list[str] = []
        for name in server_names:
            session_id, err = await _open_session(name)
            if err:
                results.append(f"[{name}] ERROR: {err}")
                continue
            try:
                output = await _execute_command(session_id, command, timeout)
                results.append(f"[{name}]\n{output}")
            except Exception as e:
                results.append(f"[{name}] ERROR: {e}")
            finally:
                await _close_session(session_id)

        return {"success": True, "output": "\n\n".join(results)}

    else:
        return {
            "success": False,
            "output": f"Unknown action '{action}'. Use: list_servers, execute, execute_all",
        }


HANDLERS = {
    "control_server": control_server,
}
