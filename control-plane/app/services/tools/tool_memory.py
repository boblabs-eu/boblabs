"""Memory and reasoning tools: think, memory_save, memory_search, handle_memory."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

TOOLS = {
    "think": {
        "description": "Private reasoning step. Use this to think through a problem before acting. Output is not shown to other agents.",
        "parameters": {
            "thought": {
                "type": "string",
                "description": "Your private reasoning",
                "required": True,
            },
        },
    },
    "memory_save": {
        "description": "Save a fact or result to lab memory for later retrieval.",
        "parameters": {
            "key": {
                "type": "string",
                "description": "Short identifier for this memory",
                "required": True,
            },
            "content": {
                "type": "string",
                "description": "The content to remember",
                "required": True,
            },
            "importance": {
                "type": "integer",
                "description": "Importance 1-10 (default: 5)",
                "required": False,
            },
        },
    },
    "memory_search": {
        "description": "Search lab memories by keyword.",
        "parameters": {
            "query": {"type": "string", "description": "Search query", "required": True},
        },
    },
    "handle_memory": {
        "description": "Manage agent memories. Use action='list' to see all memories for an agent (with hidden status). Use action='hide' or action='show' with memory_ids to change visibility. Hidden memories are excluded from agent prompts.",
        "parameters": {
            "agent_name": {
                "type": "string",
                "description": "Name of the agent whose memories to manage",
                "required": True,
            },
            "action": {
                "type": "string",
                "description": "Action: 'list', 'hide', or 'show'",
                "required": True,
            },
            "memory_ids": {
                "type": "string",
                "description": "Comma-separated memory IDs to hide/show (required for hide/show actions)",
                "required": False,
            },
        },
    },
}


async def think(executor: ToolExecutor, args: dict) -> dict:
    thought = args.get("thought", "")
    return {"success": True, "output": f"[Thought recorded: {thought[:200]}]"}


async def memory_save(executor: ToolExecutor, args: dict) -> dict:
    from app.repositories.lab_repo import LabMemoryRepository

    key = args.get("key", "")
    content = args.get("content", "")
    importance = min(max(int(args.get("importance", 5)), 1), 10)

    if not key or not content:
        return {"success": False, "output": "memory_save requires 'key' and 'content'"}

    mem_repo = LabMemoryRepository(executor.db)
    await mem_repo.create(
        lab_id=executor.lab_id,
        agent_id=None,
        scope="lab",
        key=key[:255],
        content=content[:5000],
        memory_type="tool",
        importance=importance,
    )
    await executor.db.commit()
    return {"success": True, "output": f"Memory saved: [{key}]"}


async def memory_search(executor: ToolExecutor, args: dict) -> dict:
    from app.repositories.lab_repo import LabMemoryRepository

    query = args.get("query", "").lower()
    if not query:
        return {"success": False, "output": "memory_search requires 'query'"}

    mem_repo = LabMemoryRepository(executor.db)
    memories = await mem_repo.get_by_lab(executor.lab_id, limit=50)
    matches = [m for m in memories if query in m.key.lower() or query in m.content.lower()]
    if not matches:
        return {"success": True, "output": "No matching memories found."}

    lines = []
    for m in matches[:10]:
        lines.append(f"- [{m.key}] (importance: {m.importance}) {m.content[:300]}")
    return {"success": True, "output": "\n".join(lines)}


async def handle_memory(executor: ToolExecutor, args: dict) -> dict:
    """List / hide / show memories for a specific agent."""
    import uuid

    from sqlalchemy import select
    from sqlalchemy import update as sql_update

    from app.models.orchestrator import LabAgent, LabMemory

    agent_name = args.get("agent_name", "").strip()
    action = args.get("action", "list").strip().lower()

    if not agent_name:
        return {"success": False, "output": "handle_memory requires 'agent_name'"}
    if action not in ("list", "hide", "show"):
        return {"success": False, "output": "action must be 'list', 'hide', or 'show'"}

    result = await executor.db.execute(
        select(LabAgent).where(LabAgent.lab_id == executor.lab_id, LabAgent.name == agent_name)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return {"success": False, "output": f"Agent '{agent_name}' not found in this lab"}

    if action == "list":
        result = await executor.db.execute(
            select(LabMemory)
            .where(LabMemory.lab_id == executor.lab_id, LabMemory.agent_id == agent.id)
            .order_by(LabMemory.importance.desc(), LabMemory.updated_at.desc())
            .limit(50)
        )
        mems = list(result.scalars().all())
        if not mems:
            return {"success": True, "output": f"No memories found for agent '{agent_name}'."}
        lines = [f"Memories for agent '{agent_name}' ({len(mems)} total):"]
        for m in mems:
            hidden_tag = " [HIDDEN]" if m.is_hidden else ""
            preview = (m.content or "")[:120].replace("\n", " ")
            lines.append(f"- id={m.id} key=[{m.key}] imp={m.importance}{hidden_tag}: {preview}")
        return {"success": True, "output": "\n".join(lines)}

    # hide / show
    memory_ids_str = args.get("memory_ids", "").strip()
    if not memory_ids_str:
        return {"success": False, "output": f"'memory_ids' required for action='{action}'"}

    ids = []
    for mid in memory_ids_str.split(","):
        mid = mid.strip()
        if mid:
            try:
                ids.append(uuid.UUID(mid))
            except ValueError:
                return {"success": False, "output": f"Invalid UUID: {mid}"}

    new_hidden = action == "hide"
    await executor.db.execute(
        sql_update(LabMemory)
        .where(LabMemory.id.in_(ids), LabMemory.lab_id == executor.lab_id)
        .values(is_hidden=new_hidden)
    )
    await executor.db.commit()
    return {
        "success": True,
        "output": f"{'Hid' if new_hidden else 'Showed'} {len(ids)} memory(ies) for agent '{agent_name}'.",
    }


HANDLERS = {
    "think": think,
    "memory_save": memory_save,
    "memory_search": memory_search,
    "handle_memory": handle_memory,
}
