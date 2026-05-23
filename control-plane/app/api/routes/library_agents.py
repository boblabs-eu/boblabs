"""Bob Manager — Library Agents API routes.

Standalone reusable agent definitions. Mounted at /api/v1/library-agents.
"""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, text

from app.api.dependencies import DbSession, get_current_user
from app.database import async_session
from app.models.orchestrator import Lab, LabAgent, LabMessage
from app.repositories.lab_repo import (
    LabAgentRepository,
    LabRepository,
    LibraryAgentRepository,
)
from app.schemas.orchestrator import (
    LibraryAgentCreate,
    LibraryAgentResponse,
    LibraryAgentUpdate,
)
from app.services.authorization import get_default_acl
from app.services.lab_runner import LabRunner, get_runner
from app.services.library_agent_service import (
    create_agent_instance as _create_agent_instance,
    is_app_owned_agent_name,
)

router = APIRouter(prefix="/library-agents", tags=["library-agents"])


def _library_agent_match_clause(agent_id: UUID, agent_name: str, system_prompt: str):
    normalized_name = (agent_name or "").strip().lower()
    return or_(
        LabAgent.library_agent_id == agent_id,
        and_(
            LabAgent.library_agent_id.is_(None),
            func.lower(LabAgent.name) == normalized_name,
            LabAgent.system_prompt == (system_prompt or ""),
        ),
    )


@router.get("", response_model=list[LibraryAgentResponse])
async def list_library_agents(db: DbSession, include_app_owned: bool = False):
    """List operator-managed library agents.

    Consumer-app agents (namespaced ``app__<app_id>__*``) are filtered out
    by default so the operator UI only shows things humans manage. Pass
    ``include_app_owned=true`` to surface them for debugging.
    """
    rows = await LibraryAgentRepository(db).get_all()
    if include_app_owned:
        return rows
    return [a for a in rows if not is_app_owned_agent_name(a.name)]


@router.post("", response_model=LibraryAgentResponse, status_code=status.HTTP_201_CREATED)
async def create_library_agent(data: LibraryAgentCreate, db: DbSession):
    return await LibraryAgentRepository(db).create(**data.model_dump(exclude_unset=True))


# ══════════════════════════════════════════════════
# Agent Instances (single-agent labs spawned from a template)
# ══════════════════════════════════════════════════


class AgentInstanceCreate(BaseModel):
    name: str | None = None
    pseudo: str | None = None


def _instance_to_response(lab: Lab) -> dict:
    acl = lab.acl if isinstance(lab.acl, dict) else {}
    return {
        "id": str(lab.id),
        "lab_id": str(lab.id),
        "library_agent_id": acl.get("library_agent_id"),
        "pseudo": acl.get("pseudo"),
        "name": lab.name,
        "status": lab.status,
        "current_iteration": lab.current_iteration,
        "max_iterations": lab.max_iterations,
        "created_at": lab.created_at.isoformat() if lab.created_at else None,
        "updated_at": lab.updated_at.isoformat() if lab.updated_at else None,
        "started_at": lab.started_at.isoformat() if lab.started_at else None,
        "paused_at": lab.paused_at.isoformat() if lab.paused_at else None,
        "completed_at": lab.completed_at.isoformat() if lab.completed_at else None,
    }


def _is_instance_lab(lab: Lab) -> bool:
    return isinstance(lab.acl, dict) and lab.acl.get("tag") == "agent_instance"


@router.get("/instances")
async def list_all_agent_instances(db: DbSession, library_agent_id: UUID | None = None):
    """List all single-agent instance labs (across all templates)."""
    repo = LabRepository(db)
    labs = await repo.get_all()
    instances = [lab for lab in labs if _is_instance_lab(lab)]
    if library_agent_id is not None:
        instances = [
            lab for lab in instances
            if str(lab.acl.get("library_agent_id")) == str(library_agent_id)
        ]
    return [_instance_to_response(lab) for lab in instances]


