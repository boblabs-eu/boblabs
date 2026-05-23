"""Lab Execution — lifecycle routes (run / pause / resume / stop / reset / inject).

Auth: every route requires a valid JWT and EDIT permission on the lab's
ACL. Admins bypass via ``check_permission``. Mirrors the pattern in
``labs.py``.
"""

import shutil
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.api.dependencies import DbSession, get_current_user
from app.database import async_session
from app.repositories.lab_repo import (
    LabMemoryRepository,
    LabMessageRepository,
    LabRepository,
)
from app.schemas.orchestrator import LabInject
from app.services.authorization import check_permission, Permission
from app.services.lab_runner import LabRunner, get_runner
from app.api.routes.labs import LAB_RESOURCES_ROOT

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
    if get_runner(lab_id):
        raise HTTPException(409, "Lab runner already active")

    if not lab.orchestrator_model_id:
        # Fall back to the system-wide default model from OrchestratorSettings
        from app.repositories.orchestrator_repo import OrchestratorSettingsRepository, AIModelRepository
        settings_repo = OrchestratorSettingsRepository(db)
        settings = await settings_repo.get()
        if not settings or not settings.orchestrator_model:
            raise HTTPException(422, "Lab has no model configured and no default model set")
        model_repo = AIModelRepository(db)
        all_models = await model_repo.get_all()
        resolved_id = None
        for m in all_models:
            if m.model_identifier == settings.orchestrator_model:
                resolved_id = m.id
                break
        if not resolved_id:
            raise HTTPException(422, f"Default model '{settings.orchestrator_model}' not found in AI models")
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

    runner = LabRunner(lab_id, async_session)
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
    if get_runner(lab_id):
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
    # No runner in memory — just update DB status
    await repo.update(lab_id, status="paused")
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
    # No runner in memory (e.g. after server restart) — start a fresh runner
    if lab.status not in ("paused", "created"):
        raise HTTPException(409, f"Cannot resume lab with status '{lab.status}'")
    await repo.update(lab_id, status="created", paused_at=None)
    await db.commit()
    new_runner = LabRunner(lab_id, async_session)
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
    from app.repositories.orchestrator_repo import (
        AIModelRepository,
        OrchestratorSettingsRepository,
    )
    from app.repositories.lab_repo import LabAgentRepository

    lab_agents = await LabAgentRepository(db).get_by_lab(lab.id, active_only=True)
    agents_missing_model = [a for a in lab_agents if not a.model_id]
    needs_orch_model = not lab.orchestrator_model_id
    if needs_orch_model or agents_missing_model:
        settings_row = await OrchestratorSettingsRepository(db).get()
        default_ident = (settings_row.orchestrator_model if settings_row else "") or ""
        default_model = None
        if default_ident:
            for m in await AIModelRepository(db).get_all():
                if m.model_identifier == default_ident:
                    default_model = m
                    break
        if default_model is None:
            await db.commit()
            raise HTTPException(
                422,
                "Lab or its agent has no model configured and no default "
                "orchestrator model is set — open Orchestrator settings and "
                "pick a model before injecting.",
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

    new_runner = LabRunner(lab_id, async_session)
    background_tasks.add_task(new_runner.run)
    return {"status": "injected", "started_runner": True}
