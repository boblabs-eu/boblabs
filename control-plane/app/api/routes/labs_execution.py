"""Lab Execution — lifecycle routes (run / pause / resume / stop / reset / inject).

Auth: every route requires a valid JWT and EDIT permission on the lab's
ACL. Admins bypass via ``check_permission``. Mirrors the pattern in
``labs.py``.
"""

import logging
import shutil
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.api.dependencies import DbSession, get_current_user
from app.api.routes.labs import LAB_RESOURCES_ROOT
from app.database import async_session
from app.repositories.lab_repo import (
    LabMemoryRepository,
    LabMessageRepository,
    LabRepository,
)
from app.schemas.orchestrator import LabInject
from app.services.authorization import Permission, check_permission
from app.services.lab_runner import get_runner, is_runner_reserved, reserve_runner

logger = logging.getLogger(__name__)
router = APIRouter(tags=["labs"])


@router.post("/{lab_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_lab(
    lab_id: UUID,
    background_tasks: BackgroundTasks,
    db: DbSession,
    reset: bool = False,
    user: dict = Depends(get_current_user),
):
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.EDIT)
    if lab.status == "running":
        raise HTTPException(409, "Lab is already running")
    # Cluster B — reject duplicates against both the live registry AND
    # any pending reservation (a concurrent /run that's already inside
    # the BackgroundTasks queue).
    if is_runner_reserved(lab_id):
        raise HTTPException(409, "Lab runner already active")

    if not lab.orchestrator_model_id:
        # Fall back to the system-wide default model from OrchestratorSettings,
        # or to the first registered model if the configured default is
        # missing or stale (e.g. 0.12.0-0.12.2 init.sql hardcoded 'qwen2.5:72b').
        from app.repositories.orchestrator_repo import (
            AIModelRepository,
            OrchestratorSettingsRepository,
        )

        settings_repo = OrchestratorSettingsRepository(db)
        settings = await settings_repo.get()
        configured_ident = (settings.orchestrator_model if settings else "") or ""
        model_repo = AIModelRepository(db)
        all_models = await model_repo.get_all()
        resolved_id = None
        if configured_ident:
            for m in all_models:
                if m.model_identifier == configured_ident:
                    resolved_id = m.id
                    break
        if not resolved_id and all_models:
            resolved_id = all_models[0].id
            logger.warning(
                "Orchestrator default '%s' does not match any registered model; "
                "falling back to '%s' for lab %s",
                configured_ident or "(unset)",
                all_models[0].model_identifier,
                lab_id,
            )
        if not resolved_id:
            raise HTTPException(
                422,
                "No models are registered with the orchestrator. Connect an "
                "agent so its Ollama (or other provider) models can sync, "
                "then try again.",
            )
        lab.orchestrator_model_id = resolved_id
        await repo.update(lab_id, orchestrator_model_id=resolved_id)
        await db.commit()

    # Reset completed/failed lab for a fresh run
    if reset:
        msg_repo = LabMessageRepository(db)
        mem_repo = LabMemoryRepository(db)
        await msg_repo.delete_by_lab(lab_id)
        await mem_repo.delete_by_lab(lab_id)
        # Clear output files from previous runs
        output_dir = LAB_RESOURCES_ROOT / str(lab_id) / "output"
        if output_dir.is_dir():
            shutil.rmtree(output_dir, ignore_errors=True)
            output_dir.mkdir(exist_ok=True)
        # Recreate sandbox container
        from app.services.container_manager import destroy_sandbox

        await destroy_sandbox(lab_id)
        await repo.update(
            lab_id,
            status="created",
            current_iteration=0,
            started_at=None,
            paused_at=None,
            completed_at=None,
        )
        await db.commit()
    elif lab.status in ("completed", "failed"):
        # Continue from where it stopped — just reset status
        await repo.update(lab_id, status="created", completed_at=None)
        await db.commit()

    # Pre-warm sandbox container before starting runner
    from app.services.container_manager import ensure_sandbox

    await ensure_sandbox(lab_id, memory_mb=lab.tool_container_memory_mb)

    # Cluster B — atomic reserve. If another request slipped in after the
    # earlier is_runner_reserved check, reserve_runner returns None and
    # we surface a 409.
    runner = await reserve_runner(lab_id, async_session)
    if runner is None:
        raise HTTPException(409, "Lab runner already active")
    background_tasks.add_task(runner.run)
    return {"status": "started", "lab_id": str(lab_id), "reset": reset}


