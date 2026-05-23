"""Bob Manager — WebSocket connection hub.

Manages WebSocket connections for both agents and UI clients.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages all WebSocket connections (agents + UI clients)."""

    def __init__(self) -> None:
        # agent_name -> WebSocket
        self._agents: dict[str, WebSocket] = {}
        # For UI clients subscribing to live streams
        self._clients: dict[str, WebSocket] = {}
        # Pending command responses: command_id -> asyncio.Future
        self._pending: dict[str, asyncio.Future] = {}
        # Agent metric cache: agent_name -> latest metrics
        self._metrics_cache: dict[str, dict] = {}
        # Terminal session mappings: session_id -> {client_id, server_name}
        self._terminal_sessions: dict[str, dict] = {}
        # Tool-driven terminal output queues: session_id -> asyncio.Queue
        self._tool_terminal_queues: dict[str, asyncio.Queue] = {}
        # Script runner cache: agent_name -> {host, port, scripts}
        self._script_runners: dict[str, dict] = {}

    # ── Agent Connections ────────────────────────────

    async def register_agent(self, agent_name: str, ws: WebSocket) -> None:
        """Register a connected agent."""
        self._agents[agent_name] = ws
        logger.info("Agent connected: %s", agent_name)

    async def unregister_agent(self, agent_name: str) -> None:
        """Remove agent on disconnect."""
        self._agents.pop(agent_name, None)
        logger.info("Agent disconnected: %s", agent_name)

    def get_agent(self, agent_name: str) -> WebSocket | None:
        """Get agent WebSocket by name."""
        return self._agents.get(agent_name)

    def get_connected_agents(self) -> list[str]:
        """Return list of connected agent names."""
        return list(self._agents.keys())

    async def send_to_agent(self, agent_name: str, message: dict) -> bool:
        """Send a JSON message to a specific agent."""
        ws = self._agents.get(agent_name)
        if ws is None:
            logger.warning("Agent %s not connected", agent_name)
            return False
        try:
            await ws.send_json(message)
            return True
        except Exception as e:
            logger.error("Failed to send to agent %s: %s", agent_name, e)
            await self.unregister_agent(agent_name)
            return False

    # ── Client Connections ───────────────────────────

    async def register_client(self, client_id: str, ws: WebSocket) -> None:
        """Register a UI client."""
        self._clients[client_id] = ws

    async def unregister_client(self, client_id: str) -> None:
        """Remove UI client."""
        self._clients.pop(client_id, None)

    async def broadcast_to_clients(self, message: dict) -> None:
        """Broadcast a message to all connected UI clients."""
        disconnected = []
        for client_id, ws in self._clients.items():
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(client_id)
        for cid in disconnected:
            self._clients.pop(cid, None)

    # ── Command / Response Tracking ──────────────────

    def create_pending(self, command_id: str) -> asyncio.Future:
        """Create a future for a pending command response."""
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[command_id] = future
        return future

    def resolve_pending(self, command_id: str, result: dict) -> None:
        """Resolve a pending command future with the result."""
        future = self._pending.pop(command_id, None)
        if future and not future.done():
            future.set_result(result)

    # ── Metrics Cache ────────────────────────────────

    def update_metrics(self, agent_name: str, metrics: dict) -> None:
        """Cache latest metrics from an agent."""
        self._metrics_cache[agent_name] = {
            **metrics,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_metrics(self, agent_name: str) -> dict | None:
        """Get cached metrics for an agent."""
        return self._metrics_cache.get(agent_name)

    def get_all_metrics(self) -> dict[str, dict]:
        """Get all cached metrics."""
        return dict(self._metrics_cache)

    # ── Terminal Session Mapping ─────────────────────

    def map_terminal_session(
        self, session_id: str, client_id: str, server_name: str
    ) -> None:
        """Map a terminal session to a client and server."""
        self._terminal_sessions[session_id] = {
            "client_id": client_id,
            "server_name": server_name,
        }

    def get_terminal_mapping(self, session_id: str) -> dict | None:
        """Get the mapping for a terminal session."""
        return self._terminal_sessions.get(session_id)

    def unmap_terminal_session(self, session_id: str) -> None:
        """Remove a terminal session mapping."""
        self._terminal_sessions.pop(session_id, None)

    def cleanup_client_terminals(self, client_id: str) -> None:
        """Remove all terminal sessions for a disconnected client."""
        to_remove = [
            sid
            for sid, m in self._terminal_sessions.items()
            if m["client_id"] == client_id
        ]
        for sid in to_remove:
            self._terminal_sessions.pop(sid, None)
            # We should also tell the agent to close, but we won't block here
            logger.info("Cleaned up terminal session %s for client %s", sid, client_id)

    async def send_to_client(self, client_id: str, message: dict) -> bool:
        """Send a message to a specific UI client."""
        ws = self._clients.get(client_id)
        if ws is None:
            return False
        try:
            await ws.send_json(message)
            return True
        except Exception:
            self._clients.pop(client_id, None)
            return False

    # ── Tool Terminal Sessions ───────────────────────

    def create_tool_terminal_queue(self, session_id: str) -> asyncio.Queue:
        """Create an output queue for a tool-driven terminal session."""
        q: asyncio.Queue = asyncio.Queue()
        self._tool_terminal_queues[session_id] = q
        return q

    def get_tool_terminal_queue(self, session_id: str) -> asyncio.Queue | None:
        """Get the output queue for a tool terminal session."""
        return self._tool_terminal_queues.get(session_id)

    def remove_tool_terminal_queue(self, session_id: str) -> None:
        """Remove a tool terminal queue."""
        self._tool_terminal_queues.pop(session_id, None)

    def map_tool_terminal_session(
        self, session_id: str, server_name: str
    ) -> None:
        """Map a tool terminal session (no client_id, uses queue instead)."""
        self._terminal_sessions[session_id] = {
            "client_id": "__tool__",
            "server_name": server_name,
        }

    # ── Script Runner Cache ──────────────────────────

    def update_script_runner(
        self, agent_name: str, host: str, port: int, scripts: list[dict]
    ) -> None:
        """Cache script runner info for an agent."""
        self._script_runners[agent_name] = {
            "host": host,
            "port": port,
            "scripts": scripts,
        }

    def clear_script_runner(self, agent_name: str) -> None:
        """Remove script runner cache for a disconnected agent."""
        self._script_runners.pop(agent_name, None)

    def find_runner_for_script(self, script_name: str) -> str | None:
        """Find a runner URL that hosts the given script.

        Returns the full base URL (e.g. http://192.168.1.109:9101) or None.
        """
        for _agent, info in self._script_runners.items():
            for s in info.get("scripts", []):
                if s.get("name") == script_name:
                    return f"http://{info['host']}:{info['port']}"
        return None

    def find_agent_for_script(self, script_name: str) -> str | None:
        """Find the agent name that owns the given script.

        Returns agent name or None.
        """
        for agent_name, info in self._script_runners.items():
            for s in info.get("scripts", []):
                if s.get("name") == script_name:
                    return agent_name
        return None

    def get_all_script_runners(self) -> dict[str, dict]:
        """Get all cached script runner info."""
        return dict(self._script_runners)

    def get_all_available_scripts(self) -> list[dict]:
        """Get a merged list of all available scripts across all agents.

        Each entry includes the runner URL for routing.
        """
        scripts = []
        seen = set()
        for _agent, info in self._script_runners.items():
            base_url = f"http://{info['host']}:{info['port']}"
            for s in info.get("scripts", []):
                name = s.get("name", "")
                if name and name not in seen:
                    seen.add(name)
                    scripts.append({**s, "_runner_url": base_url})
        return scripts


# Singleton
manager = ConnectionManager()
