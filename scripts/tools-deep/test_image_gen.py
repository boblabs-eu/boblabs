"""Deep test for ``image_generate`` — generates a small image.

REQUIRED ENV (set on the bob-api container, not test-time):
    IMAGE_GEN_API_URL  — the configured image generation API
    IMAGE_GEN_API_KEY  — its API key
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, "/tmp/tools-deep")
from _harness import make_executor, run_tool, passed, fail, skip, run  # noqa: E402

TOOL = "image_generate"


async def main():
    if not os.environ.get("IMAGE_GEN_API_URL"):
        skip(TOOL, "IMAGE_GEN_API_URL not set on bob-api container")
    async with make_executor(timeout_sec=180) as (db, executor):
        res = await run_tool(executor, TOOL, {
            "prompt": "smoke test", "width": 256, "height": 256,
        })
        if not res["success"]:
            fail(TOOL, res["output"][:200])
        passed(TOOL, f"256x256 image generated in {res['latency_ms']}ms")


run(main())
