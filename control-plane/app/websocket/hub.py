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
        # Cluster A — per-client identity (JWT payload). Populated by
        # register_client; used by broadcast_to_clients to filter by
        # audience when callers pass an ``audience_email`` argument.
        self._client_users: dict[str, dict] = {}
        # Pending command responses: command_id -> asyncio.Future
        self._pending: dict[str, asyncio.Future] = {}
        # R01 — command_id -> agent_name so we can cancel-on-disconnect.
        # Populated when callers pass `agent_name=...` to create_pending
        # (existing call sites in command_service / metrics_service /
        # engine.executor all know which agent they're talking to).
        self._pending_agent_map: dict[str, str] = {}
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
        """Remove agent on disconnect.

        R01 + R02 — also cancel every pending command future targeting
        this agent (otherwise each caller waits the full timeout) and
        drop every terminal session whose ``server_name`` matched (so
        downstream ``terminal.input`` frames don't silently fall on the
        floor).
        """
        self._agents.pop(agent_name, None)
        cancelled = self.cleanup_agent_pending(agent_name)
        terminated = self.cleanup_agent_terminals(agent_name)
        if cancelled or terminated:
            logger.info(
                "Agent disconnected: %s (cancelled %d pending, "
                "closed %d terminal sessions)",
                agent_name, cancelled, terminated,
            )
        else:
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

    async def register_client(self, client_id: str, ws: WebSocket,
                                user: dict | None = None) -> None:
        """Register a UI client. Cluster A — ``user`` carries the JWT
        payload (sub / role / iat etc.) so broadcast_to_clients can
        filter to a specific principal when callers know the audience.
        Anonymous registrations (user=None) are not accepted by the
        production route handler but the field is optional for tests.
        """
        self._clients[client_id] = ws
        if user is not None:
            self._client_users[client_id] = user

    async def unregister_client(self, client_id: str) -> None:
        """Remove UI client."""
        self._clients.pop(client_id, None)
        self._client_users.pop(client_id, None)

    def get_client_user(self, client_id: str) -> dict | None:
        return self._client_users.get(client_id)

    async def broadcast_to_clients(self, message: dict,
                                     *, audience_email: str | None = None,
                                     admin_only: bool = False) -> None:
        """Broadcast a message to UI clients.

        Cluster A — when ``audience_email`` is provided only clients
        whose JWT ``sub`` matches receive the message (plus all admins,
        who are universally allowed). When ``admin_only=True`` only
        admin clients receive it. With no filters (the existing
        callsites) the message goes to every authenticated client; the
        global firehose nature is preserved for backwards-compat and is
        narrowed by callers when they know who the audience is.
        """
        disconnected = []
        for client_id, ws in self._clients.items():
            if audience_email is not None or admin_only:
                user = self._client_users.get(client_id) or {}
                is_admin = user.get("role") == "admin"
                if admin_only and not is_admin:
                    continue
                if audience_email is not None and not is_admin and user.get("sub") != audience_email:
                    continue
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(client_id)
        for cid in disconnected:
            self._clients.pop(cid, None)
            self._client_users.pop(cid, None)

    # ── Command / Response Tracking ──────────────────

    def create_pending(self, command_id: str, agent_name: str | None = None) -> asyncio.Future:
        """Create a future for a pending command response.

        R01 — callers may pass ``agent_name`` so the pending future is
        tracked against its target agent. On agent disconnect
        :meth:`cleanup_agent_pending` is called from
        :meth:`unregister_agent` and every pending future for that agent
        is cancelled. Callers MUST also call :meth:`cancel_pending` in
        their own timeout / send-failure branches to drop the entry
        eagerly instead of relying on the disconnect path.
        """
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[command_id] = future
        if agent_name:
            self._pending_agent_map[command_id] = agent_name
        return future

    def resolve_pending(self, command_id: str, result: dict) -> None:
        """Resolve a pending command future with the result."""
        self._pending_agent_map.pop(command_id, None)
        future = self._pending.pop(command_id, None)
        if future and not future.done():
            future.set_result(result)

    def cancel_pending(self, command_id: str, *, reason: str = "cancelled") -> bool:
        """Drop a pending future without resolving it. Returns True if
        an entry was removed. Safe to call multiple times.

        R01 — every callsite that creates a pending future MUST call
        ``cancel_pending`` on its timeout / send-failure / exception
        paths so ``_pending`` does not grow unbounded under failure
        conditions. Logged when an entry is actually removed so the
        operator has a signal that requests are being dropped.
        """
        self._pending_agent_map.pop(command_id, None)
        future = self._pending.pop(command_id, None)
        if future is None:
            return False
        if not future.done():
            future.cancel()
        logger.debug("Cancelled pending future %s (reason=%s)", command_id, reason)
        return True

    def cleanup_agent_pending(self, agent_name: str) -> int:
        """R01 — cancel every pending future targeting ``agent_name``.
        Called from :meth:`unregister_agent` so a dropped socket doesn't
        leave its outstanding command futures hanging until each caller's
        individual timeout fires.
        """
        victims = [cid for cid, an in self._pending_agent_map.items() if an == agent_name]
        for cid in victims:
            self.cancel_pending(cid, reason=f"agent_disconnected:{agent_name}")
        return len(victims)

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

    def cleanup_agent_terminals(self, agent_name: str) -> list[str]:
        """R02 — drop every terminal session whose ``server_name`` matched
        the disconnected agent. Returns the list of removed session ids
        so the caller can broadcast a ``terminal.closed`` event if it
        wants.

        Previously these sessions stayed in ``_terminal_sessions`` after
        the agent died and ``terminal.input`` frames from the UI were
        forwarded to a no-longer-connected agent — the send failed
        silently and the user saw an unresponsive terminal with no
        indication of why.
        """
        to_remove = [
            sid for sid, m in self._terminal_sessions.items()
            if m.get("server_name") == agent_name
        ]
        for sid in to_remove:
            self._terminal_sessions.pop(sid, None)
        return to_remove

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
