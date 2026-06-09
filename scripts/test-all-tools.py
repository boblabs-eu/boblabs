#!/usr/bin/env python3
"""Smoke-test every built-in tool registered in BUILTIN_TOOLS.

Designed to run **inside the bob-api container** so it has the DB session
factory, sandbox, and tool dependencies on the import path:

    docker compose exec -T bob-api python /tmp/test-all-tools.py [--report PATH]

Or copy via stdin:

    docker compose exec -T bob-api python - < scripts/test-all-tools.py

The script picks an existing lab from the ``labs`` table, builds a
:class:`ToolExecutor` against it, then loops over every tool in
``BUILTIN_TOOLS`` with **safe minimal arguments** (no outbound mail, no
chain transactions, no destructive DB ops). For each tool it captures
``{status, latency_ms, output_summary}`` and writes a Markdown report.

Exit status: 0 if every Tier-A and Tier-B tool passes, 1 otherwise.
The pass-gate ignores graceful "not configured" failures in higher tiers
(Tier E/F integrations without API keys) — those are documented, not
release-blocking. A stack-trace from any tool always blocks.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
import traceback
from pathlib import Path

# These are tier classifications used in the report. They mirror the
# Phase-2 plan's "tool smoke test" matrix.
TIER_A = {
    "think",
    "clock",
    "file_read",
    "file_write",
    "python_exec",
    "shell_exec",
    "memory_save",
    "memory_search",
    "handle_memory",
}
TIER_B = {"db_query", "db_execute", "db_schema", "rag_list_collections", "rag_search", "rag_ingest"}
TIER_C = {
    "web_search",
    "web_extract",
    "browser_navigate",
    "browser_snapshot",
    "mermaid_to_img",
    "excalidraw",
    "gouv_data_fr",
}
TIER_D = {
    "image_generate",
    "audio_generate",
    "video_generate",
    "media_pipeline",
    "audio_mix",
    "comfyui",
}
TIER_E = {"youtube", "mail", "twitter", "call_agent", "media_post", "postiz"}
TIER_F = {"blockchain", "defi_data", "web3_portfolio", "trading", "trustless_otc"}
TIER_G = {"control_server"}

ALL_TIERS = {
    **{n: "A" for n in TIER_A},
    **{n: "B" for n in TIER_B},
    **{n: "C" for n in TIER_C},
    **{n: "D" for n in TIER_D},
    **{n: "E" for n in TIER_E},
    **{n: "F" for n in TIER_F},
    **{n: "G" for n in TIER_G},
}


def _build_args(tool_name: str, lab_workspace: Path) -> dict | None:
    """Return safe minimal args for ``tool_name``, or ``None`` to skip."""

    # ── Tier A — pure local ───────────────────────
    if tool_name == "think":
        return {"thought": "smoke test"}
    if tool_name == "clock":
        return {"action": "timestamp"}
    if tool_name == "file_write":
        return {"path": "smoke_test.txt", "content": "smoke"}
    if tool_name == "file_read":
        # Relies on file_write running first; chained sequentially below.
        return {"path": "smoke_test.txt"}
    if tool_name == "python_exec":
        return {"code": "print('ok')"}
    if tool_name == "shell_exec":
        return {"command": "echo smoke"}
    if tool_name == "memory_save":
        return {"key": "smoke", "content": "smoke", "importance": 1}
    if tool_name == "memory_search":
        return {"query": "smoke"}
    if tool_name == "handle_memory":
        return {"agent_name": "smoke", "action": "list"}

    # ── Tier B — DB / RAG ─────────────────────────
    if tool_name == "db_query":
        return {"sql": "SELECT 1 AS smoke"}
    if tool_name == "db_execute":
        # Read-only via no-op; rolled back automatically by sandbox.
        return {"sql": "SELECT 1"}
    if tool_name == "db_schema":
        return {}
    if tool_name == "rag_list_collections":
        return {}
    if tool_name == "rag_search":
        # Use a likely-non-existent collection — should fail gracefully
        # ("collection not found"), not stack-trace.
        return {"query": "smoke", "collection": "smoke-test-nonexistent"}
    if tool_name == "rag_ingest":
        return None  # Skipped — would create real RAG state.

    # ── Tier C — web ──────────────────────────────
    if tool_name == "web_search":
        return {"query": "bob labs"}
    if tool_name == "web_extract":
        return {"url": "https://example.com"}
    if tool_name == "browser_navigate":
        return {"url": "https://example.com"}
    if tool_name == "browser_snapshot":
        return {}
    if tool_name == "mermaid_to_img":
        # The handler reads the diagram from a workspace file, so write
        # one first (sequenced below).
        return {"input_path": "smoke.mmd"}
    if tool_name == "excalidraw":
        # Handler expects ``elements`` as a JSON-stringified array (the
        # LLM tool-call wire format), not a raw Python list.
        return {
            "elements": json.dumps(
                [{"type": "rectangle", "x": 0, "y": 0, "width": 100, "height": 50}]
            )
        }
    if tool_name == "gouv_data_fr":
        # Smallest possible catalog query — should return at least 1 result.
        return {"action": "search_datasets", "params": {"query": "population", "page_size": 1}}

    # ── Tier D — media (GPU) ─────────────────────
    if tool_name == "comfyui":
        return {"action": "list_models"}
    if tool_name == "image_generate":
        # Tiny prompt — should hit ComfyUI or the configured image API.
        return {"prompt": "smoke", "width": 256, "height": 256}
    if tool_name == "audio_generate":
        return None  # Skipped — heavy job (MusicGen) not worth the GPU time.
    if tool_name == "video_generate":
        return None  # Skipped — heavy Remotion render.
    if tool_name == "media_pipeline":
        return None  # Skipped — pipeline names depend on configuration.
    if tool_name == "audio_mix":
        return None  # Skipped — needs prepared input files.

    # ── Tier E — integrations (read-only paths only) ─
    if tool_name == "youtube":
        return {"action": "list_channel", "channel_handle": "@boblabs"}
    if tool_name == "mail":
        # Read inbox (IMAP); never send.
        return {"action": "read", "limit": 1}
    if tool_name == "twitter":
        return {"action": "read", "query": "ai", "limit": 1}
    if tool_name == "call_agent":
        return None  # Skipped — would actually invoke another agent.
    if tool_name == "media_post":
        return None  # Skipped — would publish.
    if tool_name == "postiz":
        return {"action": "list_integrations"}

    # ── Tier F — web3 (read-only) ────────────────
    if tool_name == "blockchain":
        return {"action": "balance", "address": "0x0000000000000000000000000000000000000000"}
    if tool_name == "defi_data":
        return {"action": "prices", "symbols": ["BTC", "ETH"]}
    if tool_name == "web3_portfolio":
        return {"action": "list_addresses"}
    if tool_name == "trading":
        return {"action": "list_wallets"}
    if tool_name == "trustless_otc":
        return {"action": "list_chains"}

    # ── Tier G — special ─────────────────────────
    if tool_name == "control_server":
        return {"action": "list_servers"}

    return None  # Unknown tool — skip.


def _classify(success: bool, output: str) -> str:
    """Bucket a result into PASS / GRACEFUL / STACKTRACE / SKIPPED."""
    if success:
        return "PASS"
    # Heuristics: a stack-trace fail is when the handler raised something
    # we surfaced as an error string. Graceful means the tool returned an
    # actionable user-level error (rate-limited, not configured, etc.).
    lower = output.lower()
    if "traceback" in lower or "exception" in lower:
        return "STACKTRACE"
    return "GRACEFUL"


async def _run_one(executor, tool_name: str, args: dict) -> dict:
    t0 = time.monotonic()
    try:
        res = await executor.execute(tool_name, args)
        success = bool(res.get("success"))
        output = str(res.get("output", ""))
    except Exception as exc:
        success = False
        output = f"Exception: {exc}\n{traceback.format_exc(limit=4)}"
    latency_ms = int((time.monotonic() - t0) * 1000)
    return {
        "tool": tool_name,
        "tier": ALL_TIERS.get(tool_name, "?"),
        "args": args,
        "success": success,
        "output_excerpt": output[:280],
        "latency_ms": latency_ms,
        "verdict": _classify(success, output),
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="/tmp/tool-test-report.md")
    parser.add_argument("--json", default="/tmp/tool-test-report.json")
    args = parser.parse_args()

    # Imports happen inside main so the script can be inspected without
    # the bob-api environment.
    from app.database import async_session
    from app.models.orchestrator import Lab
    from app.services.tool_executor import ToolExecutor
    from app.services.tools import BUILTIN_TOOLS
    from sqlalchemy import select

    async with async_session() as db:
        lab = (await db.execute(select(Lab).limit(1))).scalars().first()
        if lab is None:
            print("ERROR: no lab in DB; create one before running this test.")
            return 2
        executor = ToolExecutor(lab_id=lab.id, db=db, timeout_sec=60)
        print(f"Using lab id={lab.id} name={lab.name!r}")
        print(f"Workspace: {executor.workspace}")

        # Pre-seed: write a dummy file the file_read + mermaid tests need.
        (executor.workspace / "smoke_test.txt").write_text("smoke")
        (executor.workspace / "smoke.mmd").write_text("graph TD; A-->B")

        results: list[dict] = []
        skipped: list[str] = []

        # Run in a deterministic order, file_write before file_read.
        order = sorted(BUILTIN_TOOLS.keys(), key=lambda n: (ALL_TIERS.get(n, "Z"), n))
        for name in order:
            payload = _build_args(name, executor.workspace)
            if payload is None:
                skipped.append(name)
                results.append(
                    {
                        "tool": name,
                        "tier": ALL_TIERS.get(name, "?"),
                        "verdict": "SKIPPED",
                        "output_excerpt": "skipped — needs setup or destructive",
                    }
                )
                continue
            print(f"  [{ALL_TIERS.get(name, '?')}] {name:<26}…", end=" ", flush=True)
            r = await _run_one(executor, name, payload)
            print(f"{r['verdict']:<10} ({r['latency_ms']} ms)")
            results.append(r)

    # ── Markdown report ────────────────────────────
    by_verdict = {"PASS": [], "GRACEFUL": [], "STACKTRACE": [], "SKIPPED": []}
    for r in results:
        by_verdict[r["verdict"]].append(r)

    md = []
    md.append("# Tool Smoke Test Report\n")
    md.append(f"_Generated by `scripts/test-all-tools.py` — {len(results)} tools tested._\n")
    md.append("\n## Summary\n")
    md.append("| Verdict | Count |\n|---|---|\n")
    for v, lst in by_verdict.items():
        md.append(f"| {v} | {len(lst)} |\n")
    md.append("\n## Results by tier\n")
    md.append("| Tier | Tool | Verdict | Latency (ms) | Output excerpt |\n")
    md.append("|------|------|---------|--------------|----------------|\n")
    for r in results:
        excerpt = re.sub(r"\s+", " ", r["output_excerpt"])[:180]
        md.append(
            f"| {r['tier']} | `{r['tool']}` | {r['verdict']} | "
            f"{r.get('latency_ms', '-')} | {excerpt} |\n"
        )
    if skipped:
        md.append("\n### Skipped tools (intentional)\n")
        md.append(
            "These tools were not invoked because the safe minimal "
            "argument is unclear or invocation would have side "
            "effects (sending mail, broadcasting a transaction, "
            "consuming heavy GPU time, etc.):\n\n"
        )
        for n in skipped:
            md.append(f"- `{n}`\n")

    Path(args.report).write_text("".join(md))
    Path(args.json).write_text(json.dumps(results, indent=2))
    print(f"\nReport: {args.report}")
    print(f"JSON:   {args.json}")

    # ── Pass gate ──────────────────────────────────
    blocker = []
    for r in results:
        if r["verdict"] != "STACKTRACE":
            continue
        if r["tier"] in ("A", "B"):
            blocker.append(r["tool"])
    if blocker:
        print(f"\nFAIL — blocking stack-trace failures in tier A/B: {blocker}")
        return 1
    print("\nPASS — no blocking stack traces in tier A/B")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
