"""Bob Manager — HTTP request logging middleware.

Captures every HTTP request that reaches the FastAPI app and persists a row
to `request_log`. The DB insert is fire-and-forget (background task) so the
response path stays as fast as before.

Modules and severities are derived from the path and status code so the
admin dashboard can group/filter without any caller cooperation.
"""

import asyncio
import logging
import re
import time
from typing import Awaitable, Callable

from jose import JWTError, jwt
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.database import async_session

logger = logging.getLogger(__name__)


# Path prefixes that should NOT be logged (too noisy or pointless).
_SKIP_PREFIXES: tuple[str, ...] = (
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
    # Admin logs UI itself polls these — skip to avoid feedback loop noise.
    "/api/v1/admin/logs",
)


# Ordered (longest-first) list of (regex, module-name) pairs.
_MODULE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^/api/v1/auth(/|$)"),                "auth"),
    (re.compile(r"^/api/v1/access-tokens(/|$)"),       "tokens"),
    (re.compile(r"^/api/v1/library-agents(/|$)"),      "library-agents"),
    (re.compile(r"^/api/v1/labs(/|$)"),                "labs"),
    (re.compile(r"^/api/v1/orchestrator(/|$)"),        "orchestrator"),
    (re.compile(r"^/api/v1/tool-sets(/|$)"),           "tool-sets"),
    (re.compile(r"^/api/v1/prompt-templates(/|$)"),    "prompt-templates"),
    (re.compile(r"^/api/v1/cron-jobs(/|$)"),           "cron-jobs"),
    (re.compile(r"^/api/v1/rag(/|$)"),                 "rag"),
    (re.compile(r"^/api/v1/web3(/|$)"),                "web3"),
    (re.compile(r"^/api/v1/projects(/|$)"),            "projects"),
    (re.compile(r"^/api/v1/servers(/|$)"),             "servers"),
    (re.compile(r"^/api/v1/workflows(/|$)"),           "workflows"),
    (re.compile(r"^/api/v1/commands(/|$)"),            "commands"),
    (re.compile(r"^/api/v1/modules(/|$)"),             "modules"),
    (re.compile(r"^/api/v1/resources(/|$)"),           "resources"),
    (re.compile(r"^/api/v1/news(/|$)"),                "news"),
    (re.compile(r"^/api/v1/metrics(/|$)"),             "metrics"),
    (re.compile(r"^/api/v1/internal/apps(/|$)"),       "internal-apps"),
    (re.compile(r"^/api/v1/outreach(/|$)"),            "outreach"),
    (re.compile(r"^/api/v1/server-access(/|$)"),       "server-access"),
    (re.compile(r"^/api/v1/tool-configs(/|$)"),        "tool-configs"),
    (re.compile(r"^/api/v1/public(/|$)"),              "public"),
    (re.compile(r"^/api/"),                            "api"),
    (re.compile(r"^/ws/"),                             "websocket"),
]


def _module_for_path(path: str) -> str:
    for pattern, name in _MODULE_RULES:
        if pattern.search(path):
            return name
    return "other"


def _severity_for_status(status_code: int) -> str:
    if status_code >= 500:
        return "error"
    if status_code >= 400:
        return "warn"
    return "info"


def _client_ip(request: Request) -> str | None:
    """Best-effort: prefer X-Forwarded-For (first hop), then X-Real-IP, then peer."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        first = fwd.split(",", 1)[0].strip()
        if first:
            return first
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    if request.client:
        return request.client.host
    return None


def _decode_user(request: Request) -> tuple[str | None, str | None]:
    """Peek at the bearer token to extract user info — never raise."""
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None, None
    token = auth[7:].strip()
    if not token:
        return None, None
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return None, None
    return payload.get("sub"), payload.get("role")


async def _persist(row: dict) -> None:
    """Insert a single log row using its own session (fire-and-forget)."""
    try:
        async with async_session() as db:
            await db.execute(
                text(
                    "INSERT INTO request_log "
                    "(timestamp, ip, method, path, query, status, duration_ms, "
                    " user_email, user_role, user_agent, referer, module, severity, error_msg) "
                    "VALUES (NOW(), :ip, :method, :path, :query, :status, :duration_ms, "
                    " :user_email, :user_role, :user_agent, :referer, :module, :severity, :error_msg)"
                ),
                row,
            )
            await db.commit()
    except Exception as e:  # noqa: BLE001
        # Logging must never crash the app — swallow and warn once per failure.
        logger.warning("request_log insert failed: %s", e)


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """Append one row per HTTP request to `request_log`."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        start = time.perf_counter()
        error_msg: str | None = None
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:  # noqa: BLE001
            error_msg = f"{type(exc).__name__}: {exc}"[:500]
            raise
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            user_email, user_role = _decode_user(request)
            row = {
                "ip": _client_ip(request),
                "method": request.method,
                "path": _trunc(path, 1000),
                "query": _trunc(str(request.url.query), 1000),
                "status": status_code,
                "duration_ms": duration_ms,
                "user_email": _trunc(user_email, 255),
                "user_role": _trunc(user_role, 64),
                "user_agent": _trunc(request.headers.get("user-agent"), 500),
                "referer": _trunc(request.headers.get("referer"), 1000),
                "module": _module_for_path(path),
                "severity": _severity_for_status(status_code),
                "error_msg": error_msg,
            }
            asyncio.create_task(_persist(row))


def _trunc(value: str | None, limit: int) -> str | None:
    if value is None or value == "":
        return None
    return value[:limit]