@router.post("/{lab_id}/reset")
async def reset_lab(lab_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    """Reset a lab to fresh state: clear messages, memories, outputs. Does NOT start running."""
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.EDIT)
    if lab.status == "running":
        raise HTTPException(409, "Cannot reset a running lab — stop it first")
    if is_runner_reserved(lab_id):
        raise HTTPException(409, "Lab runner still active")

    msg_repo = LabMessageRepository(db)
    mem_repo = LabMemoryRepository(db)
    await msg_repo.delete_by_lab(lab_id)
    await mem_repo.delete_by_lab(lab_id)
    output_dir = LAB_RESOURCES_ROOT / str(lab_id) / "output"
    if output_dir.is_dir():
        shutil.rmtree(output_dir, ignore_errors=True)
        output_dir.mkdir(exist_ok=True)
    await repo.update(
        lab_id,
        status="created",
        current_iteration=0,
        started_at=None,
        paused_at=None,
        completed_at=None,
    )
    await db.commit()
    # Recreate sandbox container for clean state
    from app.services.container_manager import destroy_sandbox

    await destroy_sandbox(lab_id)
    return {"status": "created", "lab_id": str(lab_id)}


@router.post("/{lab_id}/pause")
async def pause_lab(lab_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.EDIT)
    runner = get_runner(lab_id)
    if runner:
        await runner.pause()
        return {"status": "paused"}
    # Cluster B — the cold path used to overwrite status to "paused" even
    # for terminal states (completed/failed/stopped). A subsequent /resume
    # then saw "paused" and span up a new runner. Refuse the transition
    # so terminal states stay terminal.
    if lab.status in ("completed", "failed", "stopped"):
        raise HTTPException(409, f"Cannot pause lab with status '{lab.status}'")
    if lab.status == "paused":
        # Idempotent — nothing to do.
        return {"status": "paused"}
    # O06 — every status="paused" transition must also set paused_at so the
    # UI duration column and the CRON wake-up dedup never see stale values.
    from datetime import datetime, timezone

    await repo.update(lab_id, status="paused", paused_at=datetime.now(timezone.utc))
    await db.commit()
    return {"status": "paused"}


@router.post("/{lab_id}/resume")
async def resume_lab(
    lab_id: UUID,
    background_tasks: BackgroundTasks,
    db: DbSession,
    user: dict = Depends(get_current_user),
):
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.EDIT)
    runner = get_runner(lab_id)
    if runner:
        await runner.resume()
        return {"status": "resumed"}
    # Cluster B — guard against duplicates from concurrent /resume calls
    # arriving while we're still in the BackgroundTasks queue.
    if is_runner_reserved(lab_id):
        raise HTTPException(409, "Lab runner already active")
    # No runner in memory (e.g. after server restart) — start a fresh runner
    if lab.status not in ("paused", "created"):
        raise HTTPException(409, f"Cannot resume lab with status '{lab.status}'")
    await repo.update(lab_id, status="created", paused_at=None)
    await db.commit()
    new_runner = await reserve_runner(lab_id, async_session)
    if new_runner is None:
        raise HTTPException(409, "Lab runner already active")
    background_tasks.add_task(new_runner.run)
    return {"status": "resumed"}


@router.post("/{lab_id}/stop")
async def stop_lab(lab_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.EDIT)
    runner = get_runner(lab_id)
    if runner:
        await runner.stop()
        return {"status": "stopped"}
    # No runner in memory — just update DB status
    from datetime import datetime, timezone

    await repo.update(lab_id, status="completed", completed_at=datetime.now(timezone.utc))
    await db.commit()
    return {"status": "stopped"}


