"""Bob Manager — UI client WebSocket handler."""

import logging
import uuid

from fastapi import WebSocket, WebSocketDisconnect, status
from jose import JWTError, jwt

from app.config import settings
from app.websocket.hub import manager

logger = logging.getLogger(__name__)


def _extract_token(ws: WebSocket) -> str | None:
    """Pull a JWT from one of three places (cluster A):

    1. ``Sec-WebSocket-Protocol`` header with value ``bob.jwt.<token>``
       (preferred — keeps tokens out of access logs).
    2. ``?token=<token>`` query string (fallback for environments where
       custom subprotocols are awkward to set).

    Returns the raw token string or None.
    """
    for proto in ws.headers.getlist("sec-websocket-protocol") if hasattr(ws.headers, "getlist") else (
        [v.strip() for v in (ws.headers.get("sec-websocket-protocol") or "").split(",") if v.strip()]
    ):
        if proto.startswith("bob.jwt."):
            return proto[len("bob.jwt."):]
    return ws.query_params.get("token")


def _decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None


async def handle_client_connection(ws: WebSocket) -> None:
    """Handle a UI client WebSocket connection.

    Clients receive live updates: metrics, command output, workflow progress.
    They can also request terminal sessions.

    Cluster A — the route was previously anonymous: every UI client (and
    every anonymous LivePage browser tab) received the full firehose of
    metrics, command output, terminal frames, and AI-model updates, and
    could open / write to / close any terminal session by knowing its
    UUID. The connection now requires a valid JWT (subprotocol header or
    query param) and every terminal operation is gated on the
    connecting client owning the session.
    """
    token = _extract_token(ws)
    if not token:
        # 1008 = policy violation. Browsers can detect this and prompt
        # for re-auth / re-login.
        await ws.close(code=1008)
        return
    user = _decode_token(token)
    if user is None:
        await ws.close(code=1008)
        return

    await ws.accept()
    client_id = str(uuid.uuid4())

    try:
        await manager.register_client(client_id, ws, user=user)
        logger.info(
            "UI client connected: %s (sub=%s, role=%s)",
            client_id, user.get("sub"), user.get("role"),
        )

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
                # Cluster A — only the client that opened the session can
                # write to it. session_id alone is not sufficient.
                session_id = payload.get("session_id", "")
                mapping = manager.get_terminal_mapping(session_id)
                if mapping and mapping.get("client_id") == client_id:
                    await manager.send_to_agent(mapping["server_name"], {
                        "type": "terminal.input",
                        "id": session_id,
                        "payload": payload,
                    })

            elif msg_type == "terminal.resize":
                session_id = payload.get("session_id", "")
                mapping = manager.get_terminal_mapping(session_id)
                if mapping and mapping.get("client_id") == client_id:
                    await manager.send_to_agent(mapping["server_name"], {
                        "type": "terminal.resize",
                        "id": session_id,
                        "payload": payload,
                    })

            elif msg_type == "terminal.close":
                session_id = payload.get("session_id", "")
                mapping = manager.get_terminal_mapping(session_id)
                if mapping and mapping.get("client_id") == client_id:
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
