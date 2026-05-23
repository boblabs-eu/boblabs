"""Deep test for ``audio_generate`` — generates a short audio clip.

REQUIRED ENV:
    AUDIO_GEN_SCRIPT  (default: "riffusion") — the script runner to use
    AUDIO_GEN_PROMPT  (default: "smoke test")

PRECONDITIONS:
    GPU available; the configured script runner reachable. Long: ~30-90s.
"""
from __future__ import annotations
import sys
sys.path.insert(0, "/tmp/tools-deep")
from _harness import optional_env, make_executor, run_tool, passed, fail_or_skip, run  # noqa: E402

TOOL = "audio_generate"


async def main():
    script = optional_env("AUDIO_GEN_SCRIPT", "riffusion")
    prompt = optional_env("AUDIO_GEN_PROMPT", "smoke test")
    async with make_executor(timeout_sec=300) as (db, executor):
        res = await run_tool(executor, TOOL, {
            "script": script, "prompt": prompt, "duration_sec": 4,
        })
        if not res["success"]:
            fail_or_skip(TOOL, res["output"])
        passed(TOOL, f"{script} 4s clip in {res['latency_ms']}ms")


run(main())
