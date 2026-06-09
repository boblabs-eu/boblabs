"""Shared helpers for deep per-tool tests.

Each ``test_<tool>.py`` script in this directory imports this module to
share the ToolExecutor bootstrap, env-var enforcement, and result-line
emission. Designed to run **inside the bob-api container** — call sites
look like::

    docker compose cp scripts/tools-deep bob-api:/tmp/tools-deep
    docker compose exec -T bob-api python /tmp/tools-deep/test_mail_send.py

Or the aggregator ``run_all.py`` does both steps for every script.

Verdicts:
  PASS    — the tool returned ``success=True`` and the script's
            additional checks (if any) passed.
  FAIL    — the tool returned ``success=False`` or raised; this is
            considered a real failure (exit 1).
  SKIPPED — a required env var or DB precondition is missing (exit 2);
            the aggregator counts these but does not fail the run.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

REPORT_PATH = Path("/tmp/tool-test-report-deep.md")


def require_env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None or v == "":
        print(f"MISSING ENV: {name}")
        sys.exit(2)
    return v


def optional_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default) or default


def _append_report(tool: str, verdict: str, reason: str) -> None:
    try:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        new = not REPORT_PATH.exists()
        with REPORT_PATH.open("a") as f:
            if new:
                f.write("# Tool Deep Test Report\n\n")
                f.write("| Tool | Verdict | Reason |\n")
                f.write("|------|---------|--------|\n")
            safe_reason = (reason or "").replace("|", "\\|").replace("\n", " ")[:200]
            f.write(f"| `{tool}` | {verdict} | {safe_reason} |\n")
    except OSError:
        pass


def passed(tool: str, reason: str = "") -> None:
    print(f"RESULT: {tool} PASS{f' — {reason}' if reason else ''}")
    _append_report(tool, "PASS", reason)
    sys.exit(0)


def fail(tool: str, reason: str) -> None:
    print(f"RESULT: {tool} FAIL — {reason}")
    _append_report(tool, "FAIL", reason)
    sys.exit(1)


def skip(tool: str, reason: str) -> None:
    print(f"RESULT: {tool} SKIPPED — {reason}")
    _append_report(tool, "SKIPPED", reason)
    sys.exit(2)


# Substrings that indicate "wiring is fine, the operator just hasn't
# supplied creds / quota / runner". These are SKIPPED, not FAILED — the
# deep test can't validate something that hasn't been configured yet.
_PRECONDITION_FRAGMENTS = (
    "not configured",
    "no script runners connected",
    "402 payment required",
    "no credits to fulfill",
    "is not configured",
    "all connection attempts failed",
    "all providers failed",
    "write access denied",
    "access denied to collection",
)


def fail_or_skip(tool: str, output: str) -> None:
    """Classify a tool failure: SKIPPED for known precondition gaps, FAIL otherwise."""
    lower = output.lower()
    if any(frag in lower for frag in _PRECONDITION_FRAGMENTS):
        skip(tool, output[:200])
    fail(tool, output[:200])


@asynccontextmanager
async def make_executor(timeout_sec: int = 60):
    """Yield ``(db, executor)`` against the first lab in the DB.

    Skips if no lab exists. Uses the default ToolExecutor signature today;
    when ``invoking_user_id`` is added (see plan stage 2), it'll be
    plumbed in here.
    """
    from app.database import async_session
    from app.models.orchestrator import Lab
    from app.services.tool_executor import ToolExecutor
    from sqlalchemy import select

    async with async_session() as db:
        lab = (await db.execute(select(Lab).limit(1))).scalars().first()
        if lab is None:
            skip(_caller_tool_name(), "no lab in DB")
        executor = ToolExecutor(lab_id=lab.id, db=db, timeout_sec=timeout_sec)
        yield db, executor


def _caller_tool_name() -> str:
    """Best-effort: derive the tool name from the calling script filename."""
    try:
        return Path(sys.argv[0]).stem.replace("test_", "")
    except Exception:
        return "unknown"


async def run_tool(executor, name: str, args: dict) -> dict:
    """Run one tool call. Returns ``{success, output, latency_ms}``."""
    t0 = time.monotonic()
    try:
        res = await executor.execute(name, args)
        return {
            "success": bool(res.get("success")),
            "output": str(res.get("output", "")),
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "raw": res,
        }
    except Exception as exc:
        return {
            "success": False,
            "output": f"Exception: {exc}\n{traceback.format_exc(limit=4)}",
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "raw": {},
        }


def run(coro) -> None:
    """Top-level entry — runs the test coroutine."""
    asyncio.run(coro)
