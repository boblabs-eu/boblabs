"""Bob Manager — Lab Scheduler.

Background scheduler that handles:
- Lab-level cron: triggers a full lab run on schedule.
- Agent-level cron: sends a task directly to the agent (bypasses orchestrator).

Uses croniter for cron expression parsing.
Runs as a single asyncio background task inside the control-plane process.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.orchestrator import Lab, LabAgent, LibraryAgent
from app.repositories.lab_repo import (
    CronJobRepository,
    LabAgentRepository,
    LabMemoryRepository,
    LabMessageRepository,
    LabRepository,
    LabResourceRepository,
    LabScheduleLogRepository,
    ToolSetRepository,
)
from app.services.lab_runner import (
    LabRunner,
    _broadcast_lab_event,
    _tool_output_preview,
    get_runner,
)
from app.services.pipelines import extract_pipeline_names, extract_subtool_permissions
from app.services.rag_service import augment_tool_names_with_rag_access
from app.services.web3_access_service import augment_tool_names_with_web3_access
from app.websocket.hub import manager

logger = logging.getLogger(__name__)

# Global reference to cancel the task on shutdown
_scheduler_task: asyncio.Task | None = None

POLL_INTERVAL_SEC = 30  # Check every 30 seconds


async def _check_lab_crons(db: AsyncSession, session_factory: async_sessionmaker) -> None:
    """Check all labs with cron_expression and trigger if due."""
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(Lab).where(
            Lab.cron_expression.isnot(None),
            Lab.cron_expression != "",
            Lab.status.notin_(["running"]),
        )
    )
    labs = result.scalars().all()

    for lab in labs:
        try:
            cron = croniter(lab.cron_expression, lab.next_run_at or lab.created_at)
            next_run = cron.get_next(datetime)

            # Ensure timezone-aware
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=timezone.utc)

            if next_run <= now:
                logger.info(
                    "Cron trigger for lab '%s' (expression: %s)", lab.name, lab.cron_expression
                )

                # Update next_run_at
                lab_repo = LabRepository(db)
                next_next = croniter(lab.cron_expression, now).get_next(datetime)
                if next_next.tzinfo is None:
                    next_next = next_next.replace(tzinfo=timezone.utc)
                await lab_repo.update(lab.id, next_run_at=next_next)

                # Log the schedule trigger
                log_repo = LabScheduleLogRepository(db)
                await log_repo.create(
                    lab_id=lab.id,
                    triggered_at=now,
                    status="triggered",
                )
                await db.commit()

                # Start the lab runner
                runner = LabRunner(lab.id, session_factory)
                asyncio.create_task(runner.run())

                await manager.broadcast_to_clients(
                    {
                        "type": "lab.cron.triggered",
                        "payload": {
                            "lab_id": str(lab.id),
                            "lab_name": lab.name,
                            "cron_expression": lab.cron_expression,
                        },
                    }
                )
        except Exception as e:
            logger.error("Cron check failed for lab '%s': %s", lab.name, e)


async def _check_agent_crons(db: AsyncSession, session_factory: async_sessionmaker) -> None:
    """Check all agents with cron_expression and dispatch tasks directly to them."""
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(LabAgent).where(
            LabAgent.cron_expression.isnot(None),
            LabAgent.cron_expression != "",
            LabAgent.is_active.is_(True),
        )
    )
    agents = result.scalars().all()

    for agent in agents:
        try:
            lab_result = await db.execute(select(Lab).where(Lab.id == agent.lab_id))
            lab = lab_result.scalar_one_or_none()
            if not lab or lab.status not in ("running", "paused"):
                continue

            # Find the most recent cron tick before now
            cron = croniter(agent.cron_expression, now)
            prev_trigger = cron.get_prev(datetime)
            if prev_trigger.tzinfo is None:
                prev_trigger = prev_trigger.replace(tzinfo=timezone.utc)

            # Only trigger if this tick is fresh (within the last poll window)
            if now - prev_trigger > timedelta(seconds=POLL_INTERVAL_SEC * 2):
                continue

            # Deduplicate: already triggered for this tick?
            msg_repo = LabMessageRepository(db)
            recent = await msg_repo.get_injections(
                lab.id,
                since=prev_trigger - timedelta(seconds=10),
            )
            already_injected = any(m.content.startswith(f"[CRON:{agent.name}]") for m in recent)
            if already_injected:
                continue

            instruction = (
                agent.cron_instruction or f"Execute your scheduled task (agent: {agent.name})"
            )
            inject_content = f"[CRON:{agent.name}] {instruction}"

            logger.info(
                "Agent cron trigger: '%s' in lab '%s' (expression: %s)",
                agent.name,
                lab.name,
                agent.cron_expression,
            )

            # Record the CRON event in the feed
            await msg_repo.create(
                lab_id=lab.id,
                iteration=lab.current_iteration,
                sender_type="system",
                sender_name="scheduler",
                target_agent_id=agent.id,
                target_name=agent.name,
                content=inject_content,
                message_type="inject",
            )
            await db.commit()

            await manager.broadcast_to_clients(
                {
                    "type": "lab.agent.cron.triggered",
                    "payload": {
                        "lab_id": str(lab.id),
                        "agent_name": agent.name,
                        "instruction": instruction[:200],
                    },
                }
            )

            # Execute the agent task directly (in a background task so
            # the scheduler loop isn't blocked by LLM calls / tool loops).
            asyncio.create_task(_execute_agent_cron(session_factory, lab.id, agent.id, instruction))
        except Exception as e:
            logger.error("Agent cron check failed for '%s': %s", agent.name, e)


async def _execute_agent_cron(
    session_factory: async_sessionmaker,
    lab_id,
    agent_id,
    instruction: str,
) -> None:
    """Execute a single agent CRON task directly — no orchestrator involved.

    Opens its own DB session so it's fully independent of the scheduler.
    """
    from app.services.container_manager import ensure_sandbox
    from app.services.lab_dispatcher import LabDispatcher
    from app.services.lab_runner import LabRunner, _extract_and_save_images
    from app.services.tool_executor import (
        ToolExecutor,
        build_native_tools_schema,
        parse_tool_calls,
    )

    async with session_factory() as db:
        try:
            lab_repo = LabRepository(db)
            agent_repo = LabAgentRepository(db)
            msg_repo = LabMessageRepository(db)
            mem_repo = LabMemoryRepository(db)
            res_repo = LabResourceRepository(db)
            ts_repo = ToolSetRepository(db)

            lab = await lab_repo.get_by_id(lab_id)
            agent = await agent_repo.get_by_id(agent_id)
            if not lab or not agent:
                logger.error(
                    "CRON exec: lab or agent not found (lab=%s, agent=%s)", lab_id, agent_id
                )
                return

            # Record task assignment
            await msg_repo.create(
                lab_id=lab.id,
                iteration=lab.current_iteration,
                sender_type="system",
                sender_name="scheduler",
                target_agent_id=agent.id,
                target_name=agent.name,
                content=instruction,
                message_type="task",
            )
            await db.commit()

            await _broadcast_lab_event(
                lab.id,
                "lab.task.start",
                {
                    "agent": agent.name,
                    "instruction": instruction[:200],
                    "iteration": lab.current_iteration,
                    "source": "cron",
                },
            )

            # ── Resolve tools ──
            # Hermes-backed agents run their own loop + tools in their
            # container; keep agent_tools empty so the Bob Lab tool loop is
            # skipped and Hermes' reply text can never trigger Bob Lab tools.
            from app.services.hermes import is_hermes_agent

            dispatcher = LabDispatcher(db)
            hermes_backed = is_hermes_agent(agent)
            claude_agent_backed = (not hermes_backed) and await dispatcher.is_claude_agent(
                agent, lab=lab
            )
            if hermes_backed or claude_agent_backed:
                # Hermes runs its own loop+tools; claude-agent:* runs Claude Code's
                # own loop+tools in the wrapper. Either way keep agent_tools empty so
                # the Bob Lab tool loop is skipped and the reply text isn't parsed
                # for <tool_call> blocks.
                agent_tools = []
                native_tools = None
            else:
                agent_tools = await LabRunner._resolve_tools(
                    ts_repo,
                    agent.tools,
                    agent.tool_set_id,
                    getattr(agent, "tool_set_ids", None),
                )
                agent_tools = await augment_tool_names_with_rag_access(db, lab.id, agent_tools)
                agent_tools = await augment_tool_names_with_web3_access(db, lab.id, agent_tools)
                native_tools = build_native_tools_schema(agent_tools) if agent_tools else None

            # ── Build messages ──
            agent_memories = await mem_repo.get_by_lab(lab.id, limit=30)
            lab_resources = await res_repo.get_by_lab(lab.id)

            msgs = LabRunner._build_agent_messages(
                agent,
                instruction,
                lab,
                memories=agent_memories,
                resources=lab_resources,
                resolved_tools=agent_tools,
            )

            # ── Ensure sandbox if agent has exec tools ──
            if agent_tools:
                try:
                    await ensure_sandbox(lab.id, memory_mb=lab.tool_container_memory_mb)
                except Exception as e:
                    logger.warning("CRON exec: sandbox setup failed for lab %s: %s", lab.id, e)

            # ── Call agent LLM (or delegate the turn to Hermes / Claude Code) ──
            if hermes_backed:
                from app.services.hermes import execute_hermes_turn

                result = await execute_hermes_turn(
                    db, agent, instruction, resources=lab_resources, lab_id=lab.id
                )
            else:
                # claude-agent:* passes tools=None (native_tools already None) and
                # uses Claude Code's OWN tools inside the wrapper.
                result = await dispatcher.call_agent(
                    agent, msgs, lab_id=lab.id, tools=native_tools, lab=lab
                )

            # ── Tool loop ──
            if agent_tools:
                tool_executor = ToolExecutor(
                    lab_id=lab.id,
                    db=db,
                    timeout_sec=lab.tool_timeout_sec,
                    max_output_kb=lab.tool_max_output_kb,
                    container_memory_mb=lab.tool_container_memory_mb,
                    allowed_pipelines=extract_pipeline_names(agent_tools),
                    subtool_permissions=extract_subtool_permissions(agent_tools),
                )
                total_tool_calls = 0
                max_calls = lab.tool_max_calls

                while total_tool_calls < max_calls:
                    native_tc = result.get("tool_calls")
                    if native_tc:
                        tool_calls = [
                            {"name": tc["name"], "arguments": tc["arguments"]} for tc in native_tc
                        ]
                    else:
                        tool_calls = parse_tool_calls(result["content"], agent_tools=agent_tools)

                    if not tool_calls:
                        break

                    # Save intermediate agent message
                    msg_content = result.get("content", "")
                    if not msg_content and result.get("tool_calls"):
                        msg_content = json.dumps(
                            {"tool_calls": [tc["name"] for tc in result["tool_calls"]]}
                        )
                    if msg_content:
                        await msg_repo.create(
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

                    tool_results_parts = []
                    tool_results_data = []

                    for i, tc in enumerate(tool_calls):
                        if total_tool_calls >= max_calls:
                            tool_results_parts.append(
                                f'<tool_result name="{tc["name"]}">\nTool call limit reached ({max_calls}).\n</tool_result>'
                            )
                            break

                        if tc["name"] not in agent_tools:
                            tool_output = f"Tool '{tc['name']}' is not assigned to you."
                            success = False
                        else:
                            tr = await tool_executor.execute(tc["name"], tc["arguments"])
                            tool_output = tr["output"]
                            success = tr["success"]
                            file_event = tr.get("file_event")
                            if file_event:
                                fe_action = file_event.get("action", "unknown")
                                fe_path = file_event.get("path", "")
                                fe_size = file_event.get("size_bytes", 0)
                                await msg_repo.create(
                                    lab_id=lab.id,
                                    iteration=lab.current_iteration,
                                    sender_type="agent",
                                    sender_agent_id=agent.id,
                                    sender_name=agent.name,
                                    content=f"\U0001f4c4 File {fe_action}: **{fe_path}** ({fe_size} bytes)",
                                    message_type="file_event",
                                    extra={
                                        "file_action": fe_action,
                                        "file_path": fe_path,
                                        "size_bytes": fe_size,
                                    },
                                )
                                await db.commit()

                        total_tool_calls += 1

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
                            },
                        )

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

                    # Build follow-up messages for agent
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
                        agent, msgs, lab_id=lab.id, tools=native_tools, lab=lab
                    )

            # ── Save final result ──
            result_content = result.get("content", "")
            if not result_content:
                if result.get("tool_calls"):
                    result_content = json.dumps(
                        {"tool_calls": [tc["name"] for tc in result["tool_calls"]]}
                    )
                else:
                    result_content = "(no text output)"

            extra = {}
            generated_images = _extract_and_save_images(
                result_content, lab.id, lab.current_iteration
            )
            if generated_images:
                img_refs = []
                for img_meta in generated_images:
                    res_obj = await res_repo.create(
                        lab_id=lab.id,
                        filename=img_meta["filename"],
                        original_name=img_meta["original_name"],
                        content_type=img_meta["content_type"],
                    )
                    img_refs.append(
                        {
                            "resource_id": str(res_obj.id),
                            "filename": img_meta["filename"],
                        }
                    )
                extra["images"] = img_refs

            await msg_repo.create(
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

            await _broadcast_lab_event(
                lab.id,
                "lab.task.complete",
                {
                    "agent": agent.name,
                    "iteration": lab.current_iteration,
                    "source": "cron",
                },
            )

            logger.info(
                "CRON agent '%s' completed task in lab '%s' (tokens: %d→%d)",
                agent.name,
                lab.name,
                result.get("tokens_in", 0),
                result.get("tokens_out", 0),
            )
        except Exception as e:
            logger.exception("CRON exec failed for agent '%s' in lab %s: %s", agent_id, lab_id, e)


async def _check_lab_cron_jobs(db: AsyncSession, session_factory: async_sessionmaker) -> None:
    """Check labs with cron_job_ids (library CRONs) and trigger if due."""
    now = datetime.now(timezone.utc)

    result = await db.execute(select(Lab))
    labs = result.scalars().all()

    cron_repo = CronJobRepository(db)
    msg_repo = LabMessageRepository(db)

    for lab in labs:
        cron_ids = lab.cron_job_ids or []
        if not cron_ids:
            continue
        if lab.status not in ("running", "paused"):
            continue

        for cj_id_str in cron_ids:
            try:
                import uuid as _uuid

                cj_id = _uuid.UUID(str(cj_id_str))
                cj = await cron_repo.get_by_id(cj_id)
                if not cj:
                    continue

                cron = croniter(cj.expression.strip(), now)
                prev_trigger = cron.get_prev(datetime)
                if prev_trigger.tzinfo is None:
                    prev_trigger = prev_trigger.replace(tzinfo=timezone.utc)

                if now - prev_trigger > timedelta(seconds=POLL_INTERVAL_SEC * 2):
                    continue

                # Deduplicate
                recent = await msg_repo.get_injections(
                    lab.id,
                    since=prev_trigger - timedelta(seconds=10),
                )
                already = any(m.content.startswith(f"[CRON-JOB:{cj.name}]") for m in recent)
                if already:
                    continue

                logger.info(
                    "Lab CRON job trigger: '%s' in lab '%s' (method: %s, expression: %s)",
                    cj.name,
                    lab.name,
                    cj.method,
                    cj.expression,
                )

                instruction = cj.instruction or f"Scheduled task: {cj.name}"

                if cj.method == "direct_cmd_exec":
                    # Record in feed and exec directly in container
                    await msg_repo.create(
                        lab_id=lab.id,
                        iteration=lab.current_iteration,
                        sender_type="system",
                        sender_name="cron-scheduler",
                        content=f"[CRON-JOB:{cj.name}] ⚡ Direct exec: {instruction}",
                        message_type="inject",
                    )
                    await db.commit()

                    asyncio.create_task(
                        _execute_lab_cron_cmd(session_factory, lab.id, cj.name, instruction)
                    )
                else:
                    # orchestrator_inject: inject into feed for the orchestrator
                    await msg_repo.create(
                        lab_id=lab.id,
                        iteration=lab.current_iteration,
                        sender_type="system",
                        sender_name="cron-scheduler",
                        content=f"[CRON-JOB:{cj.name}] {instruction}",
                        message_type="inject",
                    )
                    await db.commit()

                    # Wake an existing runner or start a fresh one
                    runner = get_runner(lab.id)
                    if runner is not None:
                        # Runner exists (lab was paused inside its loop)
                        if not runner._paused.is_set():
                            runner._paused.set()
                            lab_repo = LabRepository(db)
                            await lab_repo.update(lab.id, status="running", paused_at=None)
                            await db.commit()
                            await _broadcast_lab_event(lab.id, "lab.resumed", {})
                            logger.info("Woke runner for lab '%s' (orchestrator inject)", lab.name)
                    else:
                        # No runner at all — start a new one so it picks up the inject
                        new_runner = LabRunner(lab.id, session_factory)
                        asyncio.create_task(new_runner.run())
                        logger.info(
                            "Started new runner for lab '%s' (orchestrator inject)", lab.name
                        )

                await manager.broadcast_to_clients(
                    {
                        "type": "lab.cron_job.triggered",
                        "payload": {
                            "lab_id": str(lab.id),
                            "lab_name": lab.name,
                            "cron_name": cj.name,
                            "method": cj.method,
                        },
                    }
                )
            except Exception as e:
                logger.error(
                    "Lab CRON job check failed for '%s' in lab '%s': %s", cj_id_str, lab.name, e
                )


async def _execute_lab_cron_cmd(
    session_factory: async_sessionmaker,
    lab_id,
    cron_name: str,
    command: str,
) -> None:
    """Execute a direct cron command inside the lab's sandbox container.

    Cluster P — previously this used ``docker.from_env()`` + ``cntr.exec_run``
    which the docker-socket-proxy blocks (``EXEC=0`` in docker-compose.yml).
    The result was silent failure: the [CRON-JOB:...] inject row landed in
    the feed but no result ever appeared. The proxy posture was intentional
    — widening it to allow exec would let bob-api shell into any container
    on the host, not just lab sandboxes — so we keep ``EXEC=0`` and route
    the command through the same sandbox HTTP API the agent's ``shell_exec``
    tool already uses. That endpoint runs inside the per-lab container,
    enforces a first-token whitelist, applies output truncation, and
    surfaces a uniform success/output envelope back to the scheduler.

    Operator-facing trade-off: the command's first token must be in
    ``sandbox/main.py:SHELL_WHITELIST`` (curl, wget, python3, cat, grep,
    awk, sed, ffmpeg, yt-dlp, …). Arbitrary scripts must be wrapped via
    ``python3 -c "import subprocess; subprocess.run(['/path/to/script.sh'])"``
    or routed through ``method='orchestrator_inject'`` with an agent that
    has the shell_exec tool granted.
    """
    import httpx

    from app.services.container_manager import ensure_sandbox

    async with session_factory() as db:
        lab_repo = LabRepository(db)
        msg_repo = LabMessageRepository(db)

        lab = await lab_repo.get_by_id(lab_id)
        if not lab:
            return

        # Use the lab's existing tool-call budget for the cron command so
        # operators have a single knob (lab.tool_timeout_sec) that bounds
        # every sandbox-shelled invocation.
        timeout_sec = int(lab.tool_timeout_sec or 30)
        max_output_kb = int(lab.tool_max_output_kb or 256)

        async def _record(content: str, message_type: str = "result") -> None:
            await msg_repo.create(
                lab_id=lab.id,
                iteration=lab.current_iteration,
                sender_type="system",
                sender_name="cron-scheduler",
                content=content,
                message_type=message_type,
            )
            await db.commit()

        # Bring up the sandbox container (retry to absorb concurrency with
        # the runner). R6 — use the base URL returned by ensure_sandbox so
        # the URL convention lives in container_manager and any future
        # rename only has to happen once.
        base_url: str | None = None
        for attempt in range(3):
            try:
                base_url = await ensure_sandbox(lab.id, memory_mb=lab.tool_container_memory_mb)
                break
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(2)
                else:
                    logger.exception(
                        "Lab CRON cmd '%s' in lab %s: ensure_sandbox failed",
                        cron_name,
                        lab_id,
                    )
                    await _record(
                        f"[CRON-JOB:{cron_name}] direct_cmd_exec failed: "
                        f"sandbox container could not be started."
                    )
                    return
        assert base_url is not None  # loop above either returned or set this
        payload = {
            "lab_id": str(lab.id),
            "command": command,
            "timeout_sec": timeout_sec,
            "max_output_kb": max_output_kb,
        }

        # HTTP timeout = sandbox-side timeout + 5s grace, mirroring the
        # convention used by tool_exec.shell_exec (cluster E reference).
        http_timeout = timeout_sec + 5

        try:
            async with httpx.AsyncClient(timeout=http_timeout) as client:
                resp = await client.post(f"{base_url}/shell_exec", json=payload)
                resp.raise_for_status()
                result = resp.json()
        except httpx.HTTPError as exc:
            logger.warning(
                "Lab CRON cmd '%s' in lab %s: sandbox HTTP error: %s",
                cron_name,
                lab_id,
                exc,
            )
            await _record(
                f"[CRON-JOB:{cron_name}] direct_cmd_exec failed: sandbox "
                f"unreachable ({exc.__class__.__name__})."
            )
            return
        except Exception:
            logger.exception(
                "Lab CRON cmd '%s' in lab %s: unexpected error contacting sandbox",
                cron_name,
                lab_id,
            )
            await _record(
                f"[CRON-JOB:{cron_name}] direct_cmd_exec failed: unexpected "
                f"error contacting sandbox."
            )
            return

        success = bool(result.get("success"))
        output = str(result.get("output") or "")
        if len(output) > max_output_kb * 1024:
            output = output[: max_output_kb * 1024] + "\n... [truncated]"
        status_tag = "success" if success else "failed"
        await _record(f"[CRON-JOB:{cron_name}] result ({status_tag}):\n```\n{output}\n```")

        await _broadcast_lab_event(
            lab.id,
            "lab.cron_job.result",
            {
                "cron_name": cron_name,
                "success": success,
            },
        )

        logger.info(
            "Lab CRON cmd '%s' in lab '%s' completed (%s)",
            cron_name,
            lab.name,
            status_tag,
        )


async def _recover_stuck_labs(db: AsyncSession, session_factory: async_sessionmaker) -> None:
    """After a restart, labs stuck in 'running' have no runner. Reset to paused."""
    now = datetime.now(timezone.utc)
    result = await db.execute(select(Lab).where(Lab.status == "running"))
    labs = result.scalars().all()
    for lab in labs:
        runner = get_runner(lab.id)
        if runner is None:
            lab_repo = LabRepository(db)
            # Check if any agent has cron → set to paused so CRON can wake it
            agent_result = await db.execute(
                select(LabAgent).where(
                    LabAgent.lab_id == lab.id,
                    LabAgent.cron_expression.isnot(None),
                    LabAgent.cron_expression != "",
                )
            )
            has_cron = agent_result.scalars().first() is not None
            if has_cron:
                # O06 — set paused_at so the UI shows when the lab was last
                # touched (the previous "stuck running" timestamp is gone).
                await lab_repo.update(lab.id, status="paused", paused_at=now)
                logger.info("Recovered stuck lab '%s' → paused (has CRON agents)", lab.name)
            else:
                await lab_repo.update(lab.id, status="failed")
                logger.info("Recovered stuck lab '%s' → failed (no runner after restart)", lab.name)
            await db.commit()


async def _check_library_agent_crons(db: AsyncSession, session_factory: async_sessionmaker) -> None:
    """Fire cron-scheduled consumer-app library agents.

    Each tick spawns an ephemeral single-agent lab via
    :func:`app.services.library_agent_service.create_agent_instance`,
    tagged ``app:<app_id>:agent_run:<short>:cron:<tick_iso>`` so the
    consumer app can poll ``/list_agent_runs`` for results. ``cron_instruction``
    is injected as a user message before the runner starts.

    Operator-managed library agents (without the ``app__<app_id>__`` prefix)
    are ignored here — they have no orchestration target (no parent lab) and
    are picked up by the operator UI directly when the user instantiates them.
    """
    from app.services.library_agent_service import (
        create_agent_instance,
        short_name_for_app,
    )

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(LibraryAgent).where(
            LibraryAgent.cron_expression.isnot(None),
            LibraryAgent.cron_expression != "",
            LibraryAgent.name.like("app__%__%"),
        )
    )
    agents = result.scalars().all()

    for agent in agents:
        # Parse app_id + short name from the namespaced library_agents.name.
        prefix_split = agent.name.split("__", 2)
        if len(prefix_split) != 3 or prefix_split[0] != "app":
            continue
        app_id = prefix_split[1]
        short_name = short_name_for_app(agent.name, app_id)
        if not short_name:
            continue

        try:
            cron = croniter(agent.cron_expression, now)
            prev_trigger = cron.get_prev(datetime)
            if prev_trigger.tzinfo is None:
                prev_trigger = prev_trigger.replace(tzinfo=timezone.utc)

            # Only fire if the tick is fresh — guards against backfills on restart.
            if now - prev_trigger > timedelta(seconds=POLL_INTERVAL_SEC * 2):
                continue

            tick_iso = prev_trigger.replace(microsecond=0).isoformat()
            run_tag = f"app:{app_id}:agent_run:{short_name}:cron:{tick_iso}"

            # Deduplicate: skip if we already spawned a lab for this tick.
            from sqlalchemy import text as sql_text

            existing = (
                (
                    await db.execute(
                        select(Lab).where(sql_text("acl->>'tag' = :t")).params(t=run_tag)
                    )
                )
                .scalars()
                .first()
            )
            if existing:
                continue

            instance_name = f"app:{app_id}:agent:{short_name}:cron:{tick_iso}"
            acl = {
                "owner": f"app:{app_id}",
                "editors": [],
                "viewers": [],
                "tag": run_tag,
                "library_agent_id": str(agent.id),
                "app_id": app_id,
                "short_name": short_name,
                "triggered_by": "cron",
                "cron_tick": tick_iso,
            }

            # Resolve rag_access stashed in callable_agents.
            from app.schemas.orchestrator import RagAccessRef

            rag_access: list[RagAccessRef] = []
            for entry in agent.callable_agents or []:
                if isinstance(entry, dict) and "__app_meta__" in entry:
                    raw = entry["__app_meta__"].get("rag_access") or []
                    rag_access = [RagAccessRef(**r) for r in raw]
                    break

            lab = await create_agent_instance(
                db,
                library_agent_id=agent.id,
                instance_name=instance_name,
                acl=acl,
                rag_access=rag_access,
            )

            # Strip the sentinel from the cloned LabAgent.callable_agents.
            la_rows = (
                (await db.execute(select(LabAgent).where(LabAgent.lab_id == lab.id)))
                .scalars()
                .all()
            )
            if la_rows:
                cleaned = [
                    e
                    for e in (la_rows[0].callable_agents or [])
                    if not (isinstance(e, dict) and "__app_meta__" in e)
                ]
                await LabAgentRepository(db).update(la_rows[0].id, callable_agents=cleaned)

            # Inject cron_instruction so the runner picks it up.
            instruction = (
                agent.cron_instruction or f"Execute your scheduled task (agent: {short_name})"
            )
            await LabMessageRepository(db).create(
                lab_id=lab.id,
                iteration=0,
                sender_type="user",
                content=f"[CRON:{tick_iso}] {instruction}",
                message_type="user_inject",
            )
            await db.commit()

            logger.info(
                "[lib-agent-cron] app=%s agent=%s lab=%s tick=%s",
                app_id,
                short_name,
                lab.id,
                tick_iso,
            )

            # Spawn the runner in background — the lab is left in DB for
            # /list_agent_runs polling (no callback delivery on cron).
            runner = LabRunner(lab.id, session_factory)
            asyncio.create_task(runner.run())
        except Exception as e:
            logger.error(
                "[lib-agent-cron] failed for agent '%s': %s",
                agent.name,
                e,
                exc_info=True,
            )


# ── Native Hermes cron (Bob as the external scheduler heartbeat) ─────
# Per-agent cursor (epoch secs) of the last surfaced cron output; on a fresh
# start we skip history (cursor := the adapter's "now") to avoid replaying old
# job output into the feed after a bob-api restart.
_hermes_cron_cursors: dict[str, float] = {}
# Keys with an in-flight container (re)start, so repeated polls don't pile up.
_hermes_ensuring: set[str] = set()


async def _safe_ensure_hermes(agent_key, name: str) -> None:
    """(Re)start a down Hermes container in the background — container recreate
    can take ~90s, so never await it inside the scheduler loop."""
    k = str(agent_key)
    if k in _hermes_ensuring:
        return
    _hermes_ensuring.add(k)
    try:
        from app.services.hermes import ensure_hermes

        await ensure_hermes(agent_key)
        logger.info("hermes cron: (re)started container for '%s'", name)
    except Exception as e:  # noqa: BLE001
        logger.warning("hermes cron: ensure container for '%s' failed: %s", name, e)
    finally:
        _hermes_ensuring.discard(k)


async def _surface_hermes_cron_output(db: AsyncSession, agent, output: dict) -> None:
    """Post one native Hermes cron job result into its lab's message feed."""
    content = (output.get("content") or "").strip()
    lab_id = getattr(agent, "lab_id", None)
    if not content or lab_id is None:
        return
    try:
        lab = (await db.execute(select(Lab).where(Lab.id == lab_id))).scalar_one_or_none()
        if not lab:
            return
        await LabMessageRepository(db).create(
            lab_id=lab.id,
            iteration=lab.current_iteration,
            sender_type="agent",
            sender_agent_id=agent.id,
            sender_name=agent.name,
            content=content,
            message_type="result",
            provider_used="hermes",
            extra={
                "source": "hermes_cron",
                "job_id": output.get("job_id"),
                "file": output.get("file"),
            },
        )
        await db.commit()
        await _broadcast_lab_event(
            lab.id,
            "lab.hermes_cron.result",
            {"agent_id": str(agent.id), "agent_name": agent.name, "job_id": output.get("job_id")},
        )
    except Exception as e:  # noqa: BLE001
        logger.error("hermes cron: surfacing output for '%s' failed: %s", agent.name, e)
        await db.rollback()


