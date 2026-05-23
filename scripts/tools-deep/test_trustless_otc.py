"""Deep test for ``trustless_otc`` — read-only check via list_chains.

REQUIRED ENV: (none)

PRECONDITIONS:
    Settings → Tool Configs → TrustlessOTC filled in (api_base_url + api_key).
"""
from __future__ import annotations
import sys
sys.path.insert(0, "/tmp/tools-deep")
from _harness import make_executor, run_tool, passed, fail_or_skip, run  # noqa: E402

TOOL = "trustless_otc"


async def main():
    async with make_executor(timeout_sec=20) as (db, executor):
        res = await run_tool(executor, TOOL, {"action": "list_chains"})
        if not res["success"]:
            fail_or_skip(TOOL, res["output"])
        passed(TOOL, f"list_chains ok in {res['latency_ms']}ms")


run(main())
