"""Bob Manager — Metrics service layer."""

import asyncio
import uuid
import logging

from app.websocket.hub import manager

logger = logging.getLogger(__name__)


class MetricsService:
    """Business logic for metrics retrieval."""

    def get_server_metrics(self, server_name: str) -> dict | None:
        """Return cached live metrics for a server."""
        return manager.get_metrics(server_name)

    def get_all_metrics(self) -> dict[str, dict]:
        """Return all cached metrics from connected agents."""
        return manager.get_all_metrics()

    async def request_inspection(
        self, server_name: str, inspection_type: str, timeout: int = 30
    ) -> dict | None:
        """Request system inspection data from an agent.

        Args:
            server_name: Name of the target server.
            inspection_type: One of 'processes', 'services', 'crontabs', 'ports', 'firewall'.
            timeout: How long to wait for a response.

        Returns:
            Inspection data dict or None on timeout/failure.
        """
        request_id = str(uuid.uuid4())
        future = manager.create_pending(request_id)

        sent = await manager.send_to_agent(server_name, {
            "type": "inspection.request",
            "id": request_id,
            "payload": {"kind": inspection_type},
        })

        if not sent:
            return None

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.warning("Inspection %s timed out for %s", inspection_type, server_name)
            return None
