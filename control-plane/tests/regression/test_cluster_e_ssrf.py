"""Cluster E — SSRF guard regression.

The original fix replaced ad-hoc `_is_private_host` helpers (IPv4-only,
single-hop) with `app.services.ssrf_guard.is_private_host` + `safe_get`
that re-validate redirects per hop, cover IPv6 loopback/link-local/ULA,
and the full 127.0.0.0/8 range.

These tests assert each invariant the original audit flagged.
"""

from __future__ import annotations

import pytest

from app.services.ssrf_guard import (
    PrivateHostError,
    is_private_host,
    validate_public_url,
)

pytestmark = pytest.mark.regression


# ── is_private_host: IPv4 ─────────────────────────────────────────


@pytest.mark.parametrize("h", [
    "127.0.0.1", "127.0.0.2", "127.255.255.254",     # full 127.0.0.0/8
    "10.0.0.1", "10.255.255.255",                     # RFC1918
    "172.16.0.1", "172.31.255.255",
    "192.168.0.1", "192.168.255.255",
    "169.254.169.254",                                # cloud metadata
    "0.0.0.0",
    "224.0.0.1",                                      # multicast
])
def test_ipv4_private_blocked(h):
    assert is_private_host(h) is True


@pytest.mark.parametrize("h", [
    "1.1.1.1", "8.8.8.8", "13.107.42.14",
])
def test_ipv4_public_allowed(h):
    assert is_private_host(h) is False


# ── is_private_host: IPv6 ─────────────────────────────────────────


@pytest.mark.parametrize("h", [
    "::1",                                            # loopback
    "[::1]",                                          # bracketed form
    "fe80::1", "fe80::cafe",                          # link-local
    "fc00::1", "fd12:3456:789a::1",                   # unique-local
    "::",                                             # unspecified
    "ff02::1",                                        # multicast
])
def test_ipv6_private_blocked(h):
    assert is_private_host(h) is True


def test_ipv6_public_allowed():
    # Cloudflare 1.1.1.1 IPv6 — global unicast.
    assert is_private_host("2606:4700:4700::1111") is False


# ── Hostname-based blocks ─────────────────────────────────────────


@pytest.mark.parametrize("h", [
    "localhost",
    "bob-db",            # docker compose service name (no dots)
    "redis",
    "bob-api.local",     # .local suffix
    "metrics.internal",  # .internal suffix
    "",                  # empty
    None,                # None
])
def test_hostname_private_blocked(h):
    assert is_private_host(h) is True


# ── validate_public_url ───────────────────────────────────────────


@pytest.mark.parametrize("u", [
    "http://127.0.0.1/x",
    "http://[::1]/x",
    "http://169.254.169.254/latest/meta-data/",
    "https://localhost/",
    "https://bob-db:5432/",
])
def test_validate_public_url_rejects_private(u):
    with pytest.raises(PrivateHostError):
        validate_public_url(u)


@pytest.mark.parametrize("u", [
    "",
    "ftp://example.com/x",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "gopher://example.com/",
])
def test_validate_public_url_rejects_bad_schemes(u):
    with pytest.raises(PrivateHostError):
        validate_public_url(u)


def test_validate_public_url_accepts_public():
    assert validate_public_url("https://example.com/") == "https://example.com/"
