"""Lab Blueprint — JSON import & export routes."""

import uuid as uuid_mod
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import DbSession, get_current_user
from app.api.routes.labs import _lab_to_response
from app.repositories.lab_repo import (
    LabAgentRepository,
    LabRepository,
    PromptTemplateRepository,
)
from app.repositories.rag_repo import LabRagAccessRepository, RagCollectionRepository
from app.schemas.orchestrator import LabBlueprint, LabResponse
from app.services.authorization import Permission, check_permission

router = APIRouter(tags=["labs"])


@router.get("/{lab_id}/export", response_model=LabBlueprint)
async def export_lab(lab_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    """Export a lab as a portable JSON blueprint.

    Cluster G — previously anonymous and shipped system_prompt for every
    agent (a system-wide leak path: anyone with a lab UUID could harvest
    prompts). Now requires authentication, applies the same Permission.EDIT
    check used by labs_execution.update_lab so only editors/owners can
    extract a blueprint, and zeroes out every system_prompt in the
    response — re-importing the blueprint produces a lab whose agents
    have empty prompts that the new owner must re-author.
    """
    from app.repositories.orchestrator_repo import AIModelRepository

    lab_repo = LabRepository(db)
    lab = await lab_repo.get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.EDIT)

    # Helpers to resolve UUIDs to portable names
    model_repo = AIModelRepository(db)

    async def model_ref(model_id):
        if not model_id:
            return None
        m = await model_repo.get_by_id(model_id)
        return m.model_identifier if m else None

    async def prompt_template_ref(pt_id):
        if not pt_id:
            return None
        pt = await PromptTemplateRepository(db).get_by_id(pt_id)
        return pt.name if pt else None

    from app.repositories.lab_repo import ToolSetRepository as TSRepo

    async def tool_set_refs(ts_id, ts_ids):
        names = []
        ts_repo = TSRepo(db)
        if ts_id:
            ts = await ts_repo.get_by_id(ts_id)
            if ts:
                names.append(ts.name)
        for tid in ts_ids or []:
            try:
                ts = await ts_repo.get_by_id(uuid_mod.UUID(tid))
            except (ValueError, AttributeError):
                continue
            if ts and ts.name not in names:
                names.append(ts.name)
        return names

    # Build orchestrator section. Cluster G: the freeform prompt is
    # zeroed-out; importers see an empty prompt and must re-author it.
    # prompt_template references survive because they point at named,
    # reusable assets — the recipient still needs read access to those
    # templates in the target DB.
    orch = {
        "model": await model_ref(lab.orchestrator_model_id),
        "prompt": "",
        "prompt_template": await prompt_template_ref(lab.orchestrator_prompt_template_id),
        "temperature": float(lab.orchestrator_temperature or 0.7),
        "max_tokens": lab.orchestrator_max_tokens or 4096,
        "tools": lab.orchestrator_tools or [],
        "tool_sets": await tool_set_refs(
            lab.orchestrator_tool_set_id, lab.orchestrator_tool_set_ids
        ),
    }

    # Build settings section
    settings = {
        "max_iterations": lab.max_iterations,
        "max_duration_sec": lab.max_duration_sec,
        "cron_expression": lab.cron_expression,
        "tool_max_calls": lab.tool_max_calls or 10,
        "tool_timeout_sec": lab.tool_timeout_sec or 30,
        "tool_max_output_kb": lab.tool_max_output_kb or 256,
        "tool_container_memory_mb": lab.tool_container_memory_mb or 512,
        "share_memory_override": lab.share_memory_override,
        "auto_sweep_memory": lab.auto_sweep_memory or False,
    }

    # Build agents
    agent_repo = LabAgentRepository(db)
    agents = await agent_repo.get_by_lab(lab.id)
    agent_list = []
    for a in agents:
        agent_list.append(
            {
                "name": a.name,
                "role": a.role or "",
                # Cluster G: per-agent system prompt is the most leak-sensitive
                # field of a blueprint. Zero it out on export — re-import
                # produces an empty prompt that the new owner re-authors.
                "system_prompt": "",
                "prompt_template": await prompt_template_ref(a.prompt_template_id),
                "model": await model_ref(a.model_id),
                "backend": getattr(a, "backend", "native") or "native",
                "temperature": float(a.temperature or 0.7),
                "max_tokens": a.max_tokens or 4096,
                "tools": a.tools or [],
                "tool_sets": await tool_set_refs(a.tool_set_id, a.tool_set_ids),
                "is_active": a.is_active if a.is_active is not None else True,
                "sort_order": a.sort_order or 0,
                "share_memory": a.share_memory or False,
                "callable_agents": a.callable_agents or [],
                "cron_expression": a.cron_expression,
                "cron_instruction": a.cron_instruction or "",
            }
        )

    # Export RAG access links so a re-import can recreate them in one shot.
    access_rows = await LabRagAccessRepository(db).get_by_lab(lab.id)
    rag_access = [
        {
            "collection_name": collection.name,
            "can_read": entry.can_read,
            "can_write": entry.can_write,
        }
        for entry, collection in access_rows
    ]

    return {
        "version": 1,
        "lab": {
            "name": lab.name,
            "description": lab.description or "",
            "loop_type": lab.loop_type or "plan_execute",
            "loop_config": lab.loop_config or {},
            "strategy_prompt_override": lab.strategy_prompt_override,
            "context_files": lab.context_files or [],
            "orchestrator": orch,
            "settings": settings,
            "agents": agent_list,
            "rag_access": rag_access,
        },
    }


