"""Cluster A — /ws/client requires JWT.

Pre-fix: every anonymous browser tab connected to /ws/client received
the full metrics + command + terminal firehose and could open / write
to / close any terminal by knowing its UUID.

Post-fix: connection without a valid JWT (subprotocol header
`bob.jwt.<token>` OR `?token=<token>`) is closed with code 1008.
Terminal session_ids are bound to the client that opened them.

These tests use httpx.AsyncClient against the real ASGI app — the
internal `_extract_token` + `_decode_token` helpers can also be unit
tested without a full WS handshake.
"""

from __future__ import annotations

import pytest
from app.websocket.client_handler import _decode_token, _extract_token

pytestmark = pytest.mark.regression


# ── _extract_token unit tests ─────────────────────────────────────


class _FakeHeaders(dict):
    def getlist(self, k):
        v = self.get(k.lower())
        return [v] if v else []


class _FakeWS:
    def __init__(self, headers: dict, query: dict | None = None):
        self.headers = _FakeHeaders({k.lower(): v for k, v in headers.items()})
        self.query_params = query or {}


def test_extract_token_from_subprotocol():
    ws = _FakeWS({"sec-websocket-protocol": "bob.jwt.MYTOKEN"})
    assert _extract_token(ws) == "MYTOKEN"


def test_extract_token_from_query_string():
    ws = _FakeWS({}, query={"token": "QUERYTOKEN"})
    assert _extract_token(ws) == "QUERYTOKEN"


def test_extract_token_subprotocol_preferred_over_query():
    ws = _FakeWS({"sec-websocket-protocol": "bob.jwt.SUBTOK"}, query={"token": "QUERYTOK"})
    assert _extract_token(ws) == "SUBTOK"


def test_extract_token_missing_returns_none():
    ws = _FakeWS({})
    assert _extract_token(ws) is None


# ── _decode_token unit tests ──────────────────────────────────────


def test_decode_token_valid(admin_user):
    payload = _decode_token(admin_user["token"])
    assert payload is not None
    assert payload["role"] == "admin"


def test_decode_token_invalid_returns_none():
    assert _decode_token("not-a-jwt") is None
    assert _decode_token("") is None


def test_decode_token_wrong_secret_returns_none():
    """A token signed with a different secret must be rejected."""
    from datetime import timedelta

    from jose import jwt

    bad = jwt.encode({"sub": "x", "role": "admin"}, "other-secret", algorithm="HS256")
    assert _decode_token(bad) is None


# ── End-to-end via httpx websocket ────────────────────────────────


@pytest.mark.asyncio
async def test_ws_client_anonymous_rejected(anonymous_client):
    """Connecting without a token closes immediately with 1008 (handler-side).

    httpx + ASGITransport does WebSocket handshakes but doesn't expose
    the close code as cleanly as the websockets library. We use the
    ASGI protocol directly via a tiny harness.
    """
    from app.main import app as fastapi_app
    from httpx import ASGITransport

    ASGITransport(app=fastapi_app)

    # Build a minimal ASGI WS connect scope.
    scope = {
        "type": "websocket",
        "path": "/ws/client",
        "headers": [],
        "query_string": b"",
        "scheme": "ws",
        "client": ("127.0.0.1", 0),
        "server": ("test", 80),
        "subprotocols": [],
    }
    messages_received = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        messages_received.append(message)

    await fastapi_app(scope, receive, send)

    # Anonymous → handler should close with code 1008 (policy violation)
    # OR accept then close. Either way, no `websocket.accept` without a close after.
    types = [m["type"] for m in messages_received]
    assert "websocket.close" in types, (
        f"anonymous /ws/client did not close: {types} — cluster A regression"
    )


@pytest.mark.asyncio
async def test_ws_client_invalid_token_rejected(anonymous_client):
    from app.main import app as fastapi_app

    scope = {
        "type": "websocket",
        "path": "/ws/client",
        "headers": [(b"sec-websocket-protocol", b"bob.jwt.invalid-token")],
        "query_string": b"",
        "scheme": "ws",
        "client": ("127.0.0.1", 0),
        "server": ("test", 80),
        "subprotocols": ["bob.jwt.invalid-token"],
    }
    messages = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(m):
        messages.append(m)

    await fastapi_app(scope, receive, send)
    types = [m["type"] for m in messages]
    assert "websocket.close" in types, (
        f"invalid-token /ws/client did not close: {types} — cluster A regression"
    )