@router.post("/{agent_id}/instances", status_code=status.HTTP_201_CREATED)
async def create_agent_instance(
    agent_id: UUID,
    data: AgentInstanceCreate,
    db: DbSession,
    user: dict = Depends(get_current_user),
):
    """Create a runnable single-agent Lab from a library agent template."""
    repo = LibraryAgentRepository(db)
    template = await repo.get_by_id(agent_id)
    if not template:
        raise HTTPException(404, "Library agent not found")

    lab_repo = LabRepository(db)
    pseudo = (data.pseudo or "").strip()
    instance_name = (data.name or "").strip()
    if not instance_name:
        existing = await lab_repo.get_all()
        sibling_count = sum(
            1 for lab in existing
            if _is_instance_lab(lab)
            and isinstance(lab.acl, dict)
            and str(lab.acl.get("library_agent_id")) == str(agent_id)
        )
        existing_names = {
            lab.name for lab in existing
            if _is_instance_lab(lab)
            and isinstance(lab.acl, dict)
            and str(lab.acl.get("library_agent_id")) == str(agent_id)
        }
        n = sibling_count + 1
        while True:
            base = f"{template.name} #{n}"
            candidate = f"{base} - {pseudo}" if pseudo else base
            if candidate not in existing_names:
                instance_name = candidate
                break
            n += 1

    try:
        lab = await _create_agent_instance(
            db,
            library_agent_id=agent_id,
            instance_name=instance_name,
            pseudo=pseudo,
            user_sub=user.get("sub", "admin"),
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    await db.commit()
    return _instance_to_response(lab)


@router.get("/{agent_id}/instances")
async def list_agent_instances(agent_id: UUID, db: DbSession):
    """List all instances spawned from a given template."""
    return await list_all_agent_instances(db, library_agent_id=agent_id)


@router.delete("/instances/{lab_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_instance(lab_id: UUID, db: DbSession):
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    if not lab or not _is_instance_lab(lab):
        raise HTTPException(404, "Agent instance not found")
    # Stop runner if active
    runner = get_runner(lab_id)
    if runner:
        try:
            await runner.stop()
        except Exception:
            pass
    await repo.delete(lab_id)
    await db.commit()


@router.post("/instances/{lab_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_agent_instance(
    lab_id: UUID,
    background_tasks: BackgroundTasks,
    db: DbSession,
    reset: bool = False,
):
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    if not lab or not _is_instance_lab(lab):
        raise HTTPException(404, "Agent instance not found")
    if lab.status == "running":
        raise HTTPException(409, "Already running")
    if get_runner(lab_id):
        raise HTTPException(409, "Runner already active")

    if not lab.orchestrator_model_id:
        from app.repositories.orchestrator_repo import (
            AIModelRepository,
            OrchestratorSettingsRepository,
        )
        settings = await OrchestratorSettingsRepository(db).get()
        if not settings or not settings.orchestrator_model:
            raise HTTPException(422, "No model configured and no default model set")
        for m in await AIModelRepository(db).get_all():
            if m.model_identifier == settings.orchestrator_model:
                await repo.update(lab_id, orchestrator_model_id=m.id)
                break
        await db.commit()
        lab = await repo.get_by_id(lab_id)

    if reset:
        from app.repositories.lab_repo import (
            LabMemoryRepository,
            LabMessageRepository,
        )
        await LabMessageRepository(db).delete_by_lab(lab_id)
        await LabMemoryRepository(db).delete_by_lab(lab_id)
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
        await repo.update(lab_id, status="created", completed_at=None)
        await db.commit()

    from app.services.container_manager import ensure_sandbox
    await ensure_sandbox(lab_id, memory_mb=lab.tool_container_memory_mb)

    runner = LabRunner(lab_id, async_session)
    background_tasks.add_task(runner.run)
    return {"status": "started", "lab_id": str(lab_id), "reset": reset}


@router.post("/instances/{lab_id}/pause")
async def pause_agent_instance(lab_id: UUID, db: DbSession):
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    if not lab or not _is_instance_lab(lab):
        raise HTTPException(404, "Agent instance not found")
    runner = get_runner(lab_id)
    if not runner:
        raise HTTPException(409, "Not running")
    await runner.pause()
    return {"status": "paused", "lab_id": str(lab_id)}


@router.post("/instances/{lab_id}/resume")
async def resume_agent_instance(
    lab_id: UUID,
    background_tasks: BackgroundTasks,
    db: DbSession,
):
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    if not lab or not _is_instance_lab(lab):
        raise HTTPException(404, "Agent instance not found")
    runner = get_runner(lab_id)
    if runner:
        await runner.resume()
        return {"status": "resumed", "lab_id": str(lab_id)}
    # No active runner — restart the loop
    if lab.status not in ("paused", "created"):
        await repo.update(lab_id, status="created")
        await db.commit()
    runner = LabRunner(lab_id, async_session)
    background_tasks.add_task(runner.run)
    return {"status": "resumed", "lab_id": str(lab_id)}


@router.post("/instances/{lab_id}/stop")
async def stop_agent_instance(lab_id: UUID, db: DbSession):
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    if not lab or not _is_instance_lab(lab):
        raise HTTPException(404, "Agent instance not found")
    runner = get_runner(lab_id)
    if runner:
        await runner.stop()
    else:
        await repo.update(lab_id, status="completed")
        await db.commit()
    return {"status": "stopped", "lab_id": str(lab_id)}


@router.post("/instances/{lab_id}/inject")
async def inject_agent_instance(
    lab_id: UUID,
    payload: dict,
    background_tasks: BackgroundTasks,
    db: DbSession,
):
    """Inject a user message; auto-spawn the runner if none is active.

    Three live states with distinct handling:
    - Runner already active (running or paused): forward the message to its
      in-memory queue via ``runner.inject``, which wakes the paused event.
    - No runner + lab in an idle state (created / completed / failed / or
      stale paused after bob-api restart): persist the inject row AND start
      a fresh runner so the user doesn't need a manual Run click. Completed
      and failed labs are normalized back to ``created`` so the loop can
      pick up cleanly.
    """
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    if not lab or not _is_instance_lab(lab):
        raise HTTPException(404, "Agent instance not found")
    message = (payload or {}).get("message", "").strip()
    if not message:
        raise HTTPException(400, "message is required")

    runner = get_runner(lab_id)
    if runner:
        await runner.inject(message)
        return {"status": "injected", "lab_id": str(lab_id), "started_runner": False}

    # No active runner — persist the message and spawn a fresh runner.
    from app.repositories.lab_repo import LabMessageRepository

    await LabMessageRepository(db).create(
        lab_id=lab_id,
        iteration=lab.current_iteration,
        sender_type="user",
        content=message,
        message_type="user_inject",
    )

    if not lab.orchestrator_model_id:
        from app.repositories.orchestrator_repo import (
            AIModelRepository,
            OrchestratorSettingsRepository,
        )
        settings = await OrchestratorSettingsRepository(db).get()
        if not settings or not settings.orchestrator_model:
            await db.commit()
            raise HTTPException(
                422,
                "Agent has no model configured and no default model set — "
                "open the Agent tab and pick a model before injecting.",
            )
        for m in await AIModelRepository(db).get_all():
            if m.model_identifier == settings.orchestrator_model:
                await repo.update(lab_id, orchestrator_model_id=m.id)
                break

    # Normalize terminal states back to 'created' so the loop starts cleanly.
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
    return {"status": "injected", "lab_id": str(lab_id), "started_runner": True}


# ══════════════════════════════════════════════════
# Library Agent CRUD by id
# ══════════════════════════════════════════════════


async def get_library_agent(agent_id: UUID, db: DbSession):
    agent = await LibraryAgentRepository(db).get_by_id(agent_id)
    if not agent:
        raise HTTPException(404, "Library agent not found")
    return agent


@router.patch("/{agent_id}", response_model=LibraryAgentResponse)
async def update_library_agent(agent_id: UUID, data: LibraryAgentUpdate, db: DbSession):
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    agent = await LibraryAgentRepository(db).update(agent_id, **updates)
    if not agent:
        raise HTTPException(404, "Library agent not found")

    # ── Cascade to existing single-agent instances ────────────────────────
    # When the operator edits the template (e.g. swaps the model from a
    # missing one to qwen3.5:9b), that change should immediately apply to
    # every Lab spawned from this template. Otherwise the running instance
    # keeps the snapshot taken at instance-creation time and the user thinks
    # "I saved the model but it still uses the old one".
    _AGENT_FIELDS = {
        "name", "role", "system_prompt", "prompt_template_id",
        "model_id", "temperature", "max_tokens",
        "tools", "tool_set_ids",
        "share_memory", "callable_agents",
        "cron_expression", "cron_instruction",
        "anti_loop_enabled",
    }
    _LAB_FIELD_MAP = {
        "model_id":      "orchestrator_model_id",
        "temperature":   "orchestrator_temperature",
        "max_tokens":    "orchestrator_max_tokens",
        "tools":         "orchestrator_tools",
        "tool_set_ids":  "orchestrator_tool_set_ids",
        "anti_loop_enabled": "anti_loop_enabled",
    }

    agent_updates = {k: v for k, v in updates.items() if k in _AGENT_FIELDS}
    lab_updates = {dst: updates[src] for src, dst in _LAB_FIELD_MAP.items() if src in updates}

    if agent_updates or lab_updates:
        lab_repo = LabRepository(db)
        agent_repo = LabAgentRepository(db)
        labs = await lab_repo.get_all()
        touched = 0
        for lab in labs:
            acl = lab.acl if isinstance(lab.acl, dict) else {}
            if acl.get("tag") != "agent_instance":
                continue
            if str(acl.get("library_agent_id")) != str(agent_id):
                continue
            if lab_updates:
                await lab_repo.update(lab.id, **lab_updates)
            if agent_updates:
                # Update every lab_agent row that points back to this template
                rows = (
                    await db.execute(
                        select(LabAgent).where(
                            LabAgent.lab_id == lab.id,
                            LabAgent.library_agent_id == agent_id,
                        )
                    )
                ).scalars().all()
                for row in rows:
                    await agent_repo.update(row.id, **agent_updates)
            touched += 1
        if touched:
            await db.commit()

    return agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_library_agent(agent_id: UUID, db: DbSession):
    agent = await LibraryAgentRepository(db).get_by_id(agent_id)
    if not agent:
        raise HTTPException(404, "Library agent not found")
    await LibraryAgentRepository(db).delete(agent_id)


@router.post("/{agent_id}/duplicate", response_model=LibraryAgentResponse, status_code=status.HTTP_201_CREATED)
async def duplicate_library_agent(agent_id: UUID, db: DbSession):
    repo = LibraryAgentRepository(db)
    agent = await repo.get_by_id(agent_id)
    if not agent:
        raise HTTPException(404, "Library agent not found")
    return await repo.create(
        name=f"{agent.name} (copy)",
        role=agent.role,
        system_prompt=agent.system_prompt,
        prompt_template_id=agent.prompt_template_id,
        model_id=agent.model_id,
        temperature=agent.temperature,
        max_tokens=agent.max_tokens,
        tools=list(agent.tools),
        tool_set_ids=list(agent.tool_set_ids),
        share_memory=agent.share_memory,
        callable_agents=list(agent.callable_agents),
        cron_expression=agent.cron_expression,
        cron_instruction=agent.cron_instruction,
    )


# ── Usage & stats ─────────────────────────────────


@router.get("/{agent_id}/labs")
async def get_library_agent_labs(agent_id: UUID, db: DbSession):
    """Return labs that reference this library agent (one entry per lab_agent linkage)."""
    repo = LibraryAgentRepository(db)
    agent = await repo.get_by_id(agent_id)
    if not agent:
        raise HTTPException(404, "Library agent not found")

    stmt = (
        select(
            LabAgent.id,
            Lab.id,
            Lab.name,
            Lab.status,
            Lab.current_iteration,
            Lab.max_iterations,
            Lab.updated_at,
        )
        .join(Lab, Lab.id == LabAgent.lab_id)
        .where(_library_agent_match_clause(agent_id, agent.name, agent.system_prompt))
        .order_by(Lab.updated_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "lab_agent_id": str(row[0]),
            "lab_id": str(row[1]),
            "lab_name": row[2],
            "status": row[3],
            "current_iteration": row[4],
            "max_iterations": row[5],
            "updated_at": row[6].isoformat() if row[6] else None,
        }
        for row in rows
    ]


@router.get("/{agent_id}/stats")
async def get_library_agent_stats(agent_id: UUID, db: DbSession):
    """Aggregate usage stats for a library agent across all labs that use it."""
    repo = LibraryAgentRepository(db)
    agent = await repo.get_by_id(agent_id)
    if not agent:
        raise HTTPException(404, "Library agent not found")

    # Collect lab_agent ids derived from this library agent
    la_rows = (
        await db.execute(
            select(LabAgent.id, LabAgent.lab_id).where(
                _library_agent_match_clause(agent_id, agent.name, agent.system_prompt)
            )
        )
    ).all()
    lab_agent_ids = [row[0] for row in la_rows]
    lab_ids = list({row[1] for row in la_rows})

    if not lab_agent_ids:
        return {
            "labs_count": 0,
            "messages_total": 0,
            "successes": 0,
            "failures": 0,
            "loop_triggers": 0,
            "tokens_in_total": 0,
            "tokens_out_total": 0,
            "last_active": None,
        }

    # Aggregate over LabMessage
    agg = (
        await db.execute(
            select(
                func.count(LabMessage.id),
                func.coalesce(func.sum(LabMessage.tokens_in), 0),
                func.coalesce(func.sum(LabMessage.tokens_out), 0),
                func.max(LabMessage.created_at),
            ).where(LabMessage.sender_agent_id.in_(lab_agent_ids))
        )
    ).one()
    messages_total = int(agg[0] or 0)
    tokens_in_total = int(agg[1] or 0)
    tokens_out_total = int(agg[2] or 0)
    last_active = agg[3].isoformat() if agg[3] else None

    # Successes = non-error messages; failures = error message_type or tool_output.success false
    failures = int((
        await db.execute(
            select(func.count(LabMessage.id)).where(
                LabMessage.sender_agent_id.in_(lab_agent_ids),
                LabMessage.message_type == "error",
            )
        )
    ).scalar() or 0)
    successes = max(0, messages_total - failures)

    # Loop triggers — table is per-lab (no per-agent column today); count events for labs
    # that include this agent. Best-effort attribution.
    loop_triggers = 0
    if lab_ids:
        try:
            res = await db.execute(
                text(
                    "SELECT COUNT(*) FROM lab_loop_events WHERE lab_id = ANY(:ids)"
                ),
                {"ids": lab_ids},
            )
            loop_triggers = int(res.scalar() or 0)
        except Exception:
            loop_triggers = 0

    return {
        "labs_count": len(lab_ids),
        "messages_total": messages_total,
        "successes": successes,
        "failures": failures,
        "loop_triggers": loop_triggers,
        "tokens_in_total": tokens_in_total,
        "tokens_out_total": tokens_out_total,
        "last_active": last_active,
    }
