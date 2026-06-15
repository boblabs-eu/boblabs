"""Bob Manager — MCP tool registry sync.

Connects to every *enabled* :class:`McpServer`, lists its tools, and registers
each one into the global tool registries (``BUILTIN_TOOLS`` / ``TOOL_HANDLERS``)
under a namespaced key ``mcp__<slug>__<tool>``. Because every consumer
(``build_native_tools_schema``, ``format_tool_descriptions``, the
``/builtin-tools`` picker, and ``ToolExecutor.execute``) reads those two dicts,
MCP tools become first-class with no other code changes.

Re-running ``sync_mcp_tools`` is idempotent: it overwrites current entries and
prunes any ``mcp__*`` keys whose server was disabled/removed. Called on startup
and after any MCP-server CRUD mutation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import settings
from app.services import mcp_client
from app.services.mcp_client import McpServerConfig
from app.services.tools import BUILTIN_TOOLS, TOOL_HANDLERS

logger = logging.getLogger(__name__)

# Keys this module owns in BUILTIN_TOOLS/TOOL_HANDLERS (for pruning on re-sync).
_MCP_TOOL_KEYS: set[str] = set()
# tool_key -> {"server_slug", "server_name", "tool"} for the picker grouping.
MCP_TOOL_META: dict[str, dict] = {}

_sync_lock = asyncio.Lock()


# ── Curated catalog of well-known remote MCP servers ──────────────
# Enabling one of these pre-fills an McpServer row; the operator supplies any
# required token. URLs are editable after enabling in case a provider moves.
MCP_CATALOG: list[dict] = [
    {
        "key": "stripe",
        "name": "Stripe",
        "transport": "http",
        "url": "https://mcp.stripe.com",
        "auth": "bearer",
        "description": "Stripe payments, customers, invoices, balances.",
        "docs_url": "https://docs.stripe.com/mcp",
    },
    {
        "key": "datagouv",
        "name": "data.gouv.fr",
        "transport": "http",
        "url": "https://mcp.data.gouv.fr/mcp",
        "auth": "none",
        "description": "Search French open-data datasets, resources, and tabular rows.",
        "docs_url": "https://www.data.gouv.fr/",
    },
    {
        "key": "github",
        "name": "GitHub",
        "transport": "http",
        "url": "https://api.githubcopilot.com/mcp/",
        "auth": "bearer",
        "description": "GitHub repos, issues, PRs, code search (needs a PAT).",
        "docs_url": "https://github.com/github/github-mcp-server",
    },
    {
        "key": "huggingface",
        "name": "Hugging Face",
        "transport": "http",
        "url": "https://huggingface.co/mcp",
        "auth": "bearer",
        "description": "Search models, datasets, and Spaces (token optional).",
        "docs_url": "https://huggingface.co/settings/mcp",
    },
    {
        "key": "context7",
        "name": "Context7",
        "transport": "http",
        "url": "https://mcp.context7.com/mcp",
        "auth": "none",
        "description": "Up-to-date library/framework documentation lookups.",
        "docs_url": "https://context7.com/",
    },
    {
        "key": "deepwiki",
        "name": "DeepWiki",
        "transport": "http",
        "url": "https://mcp.deepwiki.com/mcp",
        "auth": "none",
        "description": "Ask questions about any public GitHub repository.",
        "docs_url": "https://deepwiki.com/",
    },
]


def get_catalog() -> list[dict]:
    return MCP_CATALOG


def _convert_input_schema(input_schema: dict | None) -> dict[str, dict]:
    """Convert an MCP tool ``inputSchema`` (JSON Schema) to Bob Labs' descriptor
    shape consumed by ``build_native_tools_schema`` /
    ``format_tool_descriptions``: ``{pname: {"type", "description", "required"}}``.

    Lossy for deeply nested objects/arrays (only the top-level param type +
    description survive), but sufficient for native function-calling.
    """
    schema = input_schema or {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    params: dict[str, dict] = {}
    for pname, pschema in props.items():
        pschema = pschema or {}
        ptype = pschema.get("type")
        if isinstance(ptype, list):  # e.g. ["string", "null"]
            ptype = next((t for t in ptype if t != "null"), "string")
        params[pname] = {
            "type": ptype or "string",
            "description": pschema.get("description") or pschema.get("title") or "",
            "required": pname in required,
        }
    return params


def _make_handler(cfg: McpServerConfig, tool_name: str):
    """Build the ToolExecutor handler closure for one MCP tool."""

    async def handler(_executor: Any, args: dict) -> dict:
        try:
            res = await mcp_client.call_tool(cfg, tool_name, args or {})
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "output": f"MCP call failed ({cfg.slug}/{tool_name}): {exc}",
            }
        return {
            "success": not res["is_error"],
            "output": res["output"] or "(empty MCP result)",
        }

    return handler


def _register_server_tools(cfg: McpServerConfig, tools: list[dict]) -> set[str]:
    keys: set[str] = set()
    for tool in tools:
        key = f"mcp__{cfg.slug}__{tool['name']}"
        desc = (tool.get("description") or "").strip()
        BUILTIN_TOOLS[key] = {
            "description": f"[MCP · {cfg.name}] {desc}".strip(),
            "parameters": _convert_input_schema(tool.get("inputSchema")),
            "mcp": True,
        }
        TOOL_HANDLERS[key] = _make_handler(cfg, tool["name"])
        MCP_TOOL_META[key] = {
            "server_slug": cfg.slug,
            "server_name": cfg.name,
            "tool": tool["name"],
        }
        keys.add(key)
    return keys


def _prune(except_keys: set[str]) -> None:
    stale = _MCP_TOOL_KEYS - except_keys
    for key in stale:
        BUILTIN_TOOLS.pop(key, None)
        TOOL_HANDLERS.pop(key, None)
        MCP_TOOL_META.pop(key, None)


async def sync_mcp_tools(session_factory) -> dict:
    """(Re)register tools for all enabled MCP servers; prune disabled ones.

    Safe to call repeatedly (startup + after every CRUD mutation). Connection
    failures for one server are logged and skipped — they never block the others
    or app startup.
    """
    from sqlalchemy import select, update

    from app.models.orchestrator import McpServer

    async with _sync_lock:
        async with session_factory() as db:
            rows = list(
                (await db.execute(select(McpServer).where(McpServer.enabled.is_(True))))
                .scalars()
                .all()
            )
            configs = [McpServerConfig.from_row(r) for r in rows]

        registered: set[str] = set()
        healthy_slugs: list[str] = []
        for cfg in configs:
            try:
                tools = await asyncio.wait_for(
                    mcp_client.list_tools(cfg),
                    timeout=settings.mcp_default_timeout_sec,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("MCP sync: %s unreachable, skipping (%s)", cfg.slug, exc)
                continue
            registered |= _register_server_tools(cfg, tools)
            healthy_slugs.append(cfg.slug)
            logger.info("MCP sync: %s registered %d tools", cfg.slug, len(tools))

        _prune(except_keys=registered)
        _MCP_TOOL_KEYS.clear()
        _MCP_TOOL_KEYS.update(registered)

        if healthy_slugs:
            from sqlalchemy import func as sa_func

            async with session_factory() as db:
                await db.execute(
                    update(McpServer)
                    .where(McpServer.slug.in_(healthy_slugs))
                    .values(last_seen_at=sa_func.now())
                )
                await db.commit()

    return {"servers": len(configs), "tools": len(registered)}


def mcp_server_tool_keys(slug: str) -> list[str]:
    """All currently-registered tool keys for one server slug (for ``mcp:<slug>``
    expansion in ``normalize_tool_names``)."""
    prefix = f"mcp__{slug}__"
    return [k for k in BUILTIN_TOOLS if k.startswith(prefix)]
