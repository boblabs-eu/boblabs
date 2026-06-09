"""Deep test for ``rag_ingest`` — ingests a tiny snippet, searches it, deletes.

REQUIRED ENV:
    RAG_TEST_COLLECTION  — name of a collection this lab can write to

PRECONDITIONS:
    The lab is linked to RAG_TEST_COLLECTION with write access.
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, "/tmp/tools-deep")
from _harness import fail_or_skip, make_executor, passed, require_env, run, run_tool  # noqa: E402

TOOL = "rag_ingest"


async def main():
    collection = require_env("RAG_TEST_COLLECTION")
    sentinel = f"bob-smoke-{int(time.time())}"
    fname = f"{sentinel}.txt"
    content = f"smoke test sentinel: {sentinel}. The colour of the sky is rosewater today."
    async with make_executor(timeout_sec=120) as (db, executor):
        ing = await run_tool(
            executor,
            TOOL,
            {
                "collection": collection,
                "filename": fname,
                "content": content,
            },
        )
        if not ing["success"]:
            fail_or_skip(TOOL, f"ingest: {ing['output']}")
        # Verify retrieval.
        srch = await run_tool(
            executor,
            "rag_search",
            {
                "query": sentinel,
                "collection": collection,
                "top_k": 3,
            },
        )
        if not srch["success"] or sentinel not in srch["output"]:
            fail_or_skip(TOOL, f"sentinel not found via rag_search: {srch['output']}")
        passed(
            TOOL, f"ingested + retrieved {sentinel} in {ing['latency_ms']}+{srch['latency_ms']}ms"
        )


run(main())
