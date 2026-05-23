"""Deep test for ``call_agent`` — verifies the dispatch path.

Requires a ``ToolExecutor`` with ``_call_agent_handler`` wired in. The bare
executor used by these tests has no handler, so the tool returns the
"not available in this context" sentinel — which we treat as a controlled
SKIPPED, not a failure. Real coverage for call_agent comes from running
an actual lab turn (the lab runner injects the handler).

REQUIRED ENV: (none)
"""
from __future__ import annotations
import sys
sys.path.insert(0, "/tmp/tools-deep")
from _harness import make_executor, run_tool, passed, fail, skip, run  # noqa: E402

TOOL = "call_agent"


async def main():
    async with make_executor(timeout_sec=30) as (db, executor):
        res = await run_tool(executor, TOOL, {
            "agent_name": "smoke", "instruction": "say ack",
        })
        out = res["output"].lower()
        if "not available in this context" in out:
            skip(TOOL, "no _call_agent_handler — exercise via a real lab turn instead")
        if not res["success"]:
            fail(TOOL, res["output"][:200])
        passed(TOOL, f"dispatched in {res['latency_ms']}ms")


run(main())
