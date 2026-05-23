"""Bob Manager Agent — Main entry point.

Starts both the Prometheus metrics server and the WebSocket client.
"""

import asyncio
import logging
import signal

from app.config import config
from app.metrics.exporter import start_metrics_server
from app.version import __version__
from app.websocket.client import AgentWebSocketClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


async def main() -> None:
    """Start the agent: metrics server + WebSocket clients."""
    logger.info("Starting Bob Manager Agent '%s' v%s", config.agent_name, __version__)
    logger.info("Control Planes: %s", ", ".join(config.control_plane_urls))
    logger.info("Metrics Port: %d", config.metrics_port)

    # Start Prometheus metrics HTTP server
    metrics_runner = await start_metrics_server(config.metrics_port)

    # Start one WebSocket client per control plane
    ws_clients = [AgentWebSocketClient(url) for url in config.control_plane_urls]

    # Handle shutdown
    loop = asyncio.get_event_loop()

    def shutdown():
        logger.info("Shutting down agent...")
        for client in ws_clients:
            client.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown)

    try:
        await asyncio.gather(*(client.connect() for client in ws_clients))
    finally:
        await metrics_runner.cleanup()
        logger.info("Agent stopped.")


if __name__ == "__main__":
    asyncio.run(main())
