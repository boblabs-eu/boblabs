"""CSO Finding #3 — every production Dockerfile must drop root.

Pre-fix: 8 production Dockerfiles ran their main process as root. The
highest-impact one was ``sandbox/Dockerfile`` — that container IS the
untrusted code-execution boundary, so any future python_exec /
shell_exec escape would have run as root.

Post-fix: every production Dockerfile declares ``USER`` at the end,
running the service as uid 1000 (named per-service: bobapi, sandbox,
showroom, remotion, bobagent, gpu). Operator migration for existing
volumes is documented in docs/AGENT.md ("CSO #3" section).

This test is the tripwire: if a future commit introduces a new
Dockerfile or strips the ``USER`` line from an existing one, the
suite fails immediately. Adding a new service to the list requires
explicitly updating PRODUCTION_DOCKERFILES below, forcing a
conscious decision about the auth posture.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


# Every production Dockerfile that must declare USER. If you add a new
# service, add its Dockerfile here AND ensure the new Dockerfile
# follows the same pattern (useradd uid 1000 + USER directive).
PRODUCTION_DOCKERFILES = [
    "agent/Dockerfile",
    "control-plane/Dockerfile",
    "sandbox/Dockerfile",
    "showroom-api/Dockerfile",
    "remotion-api/Dockerfile",
    "gpu-services/rvc-api/Dockerfile",
    "gpu-services/bark-api/Dockerfile",
    "gpu-services/coqui-tts-api/Dockerfile",
    "gpu-services/stt-api/Dockerfile",
    "gpu-services/musicgen-api/Dockerfile",
    "gpu-services/ltx-video-api/Dockerfile",
    "gpu-services/wan-video-api/Dockerfile",
]


# Pattern: a `USER` directive whose target is a non-root identifier.
# Accepts both `USER <name>` and `USER <uid>` (must not be 0 or "root").
_USER_RE = re.compile(r"^USER\s+(?P<id>\S+)\s*$", re.M)


def _read(path: str) -> str:
    full = REPO_ROOT / path
    assert full.is_file(), f"Expected {full} to exist"
    return full.read_text(encoding="utf-8")


def _present_dockerfiles() -> list[str]:
    """Filter PRODUCTION_DOCKERFILES to entries that exist in the current
    tree. Bob-manager-private services (showroom-api) ship in the source
    repo but not in the public open-source extract, so the test must
    cover only what's present rather than failing on missing files."""
    return [p for p in PRODUCTION_DOCKERFILES if (REPO_ROOT / p).is_file()]


def test_every_production_dockerfile_drops_root() -> None:
    """Every Dockerfile in PRODUCTION_DOCKERFILES must end with a
    `USER` directive that is NOT root / uid 0. The check is positional:
    we require the LAST USER directive (since a Dockerfile can switch
    users temporarily during build) to target a non-root identity."""
    failures: list[str] = []
    for path in _present_dockerfiles():
        body = _read(path)
        matches = _USER_RE.findall(body)
        if not matches:
            failures.append(f"{path}: no USER directive at all")
            continue
        last = matches[-1]
        if last in ("root", "0", "0:0"):
            failures.append(f"{path}: last USER is {last!r}")
    assert not failures, (
        "CSO #3: production Dockerfiles must drop root. Failures:\n  - " + "\n  - ".join(failures)
    )


def test_dockerfiles_use_uid_1000() -> None:
    """Convention: all services share uid 1000 so a single chown of a
    shared volume covers every consumer. If a future Dockerfile picks
    a different uid (e.g. for a service with its own volume that
    nothing else writes to), that's a conscious choice — update this
    test AND document the migration in docs/AGENT.md."""
    bad_uids: list[str] = []
    for path in _present_dockerfiles():
        body = _read(path)
        # Look for the useradd that wires uid 1000.
        if not re.search(r"useradd\s+(?:[^\\\n]*\s)?-u\s+1000\b", body):
            bad_uids.append(path)
    assert not bad_uids, (
        "CSO #3: all production Dockerfiles must use `useradd -u 1000 ...` "
        "so a single chown of a shared volume covers every consumer. "
        f"Files using a different uid (or no useradd): {bad_uids}"
    )