@router.post("/{lab_id}/inject")
async def inject_message(
    lab_id: UUID,
    data: LabInject,
    background_tasks: BackgroundTasks,
    db: DbSession,
    user: dict = Depends(get_current_user),
):
    """Inject a user message into a lab.

    If a runner is active (running or paused), forward the message to its
    in-memory queue (wakes the paused event). Otherwise persist the inject
    row AND auto-spawn a fresh runner so the user doesn't need a manual Run
    click after every inject. Completed/failed labs are normalized back to
    ``created`` so the runner picks up cleanly.
    """
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.EDIT)

    runner = get_runner(lab_id)
    if runner:
        await runner.inject(data.content)
        return {"status": "injected", "started_runner": False}

    # Cluster B — refuse if a reservation is in flight; the in-flight
    # runner will pick up the inject row on first iteration after it
    # transitions from reservation -> _active_runners.
    if is_runner_reserved(lab_id):
        raise HTTPException(409, "Lab runner spawning; retry shortly")

    # No active runner — persist + auto-spawn.
    msg_repo = LabMessageRepository(db)
    await msg_repo.create(
        lab_id=lab_id,
        iteration=lab.current_iteration,
        sender_type="user",
        sender_name="user",
        content=data.content,
        message_type="inject",
    )

    # Resolve a model if neither the lab nor its single agent has one. Affects
    # solo instances built from templates where ``model_id`` was left null
    # (e.g. seeded openclaw/hermes presets) — without this, the runner spawns
    # but the dispatcher fails with "no model_id configured" on first call.
    from app.repositories.lab_repo import LabAgentRepository
    from app.repositories.orchestrator_repo import (
        AIModelRepository,
        OrchestratorSettingsRepository,
    )

    lab_agents = await LabAgentRepository(db).get_by_lab(lab.id, active_only=True)
    agents_missing_model = [a for a in lab_agents if not a.model_id]
    needs_orch_model = not lab.orchestrator_model_id
    if needs_orch_model or agents_missing_model:
        settings_row = await OrchestratorSettingsRepository(db).get()
        default_ident = (settings_row.orchestrator_model if settings_row else "") or ""
        all_models = await AIModelRepository(db).get_all()
        default_model = None
        if default_ident:
            for m in all_models:
                if m.model_identifier == default_ident:
                    default_model = m
                    break
        # Fallback: if the configured default doesn't match a registered
        # model (stale setting from 0.12.0–0.12.2's hardcoded init.sql
        # default, or operator deleted that model), pick the first model
        # available. Better than refusing to run.
        if default_model is None and all_models:
            default_model = all_models[0]
            logger.warning(
                "Orchestrator default '%s' does not match any registered model; "
                "falling back to '%s' for lab %s",
                default_ident or "(unset)",
                default_model.model_identifier,
                lab_id,
            )
        if default_model is None:
            await db.commit()
            raise HTTPException(
                422,
                "No models are registered with the orchestrator. Connect an "
                "agent so its Ollama (or other provider) models can sync, "
                "then try again.",
            )
        if needs_orch_model:
            await repo.update(lab_id, orchestrator_model_id=default_model.id)
        for a in agents_missing_model:
            await LabAgentRepository(db).update(a.id, model_id=default_model.id)

    # Normalize terminal states so the loop starts cleanly.
    if lab.status in ("completed", "failed"):
        await repo.update(
            lab_id,
            status="created",
            completed_at=None,
            failure_reason=None,
        )
    await db.commit()

    from app.services.container_manager import ensure_sandbox

    await ensure_sandbox(lab_id, memory_mb=lab.tool_container_memory_mb)

    new_runner = await reserve_runner(lab_id, async_session)
    if new_runner is None:
        # Another caller raced in between persist and spawn; the inject
        # row will still be picked up by their runner.
        return {"status": "injected", "started_runner": False}
    background_tasks.add_task(new_runner.run)
    return {"status": "injected", "started_runner": True}
