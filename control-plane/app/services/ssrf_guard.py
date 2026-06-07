"""Shared SSRF guard: private-host detection + redirect-aware HTTP helpers.

Used by tool_web.web_extract and the RAG URL ingestion path (cluster E + M).
Replaces the ad-hoc per-call ``_is_private_host`` helpers that missed IPv6
loopback, link-local (``fe80::/10``), unique-local (``fc00::/7``), and the
full ``127.0.0.0/8`` range, and were single-shot so an attacker-controlled
HTTP server could 302 the client into the internal network without
re-validation.

The guard is intentionally fail-closed:
  - unknown hostname → blocked (treat as private)
  - resolver failure → blocked
  - any hop in a redirect chain → must pass the same check
  - non-http(s) schemes → blocked

Callers that want raw httpx for known-good external URLs (e.g. CoinGecko)
should NOT go through this guard; it is intended only for agent-supplied or
end-user-supplied URLs.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Iterable
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Public exports
__all__ = [
    "is_private_host",
    "validate_public_url",
    "safe_get",
    "PrivateHostError",
    "RedirectLoopError",
    "DEFAULT_MAX_REDIRECTS",
    "DEFAULT_MAX_BYTES",
]


DEFAULT_MAX_REDIRECTS = 5
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB

_ALLOWED_SCHEMES = {"http", "https"}


class PrivateHostError(ValueError):
    """Raised when a URL resolves to or redirects to a private address."""


class RedirectLoopError(ValueError):
    """Raised when redirect chain exceeds the configured maximum."""


def _classify_ip(addr: ipaddress._BaseAddress) -> bool:
    """Return True if ``addr`` is in any private/internal range."""
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def is_private_host(hostname: str | None) -> bool:
    """Return True if ``hostname`` is empty, a literal private IP, or
    resolves to a private IP. Fail-closed on lookup errors.

    Handles IPv4 (incl. full 127.0.0.0/8, 169.254.0.0/16, 10.0.0.0/8,
    172.16.0.0/12, 192.168.0.0/16, 0.0.0.0) and IPv6 (incl. ``::1``,
    ``fe80::/10``, ``fc00::/7``, ``::``, multicast). Docker container
    hostnames (no dots, e.g. ``bob-db``) are also blocked.
    """
    if not hostname:
        return True
    # Strip bracket form ``[::1]`` returned by urlparse on IPv6
    h = hostname.strip().strip("[]").lower()
    if not h:
        return True
    if h == "localhost" or h.endswith(".local") or h.endswith(".internal"):
        return True

    # Literal IP form?
    try:
        addr = ipaddress.ip_address(h)
        return _classify_ip(addr)
    except ValueError:
        pass

    # Docker / container hostnames have no dots.
    if "." not in h:
        return True

    # Resolve via system resolver. Fail-closed on any error.
    try:
        infos = socket.getaddrinfo(h, None)
    except (socket.gaierror, UnicodeError, OSError):
        return True

    for fam, _kind, _proto, _canon, sockaddr in infos:
        # sockaddr is (host, port) for IPv4, (host, port, flowinfo, scope) for IPv6
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return True
        if _classify_ip(addr):
            return True

    return False


def validate_public_url(url: str) -> str:
    """Return ``url`` unchanged if it is a public http(s) URL; raise otherwise.

    Performs a single hostname check; redirects are re-validated by
    :func:`safe_get` per hop.
    """
    if not url:
        raise PrivateHostError("empty URL")
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise PrivateHostError(f"scheme '{parsed.scheme}' is not allowed")
    if is_private_host(parsed.hostname):
        raise PrivateHostError(f"host '{parsed.hostname}' is private or unreachable")
    return url


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict | None = None,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    allowed_methods: Iterable[str] = ("GET",),
) -> httpx.Response:
    """GET ``url`` with manual redirect handling that re-validates every hop.

    Each 3xx response's ``Location`` is checked with :func:`validate_public_url`
    before following it. Caps response size at ``max_bytes``.

    Callers MUST pass an :class:`httpx.AsyncClient` constructed with
    ``follow_redirects=False`` (which is the httpx default for the
    constructor — they just need to NOT pass True).
    """
    current = validate_public_url(url)
    method = "GET"
    if method not in {m.upper() for m in allowed_methods}:
        raise ValueError(f"method {method!r} not in allowed_methods")

    for hop in range(max_redirects + 1):
        request = client.build_request(method, current, headers=headers)
        # Stream so we can size-cap before fully loading into memory.
        resp = await client.send(request, stream=True)
        try:
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    return resp
                # Resolve relative Location.
                current = str(httpx.URL(current).join(location))
                validate_public_url(current)
                await resp.aclose()
                continue
            # Terminal response — read with byte cap.
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_raw():
                total += len(chunk)
                if total > max_bytes:
                    await resp.aclose()
                    raise PrivateHostError(
                        f"response exceeded max_bytes={max_bytes}"
                    )
                chunks.append(chunk)
            body = b"".join(chunks)
            # Rebuild response with materialised body so callers can use
            # the standard .text / .json() / .headers interface.
            return httpx.Response(
                status_code=resp.status_code,
                headers=resp.headers,
                content=body,
                request=request,
            )
        finally:
            # If we broke out of the loop, the stream is already closed; the
            # follow-redirect branch above explicitly aclose()d. Safe to
            # call again (httpx makes aclose idempotent).
            await resp.aclose()

    raise RedirectLoopError(
        f"exceeded {max_redirects} redirects starting from {url!r}"
    )
