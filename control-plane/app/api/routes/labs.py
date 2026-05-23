"""Bob Manager — Lab API routes.

All endpoints live under /api/v1/labs/...
Sub-modules: labs_blueprint (import/export), labs_execution (lifecycle),
             labs_files (resources, output files, messages, memories).
"""

import os
import shutil
import uuid as uuid_mod
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.api.dependencies import DbSession, get_current_user
from app.services.authorization import check_permission, Permission
from app.models.orchestrator import LabMessage
from app.repositories.lab_repo import (
    LabAgentRepository,
    LabRepository,
    LabResourceRepository,
    LabToolRepository,
)
from app.schemas.orchestrator import (
    LabAgentCreate,
    LabAgentResponse,
    LabAgentUpdate,
    LabCreate,
    LabResponse,
    LabToolCreate,
    LabToolResponse,
    LabToolUpdate,
    LabUpdate,
)
from app.services.lab_runner import get_runner

router = APIRouter(prefix="/labs", tags=["labs"])

LAB_RESOURCES_ROOT = Path(os.environ.get("LAB_RESOURCES_PATH", "/data/lab_resources"))


# ══════════════════════════════════════════════════
# Strategy Prompts
# ══════════════════════════════════════════════════


@router.get("/strategies")
async def list_loop_strategies():
    """Return all registered loop strategies with display metadata.

    The frontend lab editor populates its loop_type dropdown from this list,
    so adding a new strategy in the backend automatically surfaces it in the
    UI without requiring a frontend change.
    """
    from app.services.loop_strategies import list_strategies
    return {"strategies": list_strategies()}


@router.get("/strategy-prompts/{loop_type}")
async def get_strategy_prompt(loop_type: str):
    """Return the default system prompt template for a given strategy type."""
    from app.services.loop_strategies import get_strategy_prompt as _get_prompt
    prompt = _get_prompt(loop_type)
    if prompt is None:
        raise HTTPException(404, f"Unknown strategy type: {loop_type}")
    return {"loop_type": loop_type, "prompt": prompt}


# ══════════════════════════════════════════════════
# Agent Library (all agents across all labs)
# ══════════════════════════════════════════════════


@router.get("/agents/library", response_model=list[LabAgentResponse])
async def list_all_agents(db: DbSession):
    """Return every agent across all labs — used as an agent library for reuse."""
    return await LabAgentRepository(db).get_all()


# ══════════════════════════════════════════════════
# Lab CRUD
# ══════════════════════════════════════════════════


@router.get("", response_model=list[LabResponse])
async def list_labs(
    db: DbSession,
    user: dict = Depends(get_current_user),
    include_app_runs: bool = False,
    include_showroom: bool = False,  # Deprecated alias for include_app_runs.
):
    repo = LabRepository(db)
    labs = await repo.get_all(user=user)
    if not (include_app_runs or include_showroom):
        # Hide consumer-app templates and runs from the normal Labs UI.
        # Tag prefixes:
        #   • ``app:<app_id>:template:…`` / ``app:<app_id>:run:…`` (canonical)
        #   • ``showroom_template:…`` / ``showroom_run:…`` (legacy rows)
        def _is_app_tagged(lab) -> bool:
            if not isinstance(lab.acl, dict):
                return False
            tag = str(lab.acl.get("tag", ""))
            return tag.startswith("app:") or tag.startswith("showroom_")

        labs = [lab for lab in labs if not _is_app_tagged(lab)]
    # Always hide single-agent instance labs from the normal Labs UI;
    # they live under the Agents page.
    labs = [
        lab for lab in labs
        if not (isinstance(lab.acl, dict) and lab.acl.get("tag") == "agent_instance")
    ]
    agent_repo = LabAgentRepository(db)
    message_counts = await _get_message_counts(db, [lab.id for lab in labs])
    results = []
    for lab in labs:
        agents = await agent_repo.get_by_lab(lab.id)
        results.append(_lab_to_response(lab, len(agents), message_counts.get(lab.id, 0)))
    return results


@router.post("", response_model=LabResponse, status_code=status.HTTP_201_CREATED)
async def create_lab(data: LabCreate, db: DbSession, user: dict = Depends(get_current_user)):
    repo = LabRepository(db)
    lab = await repo.create(user=user, **data.model_dump(exclude_unset=True))
    return _lab_to_response(lab, 0, 0)


@router.get("/{lab_id}", response_model=LabResponse)
async def get_lab(lab_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.VIEW)
    agents = await LabAgentRepository(db).get_by_lab(lab.id)
    message_counts = await _get_message_counts(db, [lab.id])
    return _lab_to_response(lab, len(agents), message_counts.get(lab.id, 0))


