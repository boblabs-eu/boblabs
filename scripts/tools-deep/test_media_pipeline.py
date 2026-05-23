"""Deep test for ``media_pipeline`` — runs a registered GPU pipeline.

REQUIRED ENV:
    PIPELINE_NAME  — name of a configured pipeline (must exist in
                     PIPELINE_REGISTRY). If unset, the script lists names
                     and skips.

PRECONDITIONS:
    The named pipeline's GPU service is running and reachable.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, "/tmp/tools-deep")
from _harness import optional_env, make_executor, run_tool, passed, fail_or_skip, skip, run  # noqa: E402

TOOL = "media_pipeline"


async def main():
    name = optional_env("PIPELINE_NAME")
    if not name:
        try:
            from app.services.pipelines import PIPELINE_REGISTRY
            available = ", ".join(sorted(PIPELINE_REGISTRY.keys())) or "(none)"
        except Exception as exc:
            available = f"(import failed: {exc})"
        skip(TOOL, f"set PIPELINE_NAME — available: {available}")
    async with make_executor(timeout_sec=1800) as (db, executor):
        res = await run_tool(executor, TOOL, {
            "pipeline": name, "prompt": "smoke test",
        })
        if not res["success"]:
            fail_or_skip(TOOL, res["output"])
        passed(TOOL, f"{name} ran in {res['latency_ms']}ms")


run(main())
