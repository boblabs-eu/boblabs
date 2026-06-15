"""Bob Manager — MCP (Model Context Protocol) client.

Thin, **stateless** client over the official ``mcp`` SDK. We open a fresh
connection per operation (list_tools / call_tool / health_check) rather than
holding long-lived sessions — MCP sessions live inside ``async with`` task
scopes and persisting them across requests is error-prone. Per-call connect is
simpler, correct, and fine for the low call rate of MCP tools (which already run
inside the timeout-wrapped ``ToolExecutor.execute`` path).

Only the CLIENT side of MCP is used here. We never run an MCP server.

Transports:
  - ``http``  → streamable-http (the modern default; Stripe, data.gouv, …)
  - ``sse``   → legacy HTTP+SSE
  - ``stdio`` → spawn a local subprocess (gated behind ``mcp_enable_stdio``)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class McpServerConfig:
    """Connection config decoupled from the ORM row (so DB objects never leak
    into transport code, and configs can be built in tests)."""

    slug: str
    name: str
    transport: str = "http"
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    auth_token: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Any) -> "McpServerConfig":
        return cls(
            slug=row.slug,
            name=row.name,
            transport=row.transport or "http",
            url=row.url,
            headers=dict(row.headers or {}),
            auth_token=row.auth_token,
            command=row.command,
            args=list(row.args or []),
            env=dict(row.env or {}),
        )

    def _resolved_headers(self) -> dict[str, str]:
        headers = dict(self.headers or {})
        if self.auth_token:
            headers.setdefault("Authorization", f"Bearer {self.auth_token}")
        return headers


@asynccontextmanager
async def _session(cfg: McpServerConfig):
    """Open + initialize an MCP ClientSession for one operation, then tear down."""
    # Imported lazily so the whole app still boots if the optional `mcp`
    # dependency is missing (MCP features just degrade to unavailable).
    from mcp import ClientSession

    transport = (cfg.transport or "http").lower()

    if transport in ("http", "streamable-http", "streamable_http"):
        from mcp.client.streamable_http import streamablehttp_client

        if not cfg.url:
            raise ValueError(f"MCP server '{cfg.slug}' has no url for http transport")
        async with streamablehttp_client(cfg.url, headers=cfg._resolved_headers()) as (
            read,
            write,
            _get_session_id,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    elif transport == "sse":
        from mcp.client.sse import sse_client

        if not cfg.url:
            raise ValueError(f"MCP server '{cfg.slug}' has no url for sse transport")
        async with sse_client(cfg.url, headers=cfg._resolved_headers()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    elif transport == "stdio":
        if not settings.mcp_enable_stdio:
            raise PermissionError(
                "stdio MCP transport is disabled (set MCP_ENABLE_STDIO=true to allow "
                "spawning local MCP subprocesses)"
            )
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        if not cfg.command:
            raise ValueError(f"MCP server '{cfg.slug}' has no command for stdio transport")
        params = StdioServerParameters(
            command=cfg.command,
            args=list(cfg.args or []),
            env=dict(cfg.env or {}) or None,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    else:
        raise ValueError(f"Unknown MCP transport: {cfg.transport!r}")


def _content_to_text(result: Any) -> str:
    """Flatten an MCP CallToolResult's content blocks into a single string."""
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
            continue
        data = getattr(block, "data", None)
        if data is not None:
            mime = getattr(block, "mimeType", "application/octet-stream")
            parts.append(f"[{mime} content, {len(str(data))} bytes]")
            continue
        parts.append(str(block))
    text = "\n".join(p for p in parts if p)
    # Some servers also return structuredContent — surface it if there was no text.
    if not text:
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            import json

            text = json.dumps(structured, ensure_ascii=False)
    return text


async def list_tools(cfg: McpServerConfig) -> list[dict]:
    """Return [{"name", "description", "inputSchema"}, ...] for a server."""
    async with _session(cfg) as session:
        result = await session.list_tools()
    tools: list[dict] = []
    for tool in result.tools:
        tools.append(
            {
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": dict(getattr(tool, "inputSchema", None) or {}),
            }
        )
    return tools


async def call_tool(cfg: McpServerConfig, tool_name: str, arguments: dict) -> dict:
    """Call one tool. Returns {"is_error": bool, "output": str}."""
    async with _session(cfg) as session:
        result = await session.call_tool(tool_name, arguments or {})
    return {
        "is_error": bool(getattr(result, "isError", False)),
        "output": _content_to_text(result),
    }


async def health_check(cfg: McpServerConfig) -> bool:
    """True if we can connect, initialize, and list tools."""
    try:
        await list_tools(cfg)
        return True
    except Exception as exc:  # noqa: BLE001 — health check swallows everything
        logger.info("MCP health check failed for %s: %s", cfg.slug, exc)
        return False
