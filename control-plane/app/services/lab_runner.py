"""Bob Manager — Lab Runner.

Strategy-agnostic execution engine that drives a Lab through its iterations.
Ties together: LoopStrategy, LabDispatcher, repositories, and WebSocket hub.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.orchestrator import Lab, LabAgent
from app.repositories.lab_repo import (
    LabAgentRepository,
    LabMemoryRepository,
    LabMessageRepository,
    LabRepository,
    LabResourceRepository,
    ToolSetRepository,
)
from app.services.lab_dispatcher import LabDispatcher
from app.services.loop_detection import get_loop_manager
from app.services.loop_strategies import get_strategy
from app.services.loop_strategies.base import (
    LoopContext,
    PauseAction,
    PlanAction,
    SynthesizeAction,
    TaskResult,
)
from app.services.loop_strategies.plan_execute import (
    _PendingLLMCall,
    parse_orchestrator_response,
)
from app.services.pipelines import (
    extract_pipeline_names,
    extract_subtool_permissions,
    normalize_tool_names,
)
from app.services.rag_service import augment_tool_names_with_rag_access
from app.services.server_access_service import augment_tool_names_with_server_access
from app.services.tool_executor import (
    ToolExecutor,
    build_native_tools_schema,
    format_tool_descriptions,
    parse_tool_calls,
)
from app.services.web3_access_service import augment_tool_names_with_web3_access
from app.websocket.hub import manager

logger = logging.getLogger(__name__)

LAB_RESOURCES_ROOT = Path(os.environ.get("LAB_RESOURCES_PATH", "/data/lab_resources"))

# Regex to find base64 image data in agent responses
_B64_IMAGE_RE = re.compile(r"data:image/(png|jpe?g|gif|webp);base64,([A-Za-z0-9+/=]{100,})")


def _extract_and_save_images(
    content: str,
    lab_id: UUID,
    iteration: int,
) -> list[dict]:
    """Detect base64 images in agent response text, save to disk, return metadata.

    Returns list of {filename, original_name, content_type, size_bytes, resource_type, data_uri}.
    """
    saved = []
    for i, match in enumerate(_B64_IMAGE_RE.finditer(content)):
        ext = match.group(1).replace("jpeg", "jpg")
        b64data = match.group(2)
        try:
            raw = base64.b64decode(b64data)
        except Exception as exc:
            # O04 — surface decode failures so corrupted agent output is
            # debuggable instead of silently dropped.
            logger.warning(
                "Skipping malformed base64 image #%d in lab %s iter %s: %s (len=%d, head=%r)",
                i,
                lab_id,
                iteration,
                exc,
                len(b64data),
                b64data[:40],
            )
            continue

        lab_dir = LAB_RESOURCES_ROOT / str(lab_id)
        lab_dir.mkdir(parents=True, exist_ok=True)
        fname = f"gen_iter{iteration}_{i}.{ext}"
        (lab_dir / fname).write_bytes(raw)

        saved.append(
            {
                "filename": fname,
                "original_name": fname,
                "content_type": f"image/{ext}",
                "size_bytes": len(raw),
                "resource_type": "image",
                "data_uri": match.group(0),  # full data:image/...;base64,... string
            }
        )
    return saved


def _tool_output_preview(val, limit: int = 2000) -> str:
    """Bound a tool result to a string for the stored/broadcast preview.

    Tool outputs are strings for most tools but a structured dict/list for
    JSON tools (e.g. ``gouv_data_fr`` returns ``{"results": [...]}``). The old
    ``val[:2000]`` slice crashed on those — ``dict[:2000]`` raises
    ``KeyError: slice(None, 2000, None)``, which aborted the whole run. Encode
    non-strings as JSON first, then truncate. Preview only: the full, untrimmed
    output is what gets fed back to the model.
    """
    if not isinstance(val, str):
        try:
            val = json.dumps(val, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001 — a preview must never raise
            val = str(val)
    return val[:limit]


def _materialize_context_files(lab) -> None:
    """Seed each lab.context_files entry to disk at LAB_RESOURCES_ROOT/<lab_id>/<name>.

    Each entry is expected to be ``{"name": str, "content": str}``. Names with
    path-traversal or empty content are skipped. The workspace dir is created
    if missing.

    Seed-if-missing: a context file is written ONLY when it is absent on disk.
    Once materialized, the on-disk copy is the durable working copy — the user
    may edit it (input files like ``icp_brief.md`` are meant to be edited before
    a run) and agents may write alongside it, and those changes survive every
    re-run. ``lab.context_files`` stays the canonical default in the DB (for
    reset / duplicate / blueprint export); it is never overwritten by the disk
    copy, nor does it overwrite an existing disk copy. Deleting a context file
    re-seeds it next run, and a newly added entry is seeded too. Failures are
    logged but don't abort the lab — the agent will get a clean ``file_read``
    error if a critical file is missing.
    """
    cfs = getattr(lab, "context_files", None) or []
    if not cfs:
        return
    lab_dir = LAB_RESOURCES_ROOT / str(lab.id)
    try:
        lab_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("Could not create workspace dir for lab %s", lab.id)
        return
    for cf in cfs:
        if not isinstance(cf, dict):
            continue
        name = (cf.get("name") or "").strip()
        content = cf.get("content")
        if not name or content is None:
            continue
        # Path-traversal guard: filename only, no separators, no leading dot-dot.
        if "/" in name or "\\" in name or name.startswith("..") or name == ".":
            logger.warning("Skipping context_file with unsafe name %r", name)
            continue
        target = lab_dir / name
        if target.exists():
            continue  # already materialized — preserve user/agent edits across runs
        try:
            target.write_text(str(content), encoding="utf-8")
        except OSError:
            logger.exception("Could not write context_file %s to %s", name, target)


# Active lab runners keyed by lab_id — used for pause/inject.
#
# Cluster B — the registry is now backed by two complementary structures:
#  * ``_active_runners`` (dict[UUID, LabRunner]) still holds the runner
#    object so existing get_runner() callers and pause/inject paths see
#    the same data.
#  * ``_runner_reservations`` (set[UUID]) tracks reservations made by
#    the API layer BEFORE the BackgroundTask invokes runner.run(). The
#    previous design inserted the runner inside run(), so two concurrent
#    /run requests could both pass the get_runner() guard at the route
#    layer and both schedule a BackgroundTask — double-spawn race.
# ``reserve_runner`` is the synchronization point: it atomically checks
# both structures under ``_runner_lock`` and inserts the reservation.
_active_runners: dict[UUID, "LabRunner"] = {}
_runner_reservations: set[UUID] = set()
_runner_lock = asyncio.Lock()


def get_runner(lab_id: UUID) -> "LabRunner | None":
    return _active_runners.get(lab_id)


def is_runner_reserved(lab_id: UUID) -> bool:
    """Return True if a runner exists OR a reservation is pending.

    Use this from request handlers that want to refuse a duplicate
    run/resume/inject before scheduling a BackgroundTask.
    """
    return lab_id in _active_runners or lab_id in _runner_reservations


async def reserve_runner(lab_id: UUID, session_factory) -> "LabRunner | None":
    """Atomically reserve a runner slot for ``lab_id``.

    Returns the new LabRunner instance on successful reservation, or None
    if another reservation/runner already exists. The caller schedules
    runner.run() on a BackgroundTask; reservation is released in run()'s
    finally clause.
    """
    async with _runner_lock:
        if lab_id in _active_runners or lab_id in _runner_reservations:
            return None
        runner = LabRunner(lab_id, session_factory)
        _runner_reservations.add(lab_id)
        return runner


class LabRunner:
    """Drives a single Lab execution."""

    def __init__(self, lab_id: UUID, session_factory: async_sessionmaker):
        self.lab_id = lab_id
        self.session_factory = session_factory
        self._paused = asyncio.Event()
        self._paused.set()  # starts unpaused
        self._stop_requested = False
        # R03 — `stop()` sets _stop_requested then blocks on _stopped so
        # the route handler that called `await runner.stop()` doesn't
        # return until the loop has actually exited. Pre-fix the handler
        # returned immediately and a follow-up `delete_lab` raced against
        # a still-iterating loop.
        self._stopped = asyncio.Event()

    # ── Public lifecycle ─────────────────────────

    async def run(self) -> None:
        """Main entry point — run the lab loop until done, paused, or limits hit."""
        # Cluster B — promote the reservation to a live entry. The
        # reservation guarantees no other coroutine can scheduled a
        # parallel BackgroundTask for this lab between
        # reserve_runner() returning and run() starting.
        _active_runners[self.lab_id] = self
        _runner_reservations.discard(self.lab_id)
        try:
            await self._run_loop()
        except Exception as e:
            logger.exception("Lab %s runner crashed", self.lab_id)
            reason = str(e)[:500] or "Unknown error"
            try:
                async with self.session_factory() as db:
                    await LabRepository(db).update(
                        self.lab_id,
                        status="failed",
                        failure_reason=reason,
                    )
                    await db.commit()
                await _broadcast_lab_event(
                    self.lab_id,
                    "lab.error",
                    {"error": reason},
                )
            except Exception:
                logger.error("Failed to mark lab %s as failed after crash", self.lab_id)
        finally:
            _active_runners.pop(self.lab_id, None)
            # Cluster B — also clear the reservation in case the runner
            # never reached `run()`'s success path. Defence-in-depth.
            _runner_reservations.discard(self.lab_id)
            try:
                get_loop_manager().reset_lab(self.lab_id)
            except Exception:
                pass
            # Clear dispatcher affinity for this lab
            from app.services.lab_dispatcher import clear_lab_affinity

            clear_lab_affinity(self.lab_id)
            # Stop (not destroy) the per-lab sandbox container to save resources
            try:
                from app.services.container_manager import stop_sandbox

                await stop_sandbox(self.lab_id)
            except Exception:
                pass
            # R03 — unblock any caller that is awaiting stop().
            self._stopped.set()

    async def pause(self) -> None:
        self._paused.clear()
        async with self.session_factory() as db:
            repo = LabRepository(db)
            await repo.update(self.lab_id, status="paused", paused_at=_now())
            await db.commit()
        await _broadcast_lab_event(self.lab_id, "lab.paused", {})

    async def resume(self) -> None:
        self._paused.set()
        async with self.session_factory() as db:
            repo = LabRepository(db)
            await repo.update(self.lab_id, status="running", paused_at=None)
            await db.commit()
        await _broadcast_lab_event(self.lab_id, "lab.resumed", {})

    async def stop(self, *, wait_timeout: float = 30.0) -> None:
        """Signal the loop to exit, then wait up to ``wait_timeout`` seconds
        for it to actually return.

        R03 — pre-fix this returned immediately after setting the flag
        and the caller (`/labs/{id}/stop`, `delete_lab`) raced against a
        loop still mid-iteration. Now we block on a stop event the
        runner sets in its `finally`. If the loop is genuinely wedged
        (an http call hanging past every internal timeout) the wait
        times out cleanly so the route handler doesn't hang forever.
        """
        self._stop_requested = True
        self._paused.set()  # unblock if paused so loop can exit
        if self._stopped.is_set():
            return  # already exited
        try:
            await asyncio.wait_for(self._stopped.wait(), timeout=wait_timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "LabRunner.stop(lab=%s) timed out after %ss waiting for "
                "loop to exit; returning to caller",
                self.lab_id,
                wait_timeout,
            )

    async def inject(self, message: str) -> None:
        """Inject a user message into the running lab."""
        async with self.session_factory() as db:
            msg_repo = LabMessageRepository(db)
            lab_repo = LabRepository(db)
            lab = await lab_repo.get_by_id(self.lab_id)
            iteration = lab.current_iteration if lab else 0
            await msg_repo.create(
                lab_id=self.lab_id,
                iteration=iteration,
                sender_type="user",
                sender_name="user",
                content=message,
                message_type="inject",
            )
            await db.commit()
        await _broadcast_lab_event(self.lab_id, "lab.inject", {"message": message})
        # Wake runner if paused so it processes the injection
        if not self._paused.is_set():
            self._paused.set()
            async with self.session_factory() as db:
                await LabRepository(db).update(self.lab_id, status="running", paused_at=None)
                await db.commit()
            await _broadcast_lab_event(self.lab_id, "lab.resumed", {})

    # ── Core loop ────────────────────────────────

    async def _run_loop(self) -> None:
        async with self.session_factory() as db:
            lab_repo = LabRepository(db)
            agent_repo = LabAgentRepository(db)
            msg_repo = LabMessageRepository(db)
            mem_repo = LabMemoryRepository(db)
            res_repo = LabResourceRepository(db)

            lab = await lab_repo.get_by_id(self.lab_id)
            if lab is None:
                logger.error("Lab %s not found", self.lab_id)
                return

            agents = await agent_repo.get_by_lab(lab.id, active_only=True)

            # Materialize context_files to the lab workspace on disk so agents
            # can `file_read` them inside the sandbox (mounts the same path).
            # Seed-if-missing: only writes files that are absent, so a re-run
            # preserves the on-disk working copy (user edits to input files like
            # icp_brief.md, and anything agents wrote). The DB keeps the default.
            _materialize_context_files(lab)

            # Initialize strategy
            strategy = get_strategy(lab.loop_type, lab.loop_config)
            await strategy.initialize(lab, agents)

            dispatcher = LabDispatcher(db)
            ts_repo = ToolSetRepository(db)

            # Resolve orchestrator tools (from tool_set or manual list)
            orch_tool_names = await self._resolve_tools(
                ts_repo,
                lab.orchestrator_tools,
                lab.orchestrator_tool_set_id,
                getattr(lab, "orchestrator_tool_set_ids", None),
            )
            orch_tool_names = await augment_tool_names_with_rag_access(db, lab.id, orch_tool_names)
            orch_tool_names = await augment_tool_names_with_web3_access(db, lab.id, orch_tool_names)
            orch_tool_names = await augment_tool_names_with_server_access(
                db, lab.id, orch_tool_names
            )
            # Auto-add handle_memory when auto_sweep_memory is enabled
            if getattr(lab, "auto_sweep_memory", False) and "handle_memory" not in (
                orch_tool_names or []
            ):
                orch_tool_names = list(orch_tool_names or []) + ["handle_memory"]
            orch_native_tools = (
                build_native_tools_schema(orch_tool_names) if orch_tool_names else None
            )

            # Mark running (clear any previous failure reason)
            await lab_repo.update(lab.id, status="running", started_at=_now(), failure_reason=None)
            await db.commit()
            await _broadcast_lab_event(lab.id, "lab.started", {"name": lab.name})

            start_time = time.monotonic()
            has_received_results = False
            seen_injection_ids: set = set()

            # Replay guard — a fresh runner spawned into a lab that already
            # has history (inject into a completed/failed lab) must not
            # re-deliver inject rows answered in a prior run through
            # strategy.on_inject: get_injections has no cursor, so without
            # this every historical injection re-enters the strategy and
            # gets re-dispatched. Anything created at-or-before the last
            # result/synthesis row is done; only newer rows are live work.
            # (Stateful backends like Hermes already hold the conversation
            # in their session and would redo the old task.)
            last_done_at = None
            for m in await msg_repo.get_recent(lab.id, limit=50):
                if m.message_type in ("result", "synthesis"):
                    last_done_at = m.created_at
            if last_done_at is not None:
                for inj in await msg_repo.get_injections(lab.id):
                    if inj.created_at <= last_done_at:
                        seen_injection_ids.add(inj.id)

            while True:
                # ── Guardrails ──
                if self._stop_requested:
                    await lab_repo.update(lab.id, status="completed", completed_at=_now())
                    await db.commit()
                    await _broadcast_lab_event(lab.id, "lab.completed", {"reason": "stopped"})
                    return

                # Wait if paused
                await self._paused.wait()

                # A stop() while paused sets _paused to unblock us here. Re-check
                # the flag immediately (like the PauseAction/CRON gates below) and
                # terminalize NOW — otherwise the loop runs one more full iteration
                # before the top-of-loop check, which can outlast stop()'s timeout
                # and leave the lab stuck on "paused" (no Reset button).
                if self._stop_requested:
                    await lab_repo.update(lab.id, status="completed", completed_at=_now())
                    await db.commit()
                    await _broadcast_lab_event(lab.id, "lab.completed", {"reason": "stopped"})
                    return

                # Refresh lab state
                await db.refresh(lab)

                if lab.max_iterations and lab.current_iteration >= lab.max_iterations:
                    await lab_repo.update(lab.id, status="completed", completed_at=_now())
                    await db.commit()
                    await _broadcast_lab_event(
                        lab.id, "lab.completed", {"reason": "max_iterations"}
                    )
                    return

                elapsed = time.monotonic() - start_time
                if lab.max_duration_sec and elapsed >= lab.max_duration_sec:
                    await lab_repo.update(lab.id, status="completed", completed_at=_now())
                    await db.commit()
                    await _broadcast_lab_event(lab.id, "lab.completed", {"reason": "max_duration"})
                    return

                # ── Build context ──
                messages = await msg_repo.get_recent(lab.id, limit=50)
                lab_memories = await mem_repo.get_by_lab(lab.id, scope="lab")
                injections = await msg_repo.get_injections(lab.id)
                lab_resources = await res_repo.get_by_lab(lab.id)

                # Notify strategy of NEW injections so they get prominent
                # placement at the end of the orchestrator prompt (Path 2).
                for inj in injections:
                    if inj.id not in seen_injection_ids:
                        seen_injection_ids.add(inj.id)
                        await strategy.on_inject(
                            LoopContext(
                                lab=lab,
                                agents=agents,
                                iteration=lab.current_iteration,
                                elapsed_sec=time.monotonic() - start_time,
                                messages=messages,
                                lab_memories=lab_memories,
                                user_injections=[],
                                resources=lab_resources,
                                orch_tool_names=orch_tool_names or [],
                            ),
                            inj.content,
                        )

                context = LoopContext(
                    lab=lab,
                    agents=agents,
                    iteration=lab.current_iteration,
                    elapsed_sec=elapsed,
                    messages=messages,
                    lab_memories=lab_memories,
                    user_injections=[inj.content for inj in injections],
                    resources=lab_resources,
                    orch_tool_names=orch_tool_names or [],
                )

                # ── Ask strategy for next step ──
                try:
                    action = await strategy.next_step(context)
                except Exception as e:
                    logger.exception("Strategy next_step failed for lab %s", lab.id)
                    await self._fail(lab_repo, db, lab.id, str(e))
                    return

                # ── If strategy needs an LLM call (PendingLLMCall) ──
                if isinstance(action, _PendingLLMCall):
                    action_messages = action.messages
                    try:
                        orch_result = await dispatcher.call_orchestrator(
                            lab, action_messages, tools=orch_native_tools
                        )
                    except Exception as e:
                        logger.exception("Orchestrator LLM call failed for lab %s", lab.id)
                        await self._fail(lab_repo, db, lab.id, str(e))
                        return

                    # Store orchestrator message
                    orch_content = orch_result["content"]
                    # When native tool calling is used, content may be empty — store tool call info
                    if not orch_content and orch_result.get("tool_calls"):
                        tc_names = [tc["name"] for tc in orch_result["tool_calls"]]
                        orch_content = json.dumps({"tool_calls": tc_names})
                    orch_msg = await msg_repo.create(
                        lab_id=lab.id,
                        iteration=lab.current_iteration,
                        sender_type="orchestrator",
                        sender_name="orchestrator",
                        content=orch_content,
                        message_type="message",
                        model_used=orch_result.get("model"),
                        provider_used=orch_result.get("provider"),
                        tokens_in=orch_result.get("tokens_in"),
                        tokens_out=orch_result.get("tokens_out"),
                        duration_ms=orch_result.get("duration_ms"),
                    )
                    await db.commit()

                    # Anti-loop observation (fire-and-forget; never blocks the lab).
                    try:
                        get_loop_manager().observe_message(
                            lab_id=lab.id,
                            anti_loop_enabled=bool(getattr(lab, "anti_loop_enabled", False)),
                            message_id=orch_msg.id,
                            actor_key="orchestrator",
                            content=orch_content or "",
                            tool_call=None,
                        )
                    except Exception:
                        logger.exception("Loop observe failed (orchestrator)")

                    await _broadcast_lab_event(
                        lab.id,
                        "lab.orchestrator.message",
                        {
                            "content": (orch_content or "")[:500],
                            "iteration": lab.current_iteration,
                            "sender_type": "orchestrator",
                            "sender_name": "orchestrator",
                            "model_used": orch_result.get("model"),
                            "tokens_in": orch_result.get("tokens_in", 0),
                            "tokens_out": orch_result.get("tokens_out", 0),
                            "duration_ms": orch_result.get("duration_ms", 0),
                            "message_type": "message",
                        },
                    )

                    # ── Orchestrator tool call loop ──
                    if orch_tool_names:
                        orch_tool_executor = ToolExecutor(
                            lab_id=lab.id,
                            db=db,
                            timeout_sec=lab.tool_timeout_sec,
                            max_output_kb=lab.tool_max_output_kb,
                            container_memory_mb=lab.tool_container_memory_mb,
                            allowed_pipelines=extract_pipeline_names(orch_tool_names),
                            subtool_permissions=extract_subtool_permissions(orch_tool_names),
                        )
                        orch_normalized_tools = set(normalize_tool_names(orch_tool_names))
                        orch_tc_total = 0
                        orch_tc_max = lab.tool_max_calls

                        while orch_tc_total < orch_tc_max:
                            native_tc = orch_result.get("tool_calls")
                            if native_tc:
                                orch_tool_calls = [
                                    {"name": tc["name"], "arguments": tc["arguments"]}
                                    for tc in native_tc
                                ]
                                logger.info(
                                    "Orchestrator native tool calls (%d)", len(orch_tool_calls)
                                )
                            else:
                                orch_tool_calls = parse_tool_calls(
                                    orch_result["content"], agent_tools=orch_tool_names
                                )
                            if not orch_tool_calls:
                                break

                            tool_results_parts = []
                            tool_results_data = []
                            for i, tc in enumerate(orch_tool_calls):
                                if orch_tc_total >= orch_tc_max:
                                    break
                                if tc["name"] not in orch_normalized_tools:
                                    tool_output = (
                                        f"Tool '{tc['name']}' is not assigned to orchestrator."
                                    )
                                    success = False
                                    file_event = None
                                else:
                                    tr = await orch_tool_executor.execute(
                                        tc["name"], tc["arguments"]
                                    )
                                    tool_output = tr["output"]
                                    success = tr["success"]
                                    file_event = tr.get("file_event")
                                orch_tc_total += 1

                                await msg_repo.create(
                                    lab_id=lab.id,
                                    iteration=lab.current_iteration,
                                    sender_type="orchestrator",
                                    sender_name="orchestrator",
                                    content=f"Tool call: {tc['name']}",
                                    message_type="tool_call",
                                    tool_name=tc["name"],
                                    tool_input=tc["arguments"],
                                    tool_output={
                                        "success": success,
                                        "output": _tool_output_preview(tool_output),
                                    },
                                )
                                await db.commit()

                                if file_event:
                                    fe_action = file_event["action"]
                                    fe_path = file_event["path"]
                                    fe_size = file_event.get("size_bytes", 0)
                                    await msg_repo.create(
                                        lab_id=lab.id,
                                        iteration=lab.current_iteration,
                                        sender_type="orchestrator",
                                        sender_name="orchestrator",
                                        content=f"📄 File {fe_action}: **{fe_path}** ({fe_size} bytes)",
                                        message_type="file_event",
                                        extra={
                                            "file_action": fe_action,
                                            "file_path": fe_path,
                                            "size_bytes": fe_size,
                                        },
                                    )
                                    await db.commit()

                                tool_results_parts.append(
                                    f'<tool_result name="{tc["name"]}">\n{tool_output}\n</tool_result>'
                                )
                                tc_id = (
                                    native_tc[i].get("id", f"call_{i}")
                                    if native_tc and i < len(native_tc)
                                    else f"call_{i}"
                                )
                                tool_results_data.append(
                                    {"tool_call_id": tc_id, "output": tool_output}
                                )

                            if not tool_results_parts:
                                break

                            # Build follow-up messages
                            if native_tc:
                                action_messages.append(
                                    {
                                        "role": "assistant",
                                        "content": orch_result["content"],
                                        "tool_calls": native_tc,
                                    }
                                )
                                for td in tool_results_data:
                                    action_messages.append(
                                        {
                                            "role": "tool",
                                            "tool_call_id": td["tool_call_id"],
                                            "content": td["output"],
                                        }
                                    )
                            else:
                                action_messages.append(
                                    {"role": "assistant", "content": orch_result["content"]}
                                )
                                action_messages.append(
                                    {"role": "user", "content": "\n".join(tool_results_parts)}
                                )

                            try:
                                orch_result = await dispatcher.call_orchestrator(
                                    lab, action_messages, tools=orch_native_tools
                                )
                            except Exception:
                                logger.exception(
                                    "Orchestrator tool follow-up failed for lab %s", lab.id
                                )
                                break

                            followup_content = orch_result["content"]
                            if not followup_content and orch_result.get("tool_calls"):
                                tc_names = [tc["name"] for tc in orch_result["tool_calls"]]
                                followup_content = json.dumps({"tool_calls": tc_names})
                            await msg_repo.create(
                                lab_id=lab.id,
                                iteration=lab.current_iteration,
                                sender_type="orchestrator",
                                sender_name="orchestrator",
                                content=followup_content,
                                message_type="message",
                                model_used=orch_result.get("model"),
                                provider_used=orch_result.get("provider"),
                                tokens_in=orch_result.get("tokens_in"),
                                tokens_out=orch_result.get("tokens_out"),
                                duration_ms=orch_result.get("duration_ms"),
                            )
                            await db.commit()

                    # Parse the orchestrator's JSON into a real action
                    has_inject = any(
                        "[USER INSTRUCTION]" in (m.get("content") or "")
                        for m in action_messages
                        if m.get("role") == "user"
                    )
                    action = parse_orchestrator_response(
                        orch_result["content"],
                        iteration=lab.current_iteration,
                        has_results=has_received_results,
                        has_pending_inject=has_inject,
                    )

                    # Retry on parse failure (PauseAction from bad JSON)
                    if isinstance(action, PauseAction) and "JSON" in (action.reason or ""):
                        logger.warning("Orchestrator produced bad JSON, retrying (lab %s)", lab.id)
                        retry_msgs = action_messages + [
                            {"role": "assistant", "content": orch_result["content"]},
                            {
                                "role": "user",
                                "content": "Your previous response was not valid JSON. Respond ONLY with valid JSON matching the schema. No extra text, no markdown fences.",
                            },
                        ]
                        try:
                            retry_result = await dispatcher.call_orchestrator(lab, retry_msgs)
                            action = parse_orchestrator_response(
                                retry_result["content"],
                                iteration=lab.current_iteration,
                                has_results=has_received_results,
                                has_pending_inject=has_inject,
                            )
                            # Save retry response so the JSON tasks dispatch is visible in the feed
                            if retry_result.get("content"):
                                await msg_repo.create(
                                    lab_id=lab.id,
                                    iteration=lab.current_iteration,
                                    sender_type="orchestrator",
                                    sender_name="orchestrator",
                                    content=retry_result["content"],
                                    message_type="message",
                                    model_used=retry_result.get("model"),
                                    provider_used=retry_result.get("provider"),
                                    tokens_in=retry_result.get("tokens_in"),
                                    tokens_out=retry_result.get("tokens_out"),
                                    duration_ms=retry_result.get("duration_ms"),
                                )
                                await db.commit()
                        except Exception:
                            logger.warning(
                                "Retry also failed for lab %s, keeping PauseAction", lab.id
                            )

                    # Retry if orchestrator tried to finish without dispatching after inject
                    if (
                        isinstance(action, PauseAction)
                        and "dispatch" in (action.reason or "").lower()
                        and has_inject
                    ):
                        logger.warning(
                            "Orchestrator skipped inject task, retrying with correction (lab %s)",
                            lab.id,
                        )
                        if orch_tool_names:
                            correction = (
                                "You said done without performing the requested work. "
                                "You have tools available — use them directly to fulfil the user instruction. "
                                "Alternatively, dispatch a task to an agent if one is suited for the job."
                            )
                        else:
                            correction = (
                                "You said done without dispatching any tasks. "
                                "You CANNOT perform actions yourself. To write a file, run code, or do anything, "
                                "you MUST create a task for an agent that has the right tool. "
                                "Re-read the user instruction and dispatch the appropriate task(s) now."
                            )
                        retry_msgs = action_messages + [
                            {"role": "assistant", "content": orch_result["content"]},
                            {"role": "user", "content": correction},
                        ]
                        try:
                            retry_result = await dispatcher.call_orchestrator(lab, retry_msgs)
                            action = parse_orchestrator_response(
                                retry_result["content"],
                                iteration=lab.current_iteration,
                                has_results=has_received_results,
                                has_pending_inject=False,  # don't loop forever
                            )
                            if retry_result.get("content"):
                                await msg_repo.create(
                                    lab_id=lab.id,
                                    iteration=lab.current_iteration,
                                    sender_type="orchestrator",
                                    sender_name="orchestrator",
                                    content=retry_result["content"],
                                    message_type="message",
                                    model_used=retry_result.get("model"),
                                    provider_used=retry_result.get("provider"),
                                    tokens_in=retry_result.get("tokens_in"),
                                    tokens_out=retry_result.get("tokens_out"),
                                    duration_ms=retry_result.get("duration_ms"),
                                )
                                await db.commit()
                        except Exception:
                            logger.warning("Inject-retry also failed for lab %s", lab.id)

                # ── Execute action ──
                if isinstance(action, PlanAction):
                    results = await self._execute_tasks(
                        dispatcher, agent_repo, msg_repo, mem_repo, ts_repo, db, lab, agents, action
                    )
                    await strategy.on_results(context, results)
                    has_received_results = True

                    # Store agent results as lab memories
                    agent_map = {a.name: a for a in agents}
                    for r in results:
                        if r.error or not r.response:
                            continue
                        agent_obj = agent_map.get(r.agent_name)
                        # Truncate content to a reasonable size for memory
                        content = r.response[:2000] if len(r.response) > 2000 else r.response
                        await mem_repo.create(
                            lab_id=lab.id,
                            agent_id=agent_obj.id if agent_obj else None,
                            scope="agent",
                            key=f"iter{lab.current_iteration}_{r.agent_name}",
                            content=content,
                            memory_type="result",
                            importance=5,
                        )
                    await db.commit()

                elif isinstance(action, SynthesizeAction):
                    await msg_repo.create(
                        lab_id=lab.id,
                        iteration=lab.current_iteration,
                        sender_type="orchestrator",
                        sender_name="orchestrator",
                        content=action.summary,
                        message_type="synthesis",
                    )
                    # Store final synthesis as a lab memory
                    summary_content = (
                        action.summary[:2000] if len(action.summary) > 2000 else action.summary
                    )
                    await mem_repo.create(
                        lab_id=lab.id,
                        agent_id=None,
                        scope="lab",
                        key=f"synthesis_iter{lab.current_iteration}",
                        content=summary_content,
                        memory_type="synthesis",
                        importance=8,
                    )

                    # If any agent has a cron_expression, keep the runner
                    # alive in a paused state so future CRON injections
                    # can wake it up instead of exiting permanently.
                    has_cron_agents = any(getattr(a, "cron_expression", None) for a in agents)
                    if has_cron_agents:
                        await lab_repo.update(lab.id, status="paused", paused_at=_now())
                        await db.commit()
                        await _broadcast_lab_event(
                            lab.id,
                            "lab.paused",
                            {
                                "reason": "Synthesis complete — waiting for next CRON trigger",
                                "summary": action.summary[:500],
                            },
                        )
                        logger.info(
                            "Lab %s paused after synthesis — waiting for CRON wake-up", lab.id
                        )
                        self._paused.clear()
                        await self._paused.wait()
                        if self._stop_requested:
                            await lab_repo.update(lab.id, status="completed", completed_at=_now())
                            await db.commit()
                            return
                        # Woken by inject — refresh DB connection and continue loop
                        logger.info("Lab %s woken from CRON pause — resuming loop", lab.id)
                        try:
                            await db.execute(text("SELECT 1"))
                        except Exception:
                            logger.warning(
                                "Lab %s: DB connection stale after pause, reconnecting", lab.id
                            )
                            await db.rollback()
                        await lab_repo.update(lab.id, status="running", paused_at=None)
                        await db.commit()
                        await _broadcast_lab_event(lab.id, "lab.resumed", {})
                    else:
                        await lab_repo.update(lab.id, status="completed", completed_at=_now())
                        await db.commit()
                        await _broadcast_lab_event(
                            lab.id,
                            "lab.completed",
                            {
                                "reason": "done",
                                "summary": action.summary[:500],
                            },
                        )
                        return

                elif isinstance(action, PauseAction):
                    await lab_repo.update(lab.id, status="paused", paused_at=_now())
                    await db.commit()
                    await _broadcast_lab_event(lab.id, "lab.paused", {"reason": action.reason})
                    # Wait for resume or inject
                    self._paused.clear()
                    await self._paused.wait()
                    if self._stop_requested:
                        await lab_repo.update(lab.id, status="completed", completed_at=_now())
                        await db.commit()
                        return
                    # Woken up — refresh DB connection and ensure status is running
                    try:
                        await db.execute(text("SELECT 1"))
                    except Exception:
                        logger.warning(
                            "Lab %s: DB connection stale after pause, reconnecting", lab.id
                        )
                        await db.rollback()
                    await lab_repo.update(lab.id, status="running", paused_at=None)
                    await db.commit()

                # ── Increment iteration ──
                new_iter = lab.current_iteration + 1
                await lab_repo.update(lab.id, current_iteration=new_iter)
                await db.commit()

                await _broadcast_lab_event(lab.id, "lab.iteration", {"iteration": new_iter})

    # ── Task execution ───────────────────────────

    async def _execute_tasks(
        self,
        dispatcher: LabDispatcher,
        agent_repo: LabAgentRepository,
        msg_repo: LabMessageRepository,
        mem_repo: LabMemoryRepository,
        ts_repo: ToolSetRepository,
        db: AsyncSession,
        lab: Lab,
        agents: list[LabAgent],
        plan: PlanAction,
    ) -> list[TaskResult]:
        """Execute a batch of agent tasks (concurrently where possible)."""
        agent_map = {a.name: a for a in agents}
        results: list[TaskResult] = []

        # Simple: run all tasks concurrently (depends_on is for future use)
        tasks_to_run = []
        for task_item in plan.tasks:
            agent = agent_map.get(task_item.agent_name)
            if agent is None:
                results.append(
                    TaskResult(
                        agent_name=task_item.agent_name,
                        instruction=task_item.instruction,
                        response="",
                        error=f"Agent '{task_item.agent_name}' not found in this lab.",
                    )
                )
                continue
            tasks_to_run.append((task_item, agent))

        if not tasks_to_run:
            return results

        # Store task assignments as messages
        for task_item, agent in tasks_to_run:
            await msg_repo.create(
                lab_id=lab.id,
                iteration=lab.current_iteration,
                sender_type="orchestrator",
                sender_name="orchestrator",
                target_agent_id=agent.id,
                target_name=agent.name,
                content=task_item.instruction,
                message_type="task",
            )
        await db.commit()

        # Dispatch calls concurrently
        async def _call_agent(task_item, agent: LabAgent) -> TaskResult:
            await _broadcast_lab_event(
                lab.id,
                "lab.task.start",
                {
                    "agent": agent.name,
                    "instruction": task_item.instruction[:200],
                    "iteration": lab.current_iteration,
                    "sender_type": "orchestrator",
                    "sender_name": "orchestrator",
                    "target_name": agent.name,
                    "content": task_item.instruction[:200],
                    "message_type": "task",
                },
            )
            try:
                # Determine whether this agent should see shared memories
                should_share = agent.share_memory
                if lab.share_memory_override is not None:
                    should_share = lab.share_memory_override

                agent_memories = []
                if should_share:
                    # A03 — explicit confirmation that share_memory is set;
                    # the repo refuses the call without it.
                    agent_memories = await mem_repo.get_all_memories(
                        caller_lab_id=lab.id,
                        share_memory_confirmed=True,
                        limit=30,
                    )
                else:
                    # Only this lab's memories
                    agent_memories = await mem_repo.get_by_lab(lab.id, limit=30)
                # Filter hidden memories
                agent_memories = [m for m in agent_memories if not getattr(m, "is_hidden", False)]

                # Load uploaded resources for this lab
                res_repo = LabResourceRepository(db)
                lab_resources = await res_repo.get_by_lab(lab.id)

                # ── Hermes backend: delegate the whole turn to the agent's
                # Hermes container (it runs its own loop + tools). agent_tools
                # MUST stay empty here — it both skips the Bob Lab tool loop
                # below and prevents tool_call blocks inside Hermes' reply
                # text from triggering Bob Lab tools.
                from app.services.hermes import execute_hermes_turn, is_hermes_agent

                if is_hermes_agent(agent):
                    agent_tools = []
                    result = await execute_hermes_turn(db, agent, task_item.instruction)
                elif await dispatcher.is_claude_agent(agent):
                    # ── Full-capacity claude-agent:* backend: Claude Code runs
                    # its OWN tools + loop inside the wrapper and returns the final
                    # text. Like Hermes, agent_tools MUST stay empty — it skips the
                    # Bob Lab tool loop below and prevents any <tool_call> text in
                    # the reply from triggering Bob Lab tools.
                    agent_tools = []
                    msgs = self._build_agent_messages(
                        agent,
                        task_item.instruction,
                        lab,
                        memories=agent_memories,
                        resources=lab_resources,
                        resolved_tools=[],
                    )
                    result = await dispatcher.call_agent(agent, msgs, lab_id=lab.id, tools=None)
                else:
                    # Build native tool schema for hybrid tool calling
                    agent_tools = await self._resolve_tools(
                        ts_repo,
                        agent.tools,
                        agent.tool_set_id,
                        getattr(agent, "tool_set_ids", None),
                    )
                    agent_tools = await augment_tool_names_with_rag_access(db, lab.id, agent_tools)
                    agent_tools = await augment_tool_names_with_web3_access(db, lab.id, agent_tools)
                    agent_tools = await augment_tool_names_with_server_access(
                        db, lab.id, agent_tools
                    )
                    native_tools = build_native_tools_schema(agent_tools) if agent_tools else None

                    msgs = self._build_agent_messages(
                        agent,
                        task_item.instruction,
                        lab,
                        memories=agent_memories,
                        resources=lab_resources,
                        resolved_tools=agent_tools,
                    )
                    result = await dispatcher.call_agent(
                        agent, msgs, lab_id=lab.id, tools=native_tools
                    )

                # ── Tool call loop (hybrid: native + text fallback) ──
                if agent_tools:
                    # Create call_agent callback if this agent has callable_agents configured
                    agent_call_handler = None
                    if "call_agent" in agent_tools and (agent.callable_agents or []):
                        agent_call_handler = self._make_call_agent_handler(
                            caller_agent=agent,
                            dispatcher=dispatcher,
                            msg_repo=msg_repo,
                            mem_repo=mem_repo,
                            ts_repo=ts_repo,
                            db=db,
                            lab=lab,
                            agents=agents,
                        )
                    tool_executor = ToolExecutor(
                        lab_id=lab.id,
                        db=db,
                        timeout_sec=lab.tool_timeout_sec,
                        max_output_kb=lab.tool_max_output_kb,
                        container_memory_mb=lab.tool_container_memory_mb,
                        call_agent_handler=agent_call_handler,
                        allowed_pipelines=extract_pipeline_names(agent_tools),
                        subtool_permissions=extract_subtool_permissions(agent_tools),
                    )
                    agent_normalized_tools = set(normalize_tool_names(agent_tools))
                    total_tool_calls = 0
                    max_calls = lab.tool_max_calls

                    while total_tool_calls < max_calls:
                        # A02 — re-resolve the agent's allowed tool set at the
                        # top of each LLM round. Mid-iteration changes (the
                        # operator removes the `mail` tool from the agent in
                        # the UI while the loop is running, for example)
                        # take effect on the very next tool call instead of
                        # being silently ignored until the next iteration.
                        # The refresh is a single repo lookup + tool-set
                        # join; cheaper than the LLM call we just made.
                        try:
                            await db.refresh(agent)
                            agent_tools = await self._resolve_tools(
                                ts_repo,
                                agent.tools,
                                agent.tool_set_id,
                                getattr(agent, "tool_set_ids", None),
                            )
                            agent_tools = await augment_tool_names_with_rag_access(
                                db, lab.id, agent_tools
                            )
                            agent_tools = await augment_tool_names_with_web3_access(
                                db, lab.id, agent_tools
                            )
                            agent_tools = await augment_tool_names_with_server_access(
                                db, lab.id, agent_tools
                            )
                            agent_normalized_tools = set(normalize_tool_names(agent_tools))
                            tool_executor.allowed_pipelines = extract_pipeline_names(agent_tools)
                            tool_executor.subtool_permissions = extract_subtool_permissions(
                                agent_tools
                            )
                        except Exception:
                            logger.exception(
                                "A02 — tool-set re-resolve failed for agent=%s; "
                                "falling back to the snapshot from iteration start",
                                agent.name,
                            )

                        # Hybrid parsing: try native tool_calls first, then text fallback
                        native_tc = result.get("tool_calls")
                        if native_tc:
                            tool_calls = [
                                {"name": tc["name"], "arguments": tc["arguments"]}
                                for tc in native_tc
                            ]
                            logger.info("Native tool calls detected (%d)", len(tool_calls))
                        else:
                            tool_calls = parse_tool_calls(
                                result["content"], agent_tools=agent_tools
                            )
                        if not tool_calls:
                            break

                        # Save agent's intermediate LLM response (reasoning before/between tool calls)
                        msg_content = result.get("content", "")
                        if not msg_content and result.get("tool_calls"):
                            msg_content = json.dumps(
                                {"tool_calls": [tc["name"] for tc in result["tool_calls"]]}
                            )
                        if msg_content:
                            agent_msg = await msg_repo.create(
                                lab_id=lab.id,
                                iteration=lab.current_iteration,
                                sender_type="agent",
                                sender_agent_id=agent.id,
                                sender_name=agent.name,
                                content=msg_content,
                                message_type="message",
                                model_used=result.get("model"),
                                provider_used=result.get("provider"),
                                tokens_in=result.get("tokens_in"),
                                tokens_out=result.get("tokens_out"),
                                duration_ms=result.get("duration_ms"),
                            )
                            await db.commit()

                            try:
                                get_loop_manager().observe_message(
                                    lab_id=lab.id,
                                    anti_loop_enabled=bool(
                                        getattr(lab, "anti_loop_enabled", False)
                                        or getattr(agent, "anti_loop_enabled", False)
                                    ),
                                    message_id=agent_msg.id,
                                    actor_key=f"agent:{agent.name}",
                                    content=msg_content,
                                    tool_call=None,
                                )
                            except Exception:
                                logger.exception("Loop observe failed (agent.message)")

                            await _broadcast_lab_event(
                                lab.id,
                                "lab.agent.message",
                                {
                                    "content": (msg_content or "")[:500],
                                    "iteration": lab.current_iteration,
                                    "sender_type": "agent",
                                    "sender_name": agent.name,
                                    "model_used": result.get("model"),
                                    "tokens_in": result.get("tokens_in", 0),
                                    "tokens_out": result.get("tokens_out", 0),
                                    "duration_ms": result.get("duration_ms", 0),
                                    "message_type": "message",
                                },
                            )

                        tool_results_parts = []
                        tool_results_data = []
                        for i, tc in enumerate(tool_calls):
                            if total_tool_calls >= max_calls:
                                limit_msg = f"Tool call limit reached ({max_calls}). No more tool calls allowed this turn."
                                tool_results_parts.append(
                                    f'<tool_result name="{tc["name"]}">\n{limit_msg}\n</tool_result>'
                                )
                                tool_results_data.append(
                                    {
                                        "tool_call_id": native_tc[i].get("id", f"call_{i}")
                                        if native_tc and i < len(native_tc)
                                        else f"call_{i}",
                                        "output": limit_msg,
                                    }
                                )
                                break

                            # Validate tool is assigned to this agent
                            if tc["name"] not in agent_normalized_tools:
                                tool_output = f"Tool '{tc['name']}' is not assigned to you."
                                success = False
                                file_event = None
                            else:
                                tr = await tool_executor.execute(tc["name"], tc["arguments"])
                                tool_output = tr["output"]
                                success = tr["success"]
                                file_event = tr.get("file_event")

                            total_tool_calls += 1

                            # Log tool call as a message
                            await msg_repo.create(
                                lab_id=lab.id,
                                iteration=lab.current_iteration,
                                sender_type="agent",
                                sender_agent_id=agent.id,
                                sender_name=agent.name,
                                content=f"Tool call: {tc['name']}",
                                message_type="tool_call",
                                tool_name=tc["name"],
                                tool_input=tc["arguments"],
                                tool_output={
                                    "success": success,
                                    "output": _tool_output_preview(tool_output),
                                },
                            )
                            await db.commit()

                            await _broadcast_lab_event(
                                lab.id,
                                "lab.tool.result",
                                {
                                    "agent": agent.name,
                                    "tool": tc["name"],
                                    "success": success,
                                    "iteration": lab.current_iteration,
                                    "sender_type": "agent",
                                    "sender_name": agent.name,
                                    "content": f"Tool call: {tc['name']}({', '.join(f'{k}={str(v)[:50]}' for k, v in tc['arguments'].items()) if isinstance(tc['arguments'], dict) else '...'})",
                                    "message_type": "tool_call",
                                    "tool_name": tc["name"],
                                },
                            )

                            # Notify file creation/edit events
                            if file_event:
                                fe_action = file_event["action"]
                                fe_path = file_event["path"]
                                fe_size = file_event.get("size_bytes", 0)
                                file_msg = f"📄 File {fe_action}: **{fe_path}** ({fe_size} bytes)"
                                await msg_repo.create(
                                    lab_id=lab.id,
                                    iteration=lab.current_iteration,
                                    sender_type="agent",
                                    sender_agent_id=agent.id,
                                    sender_name=agent.name,
                                    content=file_msg,
                                    message_type="file_event",
                                    extra={
                                        "file_action": fe_action,
                                        "file_path": fe_path,
                                        "size_bytes": fe_size,
                                    },
                                )
                                await db.commit()
                                await _broadcast_lab_event(
                                    lab.id,
                                    "lab.file.event",
                                    {
                                        "agent": agent.name,
                                        "action": fe_action,
                                        "path": fe_path,
                                        "size_bytes": fe_size,
                                        "iteration": lab.current_iteration,
                                    },
                                )

                            tool_results_parts.append(
                                f'<tool_result name="{tc["name"]}" success="{success}">\n'
                                f"{tool_output}\n"
                                f"</tool_result>"
                            )
                            tool_results_data.append(
                                {
                                    "tool_call_id": native_tc[i].get("id", f"call_{i}")
                                    if native_tc and i < len(native_tc)
                                    else f"call_{i}",
                                    "output": tool_output,
                                }
                            )

                        # Re-call agent with tool results
                        if native_tc:
                            # Native format: assistant message with tool_calls + tool result messages
                            msgs.append(
                                {
                                    "role": "assistant",
                                    "content": result.get("content", ""),
                                    "tool_calls": native_tc,
                                }
                            )
                            for trd in tool_results_data:
                                msgs.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": trd["tool_call_id"],
                                        "content": trd["output"],
                                    }
                                )
                            # Send results for any remaining unexecuted tool calls
                            for j in range(len(tool_results_data), len(native_tc)):
                                msgs.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": native_tc[j].get("id", f"call_{j}"),
                                        "content": f"Tool call limit reached ({max_calls}). Call was not executed.",
                                    }
                                )
                        else:
                            # Text-based fallback format
                            tool_results_block = "\n".join(tool_results_parts)
                            msgs.append({"role": "assistant", "content": result["content"]})
                            msgs.append({"role": "user", "content": tool_results_block})
                        result = await dispatcher.call_agent(
                            agent, msgs, lab_id=lab.id, tools=native_tools
                        )

                # Extract & save any generated images
                extra = {}
                # Hermes flow metadata (rounds, tools, reasoning) → UI display
                if result.get("hermes_steps"):
                    extra["hermes_steps"] = result["hermes_steps"]
                generated_images = _extract_and_save_images(
                    result["content"], lab.id, lab.current_iteration
                )
                if generated_images:
                    res_repo_inner = LabResourceRepository(db)
                    img_refs = []
                    for img_meta in generated_images:
                        res_obj = await res_repo_inner.create(
                            lab_id=lab.id,
                            filename=img_meta["filename"],
                            original_name=img_meta["original_name"],
                            content_type=img_meta["content_type"],
                            size_bytes=img_meta["size_bytes"],
                            resource_type="image",
                        )
                        img_refs.append(
                            {
                                "resource_id": str(res_obj.id),
                                "filename": img_meta["filename"],
                                "content_type": img_meta["content_type"],
                            }
                        )
                    extra["images"] = img_refs
                    logger.info(
                        "Saved %d generated images from agent '%s'", len(img_refs), agent.name
                    )

                # Build result content with fallback for empty responses
                result_content = result["content"]
                if not result_content:
                    if result.get("tool_calls"):
                        result_content = json.dumps(
                            {"tool_calls": [tc["name"] for tc in result["tool_calls"]]}
                        )
                    else:
                        result_content = "(no text output)"

                # Store final result
                final_msg = await msg_repo.create(
                    lab_id=lab.id,
                    iteration=lab.current_iteration,
                    sender_type="agent",
                    sender_agent_id=agent.id,
                    sender_name=agent.name,
                    content=result_content,
                    message_type="result",
                    model_used=result.get("model"),
                    provider_used=result.get("provider"),
                    tokens_in=result.get("tokens_in"),
                    tokens_out=result.get("tokens_out"),
                    duration_ms=result.get("duration_ms"),
                    extra=extra,
                )
                await db.commit()

                try:
                    get_loop_manager().observe_message(
                        lab_id=lab.id,
                        anti_loop_enabled=bool(
                            getattr(lab, "anti_loop_enabled", False)
                            or getattr(agent, "anti_loop_enabled", False)
                        ),
                        message_id=final_msg.id,
                        actor_key=f"agent:{agent.name}",
                        content=result_content or "",
                        tool_call=None,
                    )
                except Exception:
                    logger.exception("Loop observe failed (agent.result)")

                await _broadcast_lab_event(
                    lab.id,
                    "lab.task.complete",
                    {
                        "agent": agent.name,
                        "iteration": lab.current_iteration,
                        "sender_type": "agent",
                        "sender_name": agent.name,
                        "content": (result_content or "")[:500],
                        "message_type": "result",
                        "model_used": result.get("model"),
                        "tokens_in": result.get("tokens_in", 0),
                        "tokens_out": result.get("tokens_out", 0),
                        "duration_ms": result.get("duration_ms", 0),
                    },
                )

                return TaskResult(
                    agent_name=agent.name,
                    instruction=task_item.instruction,
                    response=result_content,
                    model_used=result.get("model"),
                    provider_used=result.get("provider"),
                    tokens_in=result.get("tokens_in", 0),
                    tokens_out=result.get("tokens_out", 0),
                    duration_ms=result.get("duration_ms", 0),
                )
            except Exception as e:
                logger.exception("Agent '%s' failed in lab %s", agent.name, lab.id)
                await _broadcast_lab_event(
                    lab.id,
                    "lab.task.error",
                    {
                        "agent": agent.name,
                        "error": str(e),
                    },
                )
                return TaskResult(
                    agent_name=agent.name,
                    instruction=task_item.instruction,
                    response="",
                    error=str(e),
                )

        # ── Dependency-aware execution ──
        # Tasks with empty depends_on run immediately. Tasks with deps
        # wait until the named agents have completed.
        completed_agents: set[str] = set()
        result_map: dict[str, TaskResult] = {}
        pending = list(tasks_to_run)

        while pending:
            # Find tasks whose dependencies are all satisfied
            ready = []
            still_pending = []
            for ti, ag in pending:
                deps = set(ti.depends_on) if ti.depends_on else set()
                if deps <= completed_agents:
                    ready.append((ti, ag))
                else:
                    still_pending.append((ti, ag))

            if not ready:
                # Circular dependency or missing agents — force-run all remaining
                logger.warning(
                    "Dependency deadlock: %d tasks have unsatisfied deps. Running them anyway.",
                    len(still_pending),
                )
                ready = still_pending
                still_pending = []

            # Run ready wave concurrently
            coros = [_call_agent(ti, ag) for ti, ag in ready]
            wave_results = await asyncio.gather(*coros, return_exceptions=False)
            for (_ti, ag), res in zip(ready, wave_results):
                results.append(res)
                completed_agents.add(ag.name)
                result_map[ag.name] = res

            pending = still_pending

        return results

    @staticmethod
    def _build_agent_messages(
        agent: LabAgent,
        instruction: str,
        lab: Lab,
        memories: list | None = None,
        resources: list | None = None,
        resolved_tools: list[str] | None = None,
    ) -> list[dict]:
        """Build the messages array for an agent LLM call."""
        system = agent.system_prompt or f"You are {agent.name}. {agent.role}"

        # Inject context files (inline JSONB — legacy)
        if lab.context_files:
            system += "\n\n<context_files>\n"
            for cf in lab.context_files:
                system += f"--- {cf.get('name', 'unnamed')} ---\n{cf.get('content', '')}\n\n"
            system += "</context_files>"

        # Inject uploaded resource listing (metadata only — agents use file_read for content)
        if resources:
            file_parts = []
            image_resources = []
            for res in resources:
                if res.resource_type == "image":
                    image_resources.append(res)
                else:
                    desc = f" — {res.description}" if res.description else ""
                    file_parts.append(
                        f"- {res.original_name} ({res.resource_type}, {res.size_bytes} bytes){desc}"
                    )

            if file_parts:
                system += "\n\n<uploaded_resources>\n"
                system += "\n".join(file_parts)
                system += '\nUse file_read(path="<filename>") to read resource content when needed.'
                system += "\n</uploaded_resources>"

            if image_resources:
                system += "\n\n<images>\n"
                for img in image_resources:
                    system += (
                        f"- {img.original_name} ({img.content_type}, {img.size_bytes} bytes)\n"
                    )
                system += "Note: Image files are available as resources. Describe what you see if relevant.\n</images>"

        # Inject tool descriptions if agent has tools assigned
        agent_tools = resolved_tools if resolved_tools is not None else (agent.tools or [])
        if agent_tools:
            system += format_tool_descriptions(agent_tools)

        # Inject memories (tiered: Level-0 index with key + preview)
        if memories:
            from app.services.loop_strategies.base import inject_memory_index

            system = inject_memory_index(system, memories)

        # Inject output files listing
        from app.services.loop_strategies.base import inject_output_files

        system = inject_output_files(system, lab.id)

        user_msg: dict[str, Any] = {"role": "user", "content": instruction}

        # Attach actual image bytes for vision-capable models
        if resources:
            image_b64: list[str] = []
            for res in resources:
                if res.resource_type == "image":
                    file_path = LAB_RESOURCES_ROOT / str(lab.id) / res.filename
                    if file_path.is_file():
                        try:
                            raw = file_path.read_bytes()
                            b64 = base64.b64encode(raw).decode()
                            ct = res.content_type or "image/png"
                            image_b64.append(f"data:{ct};base64,{b64}")
                        except Exception:
                            pass
            if image_b64:
                user_msg["images"] = image_b64

        return [
            {"role": "system", "content": system},
            user_msg,
        ]

    async def _fail(
        self, lab_repo: LabRepository, db: AsyncSession, lab_id: UUID, error: str
    ) -> None:
        reason = error[:500] or "Unknown error"
        await lab_repo.update(lab_id, status="failed", failure_reason=reason)
        await db.commit()
        await _broadcast_lab_event(lab_id, "lab.error", {"error": reason})

    @staticmethod
    async def _resolve_tools(
        ts_repo: ToolSetRepository,
        manual_tools: list | None,
        tool_set_id: UUID | None,
        tool_set_ids: list | None = None,
    ) -> list[str]:
        """Resolve effective tool list: union of all tool sets + manual tools."""
        combined: set[str] = set()
        has_sets = False

        # Multi tool-set (new)
        if tool_set_ids:
            for ts_id in tool_set_ids:
                try:
                    ts = await ts_repo.get_by_id(ts_id)
                    if ts and ts.tools:
                        combined.update(ts.tools)
                        has_sets = True
                except Exception:
                    continue

        # Legacy single tool-set
        if not has_sets and tool_set_id:
            ts = await ts_repo.get_by_id(tool_set_id)
            if ts and ts.tools:
                combined.update(ts.tools)
                has_sets = True

        # Manual tools are always included (union)
        if manual_tools:
            combined.update(manual_tools)

        return list(combined) if combined else list(manual_tools or [])

    def _make_call_agent_handler(
        self,
        caller_agent: LabAgent,
        dispatcher: LabDispatcher,
        msg_repo: LabMessageRepository,
        mem_repo: LabMemoryRepository,
        ts_repo: ToolSetRepository,
        db: AsyncSession,
        lab: Lab,
        agents: list[LabAgent],
    ):
        """Create a callback for the call_agent tool that dispatches to another agent."""
        agent_map = {a.name: a for a in agents}

        async def _handler(target_name: str, instruction: str) -> str:
            # Validate permission
            allowed = list(caller_agent.callable_agents or [])
            if target_name not in allowed:
                available = ", ".join(allowed) if allowed else "(none)"
                raise ValueError(
                    f"Agent '{caller_agent.name}' is not allowed to call '{target_name}'. "
                    f"Allowed agents: {available}"
                )

            target = agent_map.get(target_name)
            if target is None:
                raise ValueError(f"Agent '{target_name}' not found in this lab.")

            if not target.is_active:
                raise ValueError(f"Agent '{target_name}' is inactive.")

            # v1: hermes-backed agents own their loop and can't be driven as a
            # nested sub-call — fail loudly rather than silently running the
            # target as a native LLM agent.
            if (getattr(target, "backend", "native") or "native") == "hermes":
                raise ValueError(
                    f"Agent '{target_name}' runs on the Hermes backend and cannot "
                    "be called via call_agent yet. Address it directly via the "
                    "orchestrator/lab tasks instead."
                )

            # Log the cross-agent call as a message
            await msg_repo.create(
                lab_id=lab.id,
                iteration=lab.current_iteration,
                sender_type="agent",
                sender_agent_id=caller_agent.id,
                sender_name=caller_agent.name,
                target_agent_id=target.id,
                target_name=target.name,
                content=instruction,
                message_type="task",
            )
            await db.commit()

            await _broadcast_lab_event(
                lab.id,
                "lab.agent.call",
                {
                    "caller": caller_agent.name,
                    "target": target.name,
                    "instruction": instruction[:200],
                    "iteration": lab.current_iteration,
                },
            )

            # Build messages and call the target agent
            should_share = target.share_memory
            if lab.share_memory_override is not None:
                should_share = lab.share_memory_override
            if should_share:
                # A03 — explicit confirmation; repo refuses without it.
                target_memories = await mem_repo.get_all_memories(
                    caller_lab_id=lab.id,
                    share_memory_confirmed=True,
                    limit=30,
                )
            else:
                target_memories = await mem_repo.get_by_lab(lab.id, limit=30)

            res_repo = LabResourceRepository(db)
            lab_resources = await res_repo.get_by_lab(lab.id)

            target_tools = await self._resolve_tools(
                ts_repo, target.tools, target.tool_set_id, getattr(target, "tool_set_ids", None)
            )
            target_tools = await augment_tool_names_with_rag_access(db, lab.id, target_tools)
            target_tools = await augment_tool_names_with_web3_access(db, lab.id, target_tools)
            target_tools = await augment_tool_names_with_server_access(db, lab.id, target_tools)
            native_tools = build_native_tools_schema(target_tools) if target_tools else None

            msgs = self._build_agent_messages(
                target,
                instruction,
                lab,
                memories=target_memories,
                resources=lab_resources,
                resolved_tools=target_tools,
            )
            result = await dispatcher.call_agent(target, msgs, lab_id=lab.id, tools=native_tools)

            # Target agent tool loop (same logic as _execute_tasks but without call_agent to prevent loops)
            if target_tools:
                sub_executor = ToolExecutor(
                    lab_id=lab.id,
                    db=db,
                    timeout_sec=lab.tool_timeout_sec,
                    max_output_kb=lab.tool_max_output_kb,
                    container_memory_mb=lab.tool_container_memory_mb,
                    allowed_pipelines=extract_pipeline_names(target_tools),
                    subtool_permissions=extract_subtool_permissions(target_tools),
                    # No call_agent_handler for sub-agents to prevent infinite recursion
                )
                target_normalized_tools = set(normalize_tool_names(target_tools))
                total_tc = 0
                max_tc = lab.tool_max_calls

                while total_tc < max_tc:
                    native_tc = result.get("tool_calls")
                    if native_tc:
                        tool_calls = [
                            {"name": tc["name"], "arguments": tc["arguments"]} for tc in native_tc
                        ]
                    else:
                        tool_calls = parse_tool_calls(result["content"], agent_tools=target_tools)
                    if not tool_calls:
                        break

                    tool_results_parts = []
                    tool_results_data = []
                    for i, tc in enumerate(tool_calls):
                        if total_tc >= max_tc:
                            break
                        if tc["name"] not in target_normalized_tools:
                            tool_output = f"Tool '{tc['name']}' is not assigned to you."
                            success = False
                        elif tc["name"] == "call_agent":
                            tool_output = "Nested call_agent is not allowed."
                            success = False
                        else:
                            tr = await sub_executor.execute(tc["name"], tc["arguments"])
                            tool_output = tr["output"]
                            success = tr["success"]

                            # Track file events
                            file_event = tr.get("file_event")
                            if file_event:
                                await msg_repo.create(
                                    lab_id=lab.id,
                                    iteration=lab.current_iteration,
                                    sender_type="agent",
                                    sender_agent_id=target.id,
                                    sender_name=target.name,
                                    content=f"📄 File {file_event['action']}: **{file_event['path']}** ({file_event.get('size_bytes', 0)} bytes)",
                                    message_type="file_event",
                                    extra={
                                        "file_action": file_event["action"],
                                        "file_path": file_event["path"],
                                        "size_bytes": file_event.get("size_bytes", 0),
                                    },
                                )
                                await db.commit()

                        total_tc += 1
                        await msg_repo.create(
                            lab_id=lab.id,
                            iteration=lab.current_iteration,
                            sender_type="agent",
                            sender_agent_id=target.id,
                            sender_name=target.name,
                            content=f"Tool call: {tc['name']}",
                            message_type="tool_call",
                            tool_name=tc["name"],
                            tool_input=tc["arguments"],
                            tool_output={
                                "success": success,
                                "output": _tool_output_preview(tool_output),
                            },
                        )
                        await db.commit()

                        tool_results_parts.append(
                            f'<tool_result name="{tc["name"]}" success="{success}">\n{tool_output}\n</tool_result>'
                        )
                        tc_id = (
                            native_tc[i].get("id", f"call_{i}")
                            if native_tc and i < len(native_tc)
                            else f"call_{i}"
                        )
                        tool_results_data.append({"tool_call_id": tc_id, "output": tool_output})

                    if not tool_results_parts:
                        break

                    if native_tc:
                        msgs.append(
                            {
                                "role": "assistant",
                                "content": result.get("content", ""),
                                "tool_calls": native_tc,
                            }
                        )
                        for trd in tool_results_data:
                            msgs.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": trd["tool_call_id"],
                                    "content": trd["output"],
                                }
                            )
                    else:
                        msgs.append({"role": "assistant", "content": result["content"]})
                        msgs.append({"role": "user", "content": "\n".join(tool_results_parts)})
                    result = await dispatcher.call_agent(
                        target, msgs, lab_id=lab.id, tools=native_tools
                    )

            # Store the result
            inter_content = result["content"]
            if not inter_content:
                if result.get("tool_calls"):
                    inter_content = json.dumps(
                        {"tool_calls": [tc["name"] for tc in result["tool_calls"]]}
                    )
                else:
                    inter_content = "(no text output)"
            await msg_repo.create(
                lab_id=lab.id,
                iteration=lab.current_iteration,
                sender_type="agent",
                sender_agent_id=target.id,
                sender_name=target.name,
                content=inter_content,
                message_type="result",
                model_used=result.get("model"),
                provider_used=result.get("provider"),
                tokens_in=result.get("tokens_in"),
                tokens_out=result.get("tokens_out"),
                duration_ms=result.get("duration_ms"),
            )
            await db.commit()

            return result["content"]

        return _handler


# ── Helpers ──────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _broadcast_lab_event(lab_id: UUID, event_type: str, payload: dict) -> None:
    await manager.broadcast_to_clients(
        {
            "type": event_type,
            "payload": {"lab_id": str(lab_id), **payload},
        }
    )
