"""Deep test for ``twitter`` — posts a tweet, then attempts to delete it.

REQUIRED ENV:
    (none — uses TWITTER_TEST_TEXT if set, else "bob smoke <ts>")

PRECONDITIONS:
    Settings → Tool Configs → Twitter filled in (consumer + access tokens).
    Twitter API account has paid credits (the read smoke fails 402 without).

This makes a real public tweet. The script tries to delete it but if the
delete fails the tweet stays up.
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, "/tmp/tools-deep")
from _harness import fail_or_skip, make_executor, optional_env, passed, run, run_tool  # noqa: E402

TOOL = "twitter"


async def main():
    text = optional_env("TWITTER_TEST_TEXT", f"bob smoke {int(time.time())}")
    async with make_executor(timeout_sec=30) as (db, executor):
        post = await run_tool(executor, TOOL, {"action": "post", "text": text})
        if not post["success"]:
            fail_or_skip(TOOL, post["output"])
        # Best-effort delete: depends on whether the tool returns a tweet id.
        tweet_id = ""
        out = post["output"]
        for tok in out.split():
            if tok.isdigit() and len(tok) >= 15:
                tweet_id = tok
                break
        if tweet_id:
            await run_tool(executor, TOOL, {"action": "delete", "tweet_id": tweet_id})
        passed(TOOL, f"posted{f' id={tweet_id}' if tweet_id else ''} in {post['latency_ms']}ms")


run(main())
