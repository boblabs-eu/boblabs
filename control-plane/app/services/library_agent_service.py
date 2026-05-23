"""Bob Manager — Library agent instantiation service.

Spawning a runnable single-agent ``Lab`` from a ``LibraryAgent`` template is
needed in two places:

  * The operator UI (``/library-agents/{id}/instances``), which creates a
    persistent instance the user drives manually.
  * The consumer-app HMAC API (``/run_agent``), which spawns an ephemeral
    instance per request, runs it to completion, delivers a callback, then
    leaves the lab around for traceability under an ``app:<app_id>:agent_run:<gid>``
    ACL tag.

This module owns the duplication so the two callers stay in sync — in
particular, any change to the field-mapping LibraryAgent → Lab/LabAgent
(model, tools, share_memory, …) only needs to be made here.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orchestrator import Lab, LibraryAgent
from app.repositories.lab_repo import (
    LabAgentRepository,
    LabRepository,
    LibraryAgentRepository,
)
from app.repositories.rag_repo import (
    LabRagAccessRepository,
    RagCollectionRepository,
)
from app.schemas.orchestrator import RagAccessRef
from app.services.authorization import get_default_acl

logger = logging.getLogger(__name__)


async def create_agent_instance(
    db: AsyncSession,
    *,
    library_agent_id: UUID,
    instance_name: str,
    pseudo: str = "",
    acl: dict | None = None,
    rag_access: list[RagAccessRef] | None = None,
    user_sub: str = "admin",
) -> Lab:
    """Create a runnable single-agent ``Lab`` from a ``LibraryAgent``.

    Mirrors the historical inline logic in ``library_agents`` route. Callers
    are responsible for committing the session.

    Args:
        library_agent_id: Source template id.
        instance_name: Lab name to create. Must not collide with an existing
            lab — the caller decides on uniqueness.
        pseudo: Optional human label stored under ``acl.pseudo``; surfaced
            in the operator UI for instance lists.
        acl: Full ACL dict to assign to the new lab. If ``None``, the
            standard ``"agent_instance"``-tagged ACL is used so the operator
            UI picks it up under the agent's instance list. Consumer-app
            callers should pass an ``acl`` whose ``tag`` starts with
            ``"app:<app_id>:agent_run:"`` so the operator UI filters it out
            of the regular labs list.
        rag_access: Materializes ``LabRagAccess`` rows on the new lab. The
            caller has already validated ownership/permissions for each
            referenced collection.
        user_sub: Owner ``sub`` used when building the default ACL.

    Returns:
        The freshly created ``Lab``. The lab also has exactly one
        ``LabAgent`` row attached (mirroring the library agent's config).
    """
    template = await LibraryAgentRepository(db).get_by_id(library_agent_id)
    if not template:
        raise ValueError(f"Library agent {library_agent_id} not found.")

    if not acl:
        acl = get_default_acl(user_sub)
        acl["tag"] = "agent_instance"
        acl["library_agent_id"] = str(library_agent_id)
        if pseudo:
            acl["pseudo"] = pseudo
    else:
        # Normalize callers that pass acl but skip the library_agent_id hint
        acl.setdefault("library_agent_id", str(library_agent_id))
        if pseudo:
            acl.setdefault("pseudo", pseudo)

    lab_repo = LabRepository(db)
    lab = await lab_repo.create(
        name=instance_name,
        description=f"Agent instance of '{template.name}'",
        loop_type="solo_agent",
        orchestrator_model_id=template.model_id,
        orchestrator_temperature=template.temperature,
        orchestrator_max_tokens=template.max_tokens,
        orchestrator_tools=[],
        orchestrator_tool_set_ids=[],
        anti_loop_enabled=bool(template.anti_loop_enabled),
        acl=acl,
    )

    agent_repo = LabAgentRepository(db)
    await agent_repo.create(
        lab_id=lab.id,
        library_agent_id=template.id,
        name=template.name,
        role=template.role,
        system_prompt=template.system_prompt,
        prompt_template_id=template.prompt_template_id,
        model_id=template.model_id,
        temperature=template.temperature,
        max_tokens=template.max_tokens,
        tools=list(template.tools or []),
        tool_set_ids=list(template.tool_set_ids or []),
        share_memory=template.share_memory,
        callable_agents=list(template.callable_agents or []),
        anti_loop_enabled=template.anti_loop_enabled,
    )

    if rag_access:
        coll_repo = RagCollectionRepository(db)
        access_repo = LabRagAccessRepository(db)
        for ref in rag_access:
            collection = await coll_repo.get_by_name(ref.collection_name)
            if not collection:
                raise ValueError(
                    f"RAG collection '{ref.collection_name}' not found; "
                    f"create it before instantiating this agent."
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

    return lab


# ─────────────────────────────────────────────────────────────────────────────
# App-owned library agent helpers (consumer-app namespacing)
# ─────────────────────────────────────────────────────────────────────────────

_APP_AGENT_NAME_PREFIX = "app__"


def make_app_agent_name(app_id: str, short_name: str) -> str:
    """Compose the namespaced ``library_agents.name`` for an app-owned agent."""
    return f"app__{app_id}__{short_name}"


def is_app_owned_agent_name(name: str | None) -> bool:
    """Heuristic — every consumer-app agent is named ``app__<app_id>__<short>``."""
    return bool(name) and name.startswith(_APP_AGENT_NAME_PREFIX)


def short_name_for_app(name: str, app_id: str) -> str | None:
    """Return the un-namespaced short name iff ``name`` belongs to ``app_id``.

    Returns ``None`` if the name is not in the ``app__<app_id>__*`` namespace.
    """
    prefix = f"app__{app_id}__"
    if name.startswith(prefix):
        return name[len(prefix):]
    return None


async def get_app_owned_agent_by_short_name(
    db: AsyncSession, app_id: str, short_name: str
) -> LibraryAgent | None:
    """Look up an app-owned library agent by its short (un-namespaced) name."""
    from sqlalchemy import select

    full_name = make_app_agent_name(app_id, short_name)
    row = (
        await db.execute(select(LibraryAgent).where(LibraryAgent.name == full_name))
    ).scalars().first()
    return row


async def list_app_owned_agents(db: AsyncSession, app_id: str) -> list[LibraryAgent]:
    """Return every library agent in the ``app__<app_id>__*`` namespace."""
    from sqlalchemy import select

    prefix = f"app__{app_id}__"
    rows = (
        await db.execute(
            select(LibraryAgent)
            .where(LibraryAgent.name.like(f"{prefix}%"))
            .order_by(LibraryAgent.name)
        )
    ).scalars().all()
    return list(rows)