@router.post("/import", response_model=LabResponse, status_code=status.HTTP_201_CREATED)
async def import_lab(
    blueprint: LabBlueprint, db: DbSession, user: dict = Depends(get_current_user)
):
    """Create a new lab from a JSON blueprint."""
    from app.repositories.orchestrator_repo import AIModelRepository

    bp = blueprint.lab
    model_repo = AIModelRepository(db)

    async def resolve_model(ref: str | None):
        if not ref:
            return None
        # Match by model_identifier (dispatcher will load-balance across providers)
        all_models = await model_repo.get_all()
        for m in all_models:
            if m.model_identifier == ref:
                return m.id
        return None

    async def resolve_prompt_template(name: str | None):
        if not name:
            return None
        pt_repo = PromptTemplateRepository(db)
        all_pts = await pt_repo.get_all()
        for pt in all_pts:
            if pt.name == name:
                return pt.id
        return None

    from app.repositories.lab_repo import ToolSetRepository as TSRepo

    async def resolve_tool_sets(names: list[str]):
        if not names:
            return None, []
        ts_repo = TSRepo(db)
        all_ts = await ts_repo.get_all()
        ts_map = {ts.name: ts.id for ts in all_ts}
        resolved = [str(ts_map[n]) for n in names if n in ts_map]
        first_id = uuid_mod.UUID(resolved[0]) if resolved else None
        return first_id, resolved

    orch = bp.orchestrator
    settings = bp.settings

    orch_ts_id, orch_ts_ids = await resolve_tool_sets(orch.tool_sets)

    # Create lab
    lab_repo = LabRepository(db)
    lab = await lab_repo.create(
        user=user,
        name=bp.name,
        description=bp.description,
        loop_type=bp.loop_type,
        loop_config=bp.loop_config,
        strategy_prompt_override=bp.strategy_prompt_override,
        context_files=bp.context_files,
        orchestrator_model_id=await resolve_model(orch.model),
        orchestrator_prompt=orch.prompt,
        orchestrator_prompt_template_id=await resolve_prompt_template(orch.prompt_template),
        orchestrator_temperature=orch.temperature,
        orchestrator_max_tokens=orch.max_tokens,
        orchestrator_tools=orch.tools,
        orchestrator_tool_set_id=orch_ts_id,
        orchestrator_tool_set_ids=orch_ts_ids,
        max_iterations=settings.max_iterations,
        max_duration_sec=settings.max_duration_sec,
        cron_expression=settings.cron_expression,
        tool_max_calls=settings.tool_max_calls,
        tool_timeout_sec=settings.tool_timeout_sec,
        tool_max_output_kb=settings.tool_max_output_kb,
        tool_container_memory_mb=settings.tool_container_memory_mb,
        share_memory_override=settings.share_memory_override,
        auto_sweep_memory=settings.auto_sweep_memory,
        anti_loop_enabled=bp.anti_loop_enabled,
    )

    # Create agents
    agent_repo = LabAgentRepository(db)
    for a in bp.agents:
        a_ts_id, a_ts_ids = await resolve_tool_sets(a.tool_sets)
        await agent_repo.create(
            lab_id=lab.id,
            name=a.name,
            role=a.role,
            system_prompt=a.system_prompt,
            prompt_template_id=await resolve_prompt_template(a.prompt_template),
            model_id=await resolve_model(a.model),
            backend=a.backend,
            temperature=a.temperature,
            max_tokens=a.max_tokens,
            tools=a.tools,
            tool_set_id=a_ts_id,
            tool_set_ids=a_ts_ids,
            is_active=a.is_active,
            sort_order=a.sort_order,
            share_memory=a.share_memory,
            callable_agents=a.callable_agents,
            cron_expression=a.cron_expression,
            cron_instruction=a.cron_instruction,
            anti_loop_enabled=a.anti_loop_enabled,
        )

    # Materialize rag_access entries from the blueprint.
    # Ownership/permission checks are the caller's responsibility — for
    # consumer-app imports, /internal/apps/import_lab pre-validates these
    # against the app's owned collections before calling us.
    if getattr(bp, "rag_access", None):
        coll_repo = RagCollectionRepository(db)
        access_repo = LabRagAccessRepository(db)
        for ref in bp.rag_access:
            collection = await coll_repo.get_by_name(ref.collection_name)
            if not collection:
                raise HTTPException(
                    400,
                    f"RAG collection '{ref.collection_name}' not found; "
                    f"create it before importing this blueprint.",
                )
            existing = await access_repo.get_entry(lab.id, collection.id)
            if existing:
                continue
            await access_repo.create(
                lab_id=lab.id,
                collection_id=collection.id,
                can_read=ref.can_read,
                can_write=ref.can_write,
            )

    # Drop context_files to disk now so they show up in WORKSPACE FILES (and the
    # user can read/edit them) before the lab is ever run. The runner calls the
    # same function on each run — it's idempotent and only rewrites when the
    # content differs, so this doesn't fight with later edits.
    if bp.context_files:
        from app.services.lab_runner import _materialize_context_files

        _materialize_context_files(lab)

    agents = await agent_repo.get_by_lab(lab.id)
    return _lab_to_response(lab, len(agents), 0)