@router.patch("/{lab_id}", response_model=LabResponse)
async def update_lab(lab_id: UUID, data: LabUpdate, db: DbSession, user: dict = Depends(get_current_user)):
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.EDIT)
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    lab = await repo.update(lab_id, **updates)
    if not lab:
        raise HTTPException(404, "Lab not found")
    agents = await LabAgentRepository(db).get_by_lab(lab.id)
    message_counts = await _get_message_counts(db, [lab.id])
    return _lab_to_response(lab, len(agents), message_counts.get(lab.id, 0))


@router.delete("/{lab_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lab(lab_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    repo = LabRepository(db)
    lab = await repo.get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.DELETE)
    # Stop runner if active
    runner = get_runner(lab_id)
    if runner:
        await runner.stop()
    # Destroy per-lab sandbox container
    from app.services.container_manager import destroy_sandbox
    await destroy_sandbox(lab_id)
    await repo.delete(lab_id)


@router.post("/{lab_id}/duplicate", response_model=LabResponse, status_code=status.HTTP_201_CREATED)
async def duplicate_lab(lab_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    """Create a full copy of a lab including agents, tools, and resource files."""
    lab_repo = LabRepository(db)
    lab = await lab_repo.get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.VIEW)

    # Create new lab with same config but reset execution state
    new_lab = await lab_repo.create(
        user=user,
        name=f"{lab.name} (copy)",
        description=lab.description,
        loop_type=lab.loop_type,
        loop_config=lab.loop_config,
        orchestrator_model_id=lab.orchestrator_model_id,
        orchestrator_prompt=lab.orchestrator_prompt,
        orchestrator_prompt_template_id=lab.orchestrator_prompt_template_id,
        orchestrator_temperature=lab.orchestrator_temperature,
        orchestrator_max_tokens=lab.orchestrator_max_tokens,
        orchestrator_tools=lab.orchestrator_tools,
        orchestrator_tool_set_id=lab.orchestrator_tool_set_id,
        orchestrator_tool_set_ids=lab.orchestrator_tool_set_ids,
        max_iterations=lab.max_iterations,
        max_duration_sec=lab.max_duration_sec,
        context_files=lab.context_files,
        share_memory_override=lab.share_memory_override,
        strategy_prompt_override=lab.strategy_prompt_override,
        auto_sweep_memory=lab.auto_sweep_memory,
        tool_max_calls=lab.tool_max_calls,
        tool_timeout_sec=lab.tool_timeout_sec,
        tool_max_output_kb=lab.tool_max_output_kb,
        tool_container_memory_mb=lab.tool_container_memory_mb,
    )

    # Copy agents
    agent_repo = LabAgentRepository(db)
    agents = await agent_repo.get_by_lab(lab.id)
    for agent in agents:
        await agent_repo.create(
            lab_id=new_lab.id,
            name=agent.name,
            role=agent.role,
            system_prompt=agent.system_prompt,
            model_id=agent.model_id,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
            tools=agent.tools,
            tool_set_id=agent.tool_set_id,
            tool_set_ids=agent.tool_set_ids,
            is_active=agent.is_active,
            sort_order=agent.sort_order,
            share_memory=agent.share_memory,
        )

    # Copy tools
    tool_repo = LabToolRepository(db)
    tools = await tool_repo.get_by_lab(lab.id)
    for tool in tools:
        await tool_repo.create(
            lab_id=new_lab.id,
            name=tool.name,
            description=tool.description,
            tool_type=tool.tool_type,
            config=tool.config,
            execution_side=tool.execution_side,
            is_enabled=tool.is_enabled,
        )

    # Copy resource files
    res_repo = LabResourceRepository(db)
    resources = await res_repo.get_by_lab(lab.id)
    old_dir = LAB_RESOURCES_ROOT / str(lab.id)
    new_dir = LAB_RESOURCES_ROOT / str(new_lab.id)
    if resources and old_dir.is_dir():
        new_dir.mkdir(parents=True, exist_ok=True)
        for res in resources:
            src = old_dir / res.filename
            if src.is_file():
                shutil.copy2(src, new_dir / res.filename)
            await res_repo.create(
                lab_id=new_lab.id,
                filename=res.filename,
                original_name=res.original_name,
                content_type=res.content_type,
                size_bytes=res.size_bytes,
                resource_type=res.resource_type,
                description=res.description,
            )

    new_agents = await agent_repo.get_by_lab(new_lab.id)
    return _lab_to_response(new_lab, len(new_agents), 0)


# ══════════════════════════════════════════════════
# Lab Agents
# ══════════════════════════════════════════════════


@router.get("/{lab_id}/agents", response_model=list[LabAgentResponse])
async def list_lab_agents(lab_id: UUID, db: DbSession):
    return await LabAgentRepository(db).get_by_lab(lab_id)


