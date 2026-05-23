"""Deep test for ``media_post`` — publishes (or dry-runs) one social post.

REQUIRED ENV:
    MEDIA_POST_PLATFORM   — one of: x, linkedin, instagram, facebook
    MEDIA_POST_ACCOUNT_ID — the account_id from
                            GET /tool-configs/social_<platform>/accounts
    MEDIA_POST_DRY_RUN    — set to '1' to short-circuit publish (recommended
                            for the first run)
    MEDIA_POST_CONTENT    — optional; default "bob smoke <ts>"

PRECONDITIONS:
    Settings → <platform> — accounts has a row with MEDIA_POST_ACCOUNT_ID
    and real credentials (or use DRY_RUN=1 to verify wiring without posting).
"""
from __future__ import annotations
import os, sys, time
sys.path.insert(0, "/tmp/tools-deep")
from _harness import require_env, optional_env, make_executor, run_tool, passed, fail, run  # noqa: E402

TOOL = "media_post"


async def main():
    platform = require_env("MEDIA_POST_PLATFORM")
    account_id = require_env("MEDIA_POST_ACCOUNT_ID")
    dry_run = os.environ.get("MEDIA_POST_DRY_RUN") == "1"
    content = optional_env("MEDIA_POST_CONTENT", f"bob smoke {int(time.time())}")
    async with make_executor(timeout_sec=30) as (db, executor):
        # First, list accounts to confirm the account_id exists.
        listed = await run_tool(executor, TOOL, {
            "platform": platform, "action": "list_accounts",
        })
        if not listed["success"]:
            fail(TOOL, f"list_accounts failed: {listed['output'][:200]}")
        if account_id not in listed["output"]:
            fail(TOOL, f"account_id={account_id} not in list_accounts output for {platform}")
        if dry_run:
            passed(TOOL, f"dry-run: account_id={account_id} found on {platform}")
        # Real publish.
        res = await run_tool(executor, TOOL, {
            "platform": platform, "account_id": account_id,
            "action": "post", "content": content,
        })
        if not res["success"]:
            fail(TOOL, res["output"][:200])
        passed(TOOL, f"posted to {platform} as {account_id} in {res['latency_ms']}ms")


run(main())
