"""Deep test for ``postiz`` — confirms the API answers and integrations list.

REQUIRED ENV: (none)

PRECONDITIONS:
    Settings → Tool Configs → Postiz filled in (api_url + api_key).
    The Postiz container reachable at api_url.

Read-only: lists configured integrations. No posts are scheduled.
"""
from __future__ import annotations
import sys
sys.path.insert(0, "/tmp/tools-deep")
from _harness import make_executor, run_tool, passed, fail_or_skip, run  # noqa: E402

TOOL = "postiz"


async def main():
    async with make_executor(timeout_sec=20) as (db, executor):
        res = await run_tool(executor, TOOL, {"action": "list_integrations"})
        if not res["success"]:
            fail_or_skip(TOOL, res["output"])
        passed(TOOL, f"list_integrations ok in {res['latency_ms']}ms")


run(main())
