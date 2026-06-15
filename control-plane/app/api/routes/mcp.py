"""Bob Manager — MCP (Model Context Protocol) server registry API.

Mounted at /api/v1/mcp. Lets the operator browse a curated catalog of remote
MCP servers, enable/disable them, add fully custom ones, and preview the tools
a server exposes. Any mutation re-syncs the global tool registry so the enabled
servers' tools are immediately selectable by agents as ``mcp__<slug>__<tool>``.
"""

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import DbSession, require_admin
from app.config import settings
from app.database import async_session
from app.repositories.lab_repo import McpServerRepository
from app.schemas.orchestrator import (
    McpServerCreate,
    McpServerResponse,
    McpServerUpdate,
)
from app.services import mcp_client
from app.services.mcp_client import McpServerConfig
from app.services.tools.mcp_registry import MCP_CATALOG, get_catalog, sync_mcp_tools

router = APIRouter(prefix="/mcp", tags=["mcp"])

_CATALOG_BY_KEY = {entry["key"]: entry for entry in MCP_CATALOG}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug[:64] or "mcp"


async def _unique_slug(repo: McpServerRepository, base: str) -> str:
    slug = _slugify(base)
    candidate = slug
    n = 2
    while await repo.get_by_slug(candidate):
        candidate = f"{slug}-{n}"[:64]
        n += 1
    return candidate


@router.get("/catalog")
async def list_catalog(_user: dict = Depends(require_admin)):
    """Curated presets the operator can enable in one step."""
    return get_catalog()


@router.get("/servers", response_model=list[McpServerResponse])
async def list_servers(db: DbSession, _user: dict = Depends(require_admin)):
    return await McpServerRepository(db).get_all()


@router.post("/servers", response_model=McpServerResponse, status_code=status.HTTP_201_CREATED)
async def create_server(data: McpServerCreate, db: DbSession, _user: dict = Depends(require_admin)):
    repo = McpServerRepository(db)

    if data.catalog_key:
        preset = _CATALOG_BY_KEY.get(data.catalog_key)
        if not preset:
            raise HTTPException(400, f"Unknown catalog_key: {data.catalog_key}")
        name = data.name or preset["name"]
        fields = {
            "transport": preset.get("transport", "http"),
            "url": preset.get("url"),
            "command": None,
            "args": [],
            "env": {},
            "source": "catalog",
            "catalog_key": data.catalog_key,
        }
    else:
        if not data.name:
            raise HTTPException(400, "name is required for a custom MCP server")
        if data.transport == "stdio":
            if not data.command:
                raise HTTPException(400, "command is required for stdio transport")
        elif not data.url:
            raise HTTPException(400, "url is required for http/sse transport")
        name = data.name
        fields = {
            "transport": data.transport,
            "url": data.url,
            "command": data.command,
            "args": data.args,
            "env": data.env,
            "source": "custom",
            "catalog_key": None,
        }

    if await repo.get_by_name(name):
        raise HTTPException(409, f"An MCP server named '{name}' already exists")

    server = await repo.create(
        name=name,
        slug=await _unique_slug(repo, name),
        headers=data.headers or {},
        auth_token=data.auth_token,
        enabled=data.enabled,
        **fields,
    )
    await db.commit()
    if server.enabled:
        await sync_mcp_tools(async_session)
    return server


@router.patch("/servers/{server_id}", response_model=McpServerResponse)
async def update_server(
    server_id: UUID, data: McpServerUpdate, db: DbSession, _user: dict = Depends(require_admin)
):
    repo = McpServerRepository(db)
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    server = await repo.update(server_id, **updates)
    if not server:
        raise HTTPException(404, "MCP server not found")
    await db.commit()
    # Any config/enabled change can alter the registered tool set.
    await sync_mcp_tools(async_session)
    return server


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(server_id: UUID, db: DbSession, _user: dict = Depends(require_admin)):
    repo = McpServerRepository(db)
    server = await repo.get_by_id(server_id)
    if not server:
        raise HTTPException(404, "MCP server not found")
    await repo.delete(server_id)
    await db.commit()
    await sync_mcp_tools(async_session)


@router.post("/servers/{server_id}/test")
async def test_server(server_id: UUID, db: DbSession, _user: dict = Depends(require_admin)):
    """Connect to a server and preview the tools it exposes."""
    import asyncio

    server = await McpServerRepository(db).get_by_id(server_id)
    if not server:
        raise HTTPException(404, "MCP server not found")
    cfg = McpServerConfig.from_row(server)
    try:
        tools = await asyncio.wait_for(
            mcp_client.list_tools(cfg), timeout=settings.mcp_default_timeout_sec
        )
    except Exception as exc:  # noqa: BLE001
        return {"healthy": False, "error": str(exc), "tools": []}
    return {
        "healthy": True,
        "tool_count": len(tools),
        "tools": [{"name": t["name"], "description": t.get("description", "")} for t in tools],
    }