async def _check_hermes_cron(db: AsyncSession) -> None:
    """For every always-on Hermes agent: keep its container up, tick its native
    scheduler, and surface new job output into the lab feed. Bob is the external
    ~60s heartbeat the native scheduler expects — tick() only runs DUE jobs, so a
    finer poll is cheap. Non-blocking: a down container is (re)started in the
    background and ticked on the next pass."""
    from app.services.hermes import (
        cron_output,
        cron_tick,
        get_hermes_status,
        hermes_container_key,
    )

    try:
        agents = (
            await db.execute(
                select(LabAgent).where(
                    LabAgent.backend == "hermes",
                    LabAgent.hermes_activated.is_(True),
                )
            )
        ).scalars().all()
    except Exception as e:  # noqa: BLE001
        logger.error("hermes cron: query failed: %s", e)
        return

    for agent in agents:
        key = hermes_container_key(agent)
        try:
            status = await get_hermes_status(key)
        except Exception as e:  # noqa: BLE001
            logger.warning("hermes cron: status for '%s' failed: %s", agent.name, e)
            continue
        if not status.get("image_configured"):
            return  # feature dormant — nothing to tick for any agent
        if not (status.get("running") and status.get("healthy") and status.get("url")):
            asyncio.create_task(_safe_ensure_hermes(key, agent.name))
            continue

        url = status["url"]
        await cron_tick(url)

        agent_key = str(agent.id)
        cursor = _hermes_cron_cursors.get(agent_key)
        data = await cron_output(url, since=cursor or 0.0)
        now = float(data.get("now") or 0.0)
        if cursor is None:
            _hermes_cron_cursors[agent_key] = now  # first sight: don't replay history
            continue
        for o in data.get("outputs") or []:
            await _surface_hermes_cron_output(db, agent, o)
        _hermes_cron_cursors[agent_key] = now or cursor


