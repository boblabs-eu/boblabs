"""Bob Manager — UI client WebSocket handler."""

import logging
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from app.websocket.hub import manager

logger = logging.getLogger(__name__)


async def handle_client_connection(ws: WebSocket) -> None:
    """Handle a UI client WebSocket connection.

    Clients receive live updates: metrics, command output, workflow progress.
    They can also request terminal sessions.
    """
    await ws.accept()
    client_id = str(uuid.uuid4())

    try:
        await manager.register_client(client_id, ws)
        logger.info("UI client connected: %s", client_id)

        # Send initial state
        await ws.send_json({
            "type": "init",
            "payload": {
                "connected_agents": manager.get_connected_agents(),
                "cached_metrics": manager.get_all_metrics(),
            },
        })

        # Main message loop — relay terminal messages to agents
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")
            payload = data.get("payload", {})

            if msg_type == "terminal.open":
                # Client wants to open a terminal on an agent
                server_name = payload.get("server_name", "")
                session_id = str(uuid.uuid4())
                cols = payload.get("cols", 120)
                rows = payload.get("rows", 40)

                # Map session to this client
                manager.map_terminal_session(session_id, client_id, server_name)

                sent = await manager.send_to_agent(server_name, {
                    "type": "terminal.open",
                    "id": session_id,
                    "payload": {
                        "session_id": session_id,
                        "cols": cols,
                        "rows": rows,
                    },
                })

                if not sent:
                    await ws.send_json({
                        "type": "terminal.error",
                        "payload": {
                            "session_id": session_id,
                            "error": "Agent not connected",
                        },
                    })
                else:
                    await ws.send_json({
                        "type": "terminal.session_id",
                        "payload": {"session_id": session_id},
                    })

            elif msg_type == "terminal.input":
                session_id = payload.get("session_id", "")
                mapping = manager.get_terminal_mapping(session_id)
                if mapping:
                    await manager.send_to_agent(mapping["server_name"], {
                        "type": "terminal.input",
                        "id": session_id,
                        "payload": payload,
                    })

            elif msg_type == "terminal.resize":
                session_id = payload.get("session_id", "")
                mapping = manager.get_terminal_mapping(session_id)
                if mapping:
                    await manager.send_to_agent(mapping["server_name"], {
                        "type": "terminal.resize",
                        "id": session_id,
                        "payload": payload,
                    })

            elif msg_type == "terminal.close":
                session_id = payload.get("session_id", "")
                mapping = manager.get_terminal_mapping(session_id)
                if mapping:
                    await manager.send_to_agent(mapping["server_name"], {
                        "type": "terminal.close",
                        "id": session_id,
                        "payload": {"session_id": session_id},
                    })
                manager.unmap_terminal_session(session_id)

            else:
                logger.debug("Client %s sent: %s", client_id, msg_type)

    except WebSocketDisconnect:
        logger.info("UI client disconnected: %s", client_id)
    except Exception as e:
        logger.error("Client connection error: %s", e)
    finally:
        # Close any terminal sessions owned by this client
        manager.cleanup_client_terminals(client_id)
        await manager.unregister_client(client_id)