@router.post(
    "/{lab_id}/agents",
    response_model=LabAgentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_lab_agent(lab_id: UUID, data: LabAgentCreate, db: DbSession):
    # Verify lab exists
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    return await LabAgentRepository(db).create(
        lab_id=lab_id, **data.model_dump(exclude_unset=True)
    )


@router.patch("/{lab_id}/agents/{agent_id}", response_model=LabAgentResponse)
async def update_lab_agent(lab_id: UUID, agent_id: UUID, data: LabAgentUpdate, db: DbSession):
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    agent = await LabAgentRepository(db).update(agent_id, **updates)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


@router.delete("/{lab_id}/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lab_agent(lab_id: UUID, agent_id: UUID, db: DbSession):
    await LabAgentRepository(db).delete(agent_id)


# ══════════════════════════════════════════════════
# Lab Tools
# ══════════════════════════════════════════════════


@router.get("/{lab_id}/tools", response_model=list[LabToolResponse])
async def list_lab_tools(lab_id: UUID, db: DbSession):
    return await LabToolRepository(db).get_by_lab(lab_id)


@router.post(
    "/{lab_id}/tools",
    response_model=LabToolResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_lab_tool(lab_id: UUID, data: LabToolCreate, db: DbSession):
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    return await LabToolRepository(db).create(
        lab_id=lab_id, **data.model_dump(exclude_unset=True)
    )


@router.patch("/{lab_id}/tools/{tool_id}", response_model=LabToolResponse)
async def update_lab_tool(lab_id: UUID, tool_id: UUID, data: LabToolUpdate, db: DbSession):
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    tool = await LabToolRepository(db).update(tool_id, **updates)
    if not tool:
        raise HTTPException(404, "Tool not found")
    return tool


@router.delete("/{lab_id}/tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lab_tool(lab_id: UUID, tool_id: UUID, db: DbSession):
    await LabToolRepository(db).delete(tool_id)


# ══════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════


async def _get_message_counts(db: DbSession, lab_ids: list[UUID]) -> dict[UUID, int]:
    if not lab_ids:
        return {}
    result = await db.execute(
        select(LabMessage.lab_id, func.count(LabMessage.id))
        .where(LabMessage.lab_id.in_(lab_ids))
        .group_by(LabMessage.lab_id)
    )
    return {lab_id: int(count or 0) for lab_id, count in result.all()}


def _lab_to_response(lab, agent_count: int, message_count: int) -> dict:
    """Convert Lab ORM to response dict with aggregate counts."""
    return {
        "id": lab.id,
        "name": lab.name,
        "description": lab.description,
        "status": lab.status,
        "loop_type": lab.loop_type,
        "loop_config": lab.loop_config,
        "orchestrator_model_id": lab.orchestrator_model_id,
        "orchestrator_prompt": lab.orchestrator_prompt,
        "orchestrator_prompt_template_id": lab.orchestrator_prompt_template_id,
        "orchestrator_temperature": lab.orchestrator_temperature,
        "orchestrator_max_tokens": lab.orchestrator_max_tokens,
        "max_iterations": lab.max_iterations,
        "max_duration_sec": lab.max_duration_sec,
        "current_iteration": lab.current_iteration,
        "cron_expression": lab.cron_expression,
        "next_run_at": lab.next_run_at,
        "context_files": lab.context_files,
        "share_memory_override": lab.share_memory_override,
        "strategy_prompt_override": lab.strategy_prompt_override,
        "orchestrator_tools": lab.orchestrator_tools,
        "orchestrator_tool_set_id": lab.orchestrator_tool_set_id,
        "orchestrator_tool_set_ids": lab.orchestrator_tool_set_ids,
        "auto_sweep_memory": lab.auto_sweep_memory,
        "cron_job_ids": lab.cron_job_ids or [],
        "tool_max_calls": lab.tool_max_calls,
        "tool_timeout_sec": lab.tool_timeout_sec,
        "tool_max_output_kb": lab.tool_max_output_kb,
        "tool_container_memory_mb": lab.tool_container_memory_mb,
        "agent_count": agent_count,
        "message_count": message_count,
        "started_at": lab.started_at,
        "paused_at": lab.paused_at,
        "completed_at": lab.completed_at,
        "created_at": lab.created_at,
        "updated_at": lab.updated_at,
        "acl": lab.acl,
    }


# ══════════════════════════════════════════════════
# Include sub-routers
# ══════════════════════════════════════════════════

from app.api.routes.labs_blueprint import router as blueprint_router  # noqa: E402
from app.api.routes.labs_execution import router as execution_router  # noqa: E402
from app.api.routes.labs_files import router as files_router  # noqa: E402
from app.api.routes.labs_loop import router as loop_router  # noqa: E402

router.include_router(blueprint_router)
router.include_router(execution_router)
router.include_router(files_router)
router.include_router(loop_router)