async def _scheduler_loop(session_factory: async_sessionmaker) -> None:
    """Main scheduler loop — runs indefinitely."""
    await asyncio.sleep(10)  # Wait for app startup
    logger.info("Lab scheduler started (poll interval: %ds)", POLL_INTERVAL_SEC)

    # One-time: recover labs stuck in 'running' from a previous crash/restart
    try:
        async with session_factory() as db:
            await _recover_stuck_labs(db, session_factory)
    except Exception as e:
        logger.error("Lab recovery failed: %s", e)

    while True:
        try:
            async with session_factory() as db:
                await _check_lab_crons(db, session_factory)
                await _check_agent_crons(db, session_factory)
                await _check_lab_cron_jobs(db, session_factory)
                await _check_library_agent_crons(db, session_factory)
                await _check_hermes_cron(db)
        except Exception as e:
            logger.error("Scheduler loop error: %s", e)

        await asyncio.sleep(POLL_INTERVAL_SEC)


def start_scheduler(session_factory: async_sessionmaker) -> asyncio.Task:
    """Start the background scheduler task. Call from app startup."""
    global _scheduler_task
    _scheduler_task = asyncio.create_task(_scheduler_loop(session_factory))
    return _scheduler_task


def stop_scheduler() -> None:
    """Cancel the scheduler task. Call from app shutdown."""
    global _scheduler_task
    if _scheduler_task:
        _scheduler_task.cancel()
        _scheduler_task = None
