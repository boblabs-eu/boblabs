"""Deep test for ``video_generate`` — renders a 1-second placeholder MP4.

REQUIRED ENV (set on bob-api container, has a sane default):
    REMOTION_API_URL  (default: http://bob-remotion:3020)

PRECONDITIONS:
    bob-remotion service running. Render takes ~10-30s.
"""
from __future__ import annotations
import sys
sys.path.insert(0, "/tmp/tools-deep")
from _harness import make_executor, run_tool, passed, fail, run  # noqa: E402

TOOL = "video_generate"

REMOTION_TSX = '''import {AbsoluteFill} from "remotion";
export const Main = () => <AbsoluteFill style={{background:"#222",color:"#fff",
  display:"flex",alignItems:"center",justifyContent:"center",fontSize:60}}>smoke</AbsoluteFill>;
'''


async def main():
    async with make_executor(timeout_sec=600) as (db, executor):
        res = await run_tool(executor, TOOL, {
            "code": REMOTION_TSX,
            "width": 320, "height": 180, "fps": 30, "duration_in_frames": 30,
        })
        if not res["success"]:
            fail(TOOL, res["output"][:200])
        passed(TOOL, f"320x180@30fps render in {res['latency_ms']}ms")


run(main())
