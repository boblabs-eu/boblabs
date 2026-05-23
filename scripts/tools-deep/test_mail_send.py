"""Deep test for ``mail`` — sends one email via SMTP, verifies success.

REQUIRED ENV:
    MAIL_TEST_TO    — recipient address (your own mailbox is best)

PRECONDITIONS:
    Settings → Tool Configs → Mail filled in (SMTP host/port/user/pass/from).

This sends a real email. Use your own address.
"""
from __future__ import annotations
import sys, time
sys.path.insert(0, "/tmp/tools-deep")
from _harness import require_env, make_executor, run_tool, passed, fail, run  # noqa: E402

TOOL = "mail"


async def main():
    to = require_env("MAIL_TEST_TO")
    subject = f"bob smoke {int(time.time())}"
    body = "smoke test — safe to ignore"
    async with make_executor(timeout_sec=30) as (db, executor):
        res = await run_tool(executor, TOOL, {
            "action": "send", "to": to, "subject": subject, "body": body,
        })
        if not res["success"]:
            fail(TOOL, res["output"][:200])
        passed(TOOL, f"sent to {to} in {res['latency_ms']}ms")


run(main())
