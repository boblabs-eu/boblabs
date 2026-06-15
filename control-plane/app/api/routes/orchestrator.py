"""Bob Manager — AI Orchestrator API routes."""

from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import DbSession, get_current_user, require_admin
from app.models.orchestrator import AIAgent, AIProvider, Conversation
from app.repositories.orchestrator_repo import (
    AIAgentRepository,
    AIModelRepository,
    AIProviderRepository,
    OrchestratorSettingsRepository,
)
from app.schemas.orchestrator import (
    AIAgentCreate,
    AIAgentResponse,
    AIAgentUpdate,
    AIModelResponse,
    AIProviderCreate,
    AIProviderResponse,
    AIProviderUpdate,
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
    MessageCreate,
    MessageResponse,
    OrchestratorSettingsResponse,
    OrchestratorSettingsUpdate,
    TaskResponse,
)
from app.services.authorization import (
    Permission,
    check_permission,
    filter_query_by_access,
)
from app.services.comfyui_discovery import discover_comfyui_models
from app.services.conversation_service import ConversationService
from app.services.orchestrator_service import OrchestratorService
from app.services.task_queue_service import TaskQueueService

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])


async def _infer_provider_server_id(
    db: DbSession, base_url: str, server_id: UUID | None
) -> UUID | None:
    if server_id is not None or not base_url:
        return server_id

    host = urlparse(base_url).hostname
    if not host:
        return None

    from sqlalchemy import select

    from app.models.server import Server

    result = await db.execute(select(Server.id).where(Server.host == host))
    row = result.first()
    return row[0] if row else None


# ── Settings ──────────────────────────────────────


@router.get("/settings", response_model=OrchestratorSettingsResponse)
async def get_settings(db: DbSession):
    repo = OrchestratorSettingsRepository(db)
    settings = await repo.get()
    if settings is None:
        settings = await repo.upsert()
        await db.commit()
    return settings


@router.put("/settings", response_model=OrchestratorSettingsResponse)
async def update_settings(data: OrchestratorSettingsUpdate, db: DbSession):
    repo = OrchestratorSettingsRepository(db)
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        return await repo.get()
    return await repo.upsert(**updates)


# ── AI Providers ──────────────────────────────────

# Single source of truth for all supported provider_type values. Keep this in
# sync with backend dispatcher logic (llm_provider.py). The frontend lab/
# orchestrator UI fetches this list via GET /providers/types instead of
# hardcoding the same entries — adding a new provider here makes it appear
# in the UI automatically.
SUPPORTED_PROVIDER_TYPES: list[dict[str, str]] = [
    {"type": "ollama", "label": "Ollama (Local)"},
    {"type": "huggingface", "label": "HuggingFace"},
    {"type": "openai", "label": "OpenAI-Compatible"},
    {"type": "anthropic", "label": "Anthropic (Claude)"},
    {"type": "claude_cli", "label": "Claude CLI"},
    {"type": "openai_cloud", "label": "OpenAI"},
    {"type": "xai", "label": "xAI (Grok)"},
    {"type": "groq", "label": "Groq"},
    {"type": "deepseek", "label": "DeepSeek"},
    {"type": "comfyui", "label": "ComfyUI"},
    {"type": "stt", "label": "Speech-to-Text (Whisper)"},
]
_SUPPORTED_PROVIDER_TYPE_VALUES = {p["type"] for p in SUPPORTED_PROVIDER_TYPES}


@router.get("/providers/types")
async def list_provider_types():
    """Return all provider_type values supported by the backend dispatcher."""
    return {"provider_types": SUPPORTED_PROVIDER_TYPES}


@router.get("/providers", response_model=list[AIProviderResponse])
async def list_providers(db: DbSession):
    from sqlalchemy import select

    from app.models.orchestrator import AIProvider
    from app.models.server import Server

    stmt = (
        select(AIProvider, Server.name.label("server_name"))
        .outerjoin(Server, AIProvider.server_id == Server.id)
        .order_by(AIProvider.name)
    )
    result = await db.execute(stmt)
    rows = result.all()
    providers = []
    for provider, server_name in rows:
        d = AIProviderResponse.model_validate(provider)
        d.server_name = server_name
        providers.append(d)
    return providers


@router.post(
    "/providers",
    response_model=AIProviderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_provider(data: AIProviderCreate, db: DbSession):
    if data.provider_type not in _SUPPORTED_PROVIDER_TYPE_VALUES:
        raise HTTPException(400, f"Unsupported provider_type: {data.provider_type}")
    repo = AIProviderRepository(db)
    server_id = await _infer_provider_server_id(db, data.base_url, data.server_id)
    provider = AIProvider(
        name=data.name,
        provider_type=data.provider_type,
        base_url=data.base_url,
        api_key=data.api_key,
        server_id=server_id,
        is_active=data.is_active,
    )
    return await repo.create(provider)


@router.put("/providers/{provider_id}", response_model=AIProviderResponse)
async def update_provider(provider_id: UUID, data: AIProviderUpdate, db: DbSession):
    repo = AIProviderRepository(db)
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        provider = await repo.get_by_id(provider_id)
        if not provider:
            raise HTTPException(404, "Provider not found")
        return provider
    if "base_url" in updates and "server_id" not in updates:
        provider = await repo.get_by_id(provider_id)
        if not provider:
            raise HTTPException(404, "Provider not found")
        updates["server_id"] = await _infer_provider_server_id(
            db, updates["base_url"], provider.server_id
        )
    result = await repo.update(provider_id, **updates)
    if result is None:
        raise HTTPException(404, "Provider not found")
    return result


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(provider_id: UUID, db: DbSession):
    repo = AIProviderRepository(db)
    if not await repo.delete(provider_id):
        raise HTTPException(404, "Provider not found")


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: UUID, db: DbSession):
    svc = OrchestratorService(db)
    try:
        return await svc.test_provider(provider_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/providers/{provider_id}/approve", response_model=AIProviderResponse)
async def approve_provider(provider_id: UUID, db: DbSession, user: dict = Depends(require_admin)):
    """Approve an auto-discovered AI provider (cluster I).

    Auto-discovered providers from agent metrics ticks are inserted with
    ``pending_approval=True, is_active=False`` so an attacker who learned
    AGENT_SECRET cannot register a provider that immediately serves
    dispatch traffic. Admin approval flips both flags so the engine
    will route to it.
    """
    repo = AIProviderRepository(db)
    provider = await repo.get_by_id(provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    updated = await repo.update(
        provider_id,
        pending_approval=False,
        is_active=True,
    )
    return updated


# ── AI Models ─────────────────────────────────────


@router.get("/models", response_model=list[AIModelResponse])
async def list_models(db: DbSession, provider_id: UUID | None = None):
    repo = AIModelRepository(db)
    return await repo.get_all(provider_id=provider_id)


@router.get("/models/unique")
async def list_unique_models(db: DbSession):
    """Return deduplicated models with per-model server counts.

    Groups by model_identifier and returns one entry per unique model with:
    - total_providers: how many providers host this model
    - available_providers: how many of those are currently available
    - provider_ids: list of provider UUIDs hosting this model
    - server_names: list of server display names
    """
    from sqlalchemy import Integer, case, func, select

    from app.models.orchestrator import AIModel, AIProvider
    from app.models.server import Server

    stmt = (
        select(
            AIModel.model_identifier,
            func.count(AIModel.id).label("total_providers"),
            func.sum(case((AIModel.is_available == True, 1), else_=0)).label("available_providers"),
            func.array_agg(AIModel.id).label("model_ids"),
            func.array_agg(AIModel.provider_id).label("provider_ids"),
            func.array_agg(func.coalesce(Server.name, AIProvider.name)).label("server_names"),
            func.max(AIModel.is_available.cast(Integer)).label("any_available"),
            func.max(AIModel.last_seen_at).label("last_seen_at"),
        )
        .join(AIProvider, AIModel.provider_id == AIProvider.id)
        .outerjoin(Server, AIProvider.server_id == Server.id)
        .group_by(AIModel.model_identifier)
        .order_by(AIModel.model_identifier)
    )
    result = await db.execute(stmt)
    rows = result.all()
    out = []
    for row in rows:
        out.append(
            {
                "model_identifier": row.model_identifier,
                "total_providers": row.total_providers,
                "available_providers": row.available_providers,
                "any_available": bool(row.any_available),
                "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
                "model_ids": [str(mid) for mid in row.model_ids],
                "provider_ids": [str(pid) for pid in row.provider_ids],
                "server_names": list(set(row.server_names)) if row.server_names else [],
            }
        )
    return out


@router.get("/models/live")
async def get_live_models(db: DbSession):
    """Return live models from all providers (Ollama, HuggingFace/vLLM, OpenAI, ComfyUI).

    Returns list of {provider_id, provider_name, provider_type, server, models[]}.
    - Ollama: queried via agent metrics cache or direct curl.
    - HuggingFace/OpenAI: queried via /v1/models endpoint.
    - ComfyUI: queried via /models and /models/<folder>.
    """
    import asyncio
    import json as jsonlib
    import uuid

    import httpx

    from app.websocket.hub import manager

    provider_repo = AIProviderRepository(db)
    all_providers = await provider_repo.get_all()
    all_metrics = manager.get_all_metrics()
    connected = manager.get_connected_agents()
    result = []

    # ── Ollama providers: query agents ────────────
    ollama_providers = [p for p in all_providers if p.provider_type == "ollama"]
    seen_servers = set()

    # 1. Check metrics cache
    for agent_name, metrics in all_metrics.items():
        ollama_models = metrics.get("ollama_models", [])
        if ollama_models:
            # Find the matching provider
            matched_provider = next(
                (
                    p
                    for p in ollama_providers
                    if p.name == agent_name or p.name == f"ollama-{agent_name}"
                ),
                None,
            )
            result.append(
                {
                    "provider_id": str(matched_provider.id) if matched_provider else None,
                    "provider_name": matched_provider.name
                    if matched_provider
                    else f"ollama-{agent_name}",
                    "provider_type": "ollama",
                    "server": agent_name,
                    "models": ollama_models,
                }
            )
            seen_servers.add(agent_name)

    # 2. Direct agent query fallback for unseen agents
    agents_to_query = [a for a in connected if a not in seen_servers]

    async def _ask_ollama(agent_name: str) -> dict | None:
        command_id = str(uuid.uuid4())
        future = manager.create_pending(command_id)
        sent = await manager.send_to_agent(
            agent_name,
            {
                "type": "command.execute",
                "id": command_id,
                "payload": {
                    "command": "curl -s http://localhost:11434/api/tags 2>/dev/null || echo '{}'",
                },
            },
        )
        if not sent:
            return None
        try:
            resp = await asyncio.wait_for(future, timeout=5.0)
            stdout = resp.get("stdout", "")
            if not stdout.strip() or stdout.strip() == "{}":
                return None
            data = jsonlib.loads(stdout)
            models = []
            for m in data.get("models", []):
                details = m.get("details", {})
                models.append(
                    {
                        "name": m.get("name", ""),
                        "model": m.get("model", m.get("name", "")),
                        "size": m.get("size", 0),
                        "parameter_size": details.get("parameter_size", ""),
                        "quantization": details.get("quantization_level", ""),
                        "family": details.get("family", ""),
                        "format": details.get("format", ""),
                        "modified_at": m.get("modified_at", ""),
                    }
                )
            if models:
                matched = next(
                    (
                        p
                        for p in ollama_providers
                        if p.name == agent_name or p.name == f"ollama-{agent_name}"
                    ),
                    None,
                )
                return {
                    "provider_id": str(matched.id) if matched else None,
                    "provider_name": matched.name if matched else f"ollama-{agent_name}",
                    "provider_type": "ollama",
                    "server": agent_name,
                    "models": models,
                }
        except (asyncio.TimeoutError, jsonlib.JSONDecodeError, Exception):
            pass
        return None

    # ── HuggingFace / OpenAI providers: query /v1/models ────────────
    api_providers = [
        p for p in all_providers if p.provider_type in ("huggingface", "openai") and p.is_active
    ]
    comfyui_providers = [p for p in all_providers if p.provider_type == "comfyui" and p.is_active]

    async def _ask_api_provider(provider: AIProvider) -> dict | None:
        try:
            headers = {}
            if provider.api_key:
                headers["Authorization"] = f"Bearer {provider.api_key}"
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{provider.base_url}/v1/models", headers=headers)
                resp.raise_for_status()
                data = resp.json()

            served = data.get("data", [])
            if not served:
                return None

            models = []
            for m in served:
                models.append(
                    {
                        "name": m.get("id", ""),
                        "model": m.get("id", ""),
                        "size": 0,
                        "parameter_size": "",
                        "quantization": "",
                        "family": "",
                        "format": "",
                    }
                )
            # Find server name from server_id
            server_name = provider.name
            return {
                "provider_id": str(provider.id),
                "provider_name": provider.name,
                "provider_type": provider.provider_type,
                "server": server_name,
                "models": models,
            }
        except Exception:
            return None

    async def _ask_comfyui_provider(provider: AIProvider) -> dict | None:
        try:
            models = await discover_comfyui_models(provider.base_url)
            if not models:
                return None

            return {
                "provider_id": str(provider.id),
                "provider_name": provider.name,
                "provider_type": provider.provider_type,
                "server": provider.name,
                "models": [
                    {
                        "name": m.get("name", ""),
                        "model": m.get("identifier", m.get("name", "")),
                        "size": m.get("size", 0),
                        "parameter_size": m.get("parameter_size", ""),
                        "quantization": m.get("quantization", ""),
                        "family": m.get("family", ""),
                        "format": m.get("format", ""),
                    }
                    for m in models
                ],
            }
        except Exception:
            return None

    # Run all queries concurrently
    coros = []
    coros.extend(_ask_ollama(name) for name in agents_to_query)
    coros.extend(_ask_api_provider(p) for p in api_providers)
    coros.extend(_ask_comfyui_provider(p) for p in comfyui_providers)
    if coros:
        results = await asyncio.gather(*coros)
        for r in results:
            if r:
                result.append(r)

    # ── Riffusion providers: use metrics cache ─────────────
    riffusion_providers = [p for p in all_providers if p.provider_type == "riffusion"]
    for agent_name, metrics in all_metrics.items():
        riffusion_models = metrics.get("riffusion_models", [])
        if riffusion_models:
            matched_provider = next(
                (p for p in riffusion_providers if p.name == f"riffusion-{agent_name}"),
                None,
            )
            result.append(
                {
                    "provider_id": str(matched_provider.id) if matched_provider else None,
                    "provider_name": matched_provider.name
                    if matched_provider
                    else f"riffusion-{agent_name}",
                    "provider_type": "riffusion",
                    "server": agent_name,
                    "models": riffusion_models,
                }
            )

    # ── GPU service providers (MusicGen, Bark, RVC, STT): use metrics cache ─────────────
    _GPU_SVC_KEYS = [
        ("musicgen_models", "musicgen"),
        ("bark_models", "bark"),
        ("rvc_models", "rvc"),
        ("stt_models", "stt"),
    ]
    for metrics_key, ptype in _GPU_SVC_KEYS:
        typed_providers = [p for p in all_providers if p.provider_type == ptype]
        for agent_name, metrics in all_metrics.items():
            svc_models = metrics.get(metrics_key, [])
            if svc_models:
                matched = next(
                    (p for p in typed_providers if p.name == f"{ptype}-{agent_name}"),
                    None,
                )
                result.append(
                    {
                        "provider_id": str(matched.id) if matched else None,
                        "provider_name": matched.name if matched else f"{ptype}-{agent_name}",
                        "provider_type": ptype,
                        "server": agent_name,
                        "models": svc_models,
                    }
                )

    # ── Claude CLI wrapper providers: use metrics cache ─────────────
    claude_cli_providers = [p for p in all_providers if p.provider_type == "claude_cli"]
    for agent_name, metrics in all_metrics.items():
        cli_models = metrics.get("claude_cli_models", [])
        if cli_models:
            matched_provider = next(
                (p for p in claude_cli_providers if p.name == f"claude_cli-{agent_name}"),
                None,
            )
            result.append(
                {
                    "provider_id": str(matched_provider.id) if matched_provider else None,
                    "provider_name": matched_provider.name
                    if matched_provider
                    else f"claude_cli-{agent_name}",
                    "provider_type": "claude_cli",
                    "server": agent_name,
                    "models": cli_models,
                }
            )

    # ── Script Runner (ToolAI) providers ─────────────
    all_runners = manager.get_all_script_runners()
    for agent_name, runner_info in all_runners.items():
        scripts = runner_info.get("scripts", [])
        if scripts:
            models = []
            for s in scripts:
                name = s.get("name", "") if isinstance(s, dict) else str(s)
                s.get("description", "") if isinstance(s, dict) else ""
                env = s.get("env", "") if isinstance(s, dict) else ""
                models.append(
                    {
                        "name": name,
                        "model": name,
                        "size": 0,
                        "parameter_size": "",
                        "quantization": env or "script",
                        "family": "audio",
                        "format": "script",
                    }
                )
            result.append(
                {
                    "provider_id": None,
                    "provider_name": f"toolai-{agent_name}",
                    "provider_type": "toolai",
                    "server": agent_name,
                    "models": models,
                }
            )

    return result


@router.post("/models/sync")
async def sync_all_models(db: DbSession):
    """Force-sync models from all live sources into the database.

    Uses the live models endpoint logic (agent commands) to discover models,
    then persists them to the database with auto-created providers.
    """
    import asyncio
    import json as jsonlib
    import uuid as uuid_mod

    import httpx

    from app.models.orchestrator import AIProvider
    from app.repositories.server_repo import ServerRepository
    from app.websocket.hub import manager

    server_repo = ServerRepository(db)
    provider_repo = AIProviderRepository(db)
    model_repo = AIModelRepository(db)
    total_synced = 0
    all_providers = await provider_repo.get_all(active_only=True)

    # Discover models from all connected agents via command execution
    connected = manager.get_connected_agents()
    all_metrics = manager.get_all_metrics()

    async def _discover_agent(agent_name: str) -> tuple[str, list[dict]]:
        # First check metrics cache
        metrics = all_metrics.get(agent_name, {})
        cached = metrics.get("ollama_models", [])
        if cached:
            return agent_name, cached
        # Ask agent to query local Ollama
        command_id = str(uuid_mod.uuid4())
        future = manager.create_pending(command_id)
        sent = await manager.send_to_agent(
            agent_name,
            {
                "type": "command.execute",
                "id": command_id,
                "payload": {
                    "command": "curl -s http://localhost:11434/api/tags 2>/dev/null || echo '{}'",
                },
            },
        )
        if not sent:
            return agent_name, []
        try:
            resp = await asyncio.wait_for(future, timeout=5.0)
            stdout = resp.get("stdout", "")
            if not stdout.strip() or stdout.strip() == "{}":
                return agent_name, []
            data = jsonlib.loads(stdout)
            models = []
            for m in data.get("models", []):
                details = m.get("details", {})
                models.append(
                    {
                        "name": m.get("name", ""),
                        "model": m.get("model", m.get("name", "")),
                        "size": m.get("size", 0),
                        "parameter_size": details.get("parameter_size", ""),
                        "quantization": details.get("quantization_level", ""),
                        "family": details.get("family", ""),
                        "format": details.get("format", ""),
                    }
                )
            return agent_name, models
        except Exception:
            return agent_name, []

    # Discover from all agents concurrently
    tasks = [_discover_agent(name) for name in connected]
    discoveries = await asyncio.gather(*tasks) if tasks else []

    for agent_name, ollama_models in discoveries:
        if not ollama_models:
            continue

        server = await server_repo.get_by_name(agent_name)
        if not server:
            continue

        # Get or create provider
        provider_name = agent_name
        provider = await provider_repo.get_by_name(provider_name)
        # Fallback: check legacy name
        if provider is None:
            provider = await provider_repo.get_by_name(f"ollama-{agent_name}")
            if provider:
                await provider_repo.update(provider.id, name=provider_name)
        if provider is None:
            provider = AIProvider(
                name=provider_name,
                provider_type="ollama",
                base_url=f"http://{server.host}:11434",
                server_id=server.id,
                is_active=True,
            )
            provider = await provider_repo.create(provider)

        # Fetch context_length for each model via /api/show
        ctx_lengths: dict[str, int] = {}

        async def _fetch_ctx(base_url: str, model_name: str):
            try:
                async with httpx.AsyncClient(timeout=5.0) as hc:
                    r = await hc.post(f"{base_url}/api/show", json={"name": model_name})
                    if r.status_code == 200:
                        info = r.json().get("model_info", {})
                        for k, v in info.items():
                            if "context_length" in k and isinstance(v, (int, float)):
                                ctx_lengths[model_name] = int(v)  # noqa: B023 — closure intentionally shares ctx_lengths dict
                                break
            except Exception:
                pass

        ctx_tasks = [
            _fetch_ctx(provider.base_url, m.get("name", m.get("model", "")))
            for m in ollama_models
            if m.get("name") or m.get("model")
        ]
        await asyncio.gather(*ctx_tasks)

        # Upsert models
        seen_ids = []
        for m in ollama_models:
            model_id = m.get("name", m.get("model", ""))
            if not model_id:
                continue
            params = {
                "parameter_size": m.get("parameter_size", ""),
                "quantization": m.get("quantization", ""),
                "size": m.get("size", 0),
            }
            if model_id in ctx_lengths:
                params["context_length"] = ctx_lengths[model_id]
            result = await model_repo.upsert(
                provider_id=provider.id,
                model_identifier=model_id,
                name=model_id,
                capabilities={"family": m.get("family", ""), "format": m.get("format", "")},
                parameters=params,
            )
            seen_ids.append(result.id)
            total_synced += 1

        if seen_ids:
            await model_repo.mark_unavailable(provider.id, seen_ids)

    # ── Also discover vLLM containers from Docker metrics ──

    for agent_name, metrics in all_metrics.items():
        docker_containers = metrics.get("docker_containers", [])
        vllm_containers = [
            c
            for c in docker_containers
            if c.get("state") == "running" and "vllm" in (c.get("image", "") or "").lower()
        ]
        if not vllm_containers:
            continue

        server = await server_repo.get_by_name(agent_name)
        if not server:
            continue

        for container in vllm_containers:
            from app.websocket.agent_handler import _parse_host_port

            host_port = _parse_host_port(container.get("ports", ""), 8000)
            if not host_port:
                continue

            base_url = f"http://{server.host}:{host_port}"
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                    resp = await client.get(f"{base_url}/v1/models")
                    resp.raise_for_status()
                    data = resp.json()
            except Exception:
                continue

            served_models = data.get("data", [])
            if not served_models:
                continue

            model_name = served_models[0].get("id", container.get("name", "vllm"))
            provider_name = f"{model_name}"
            provider = await provider_repo.get_by_name(provider_name)
            if provider is None:
                provider = AIProvider(
                    name=provider_name,
                    provider_type="huggingface",
                    base_url=base_url,
                    server_id=server.id,
                    is_active=True,
                )
                provider = await provider_repo.create(provider)

            seen_ids = []
            for m in served_models:
                mid = m.get("id", "")
                if not mid:
                    continue
                result = await model_repo.upsert(
                    provider_id=provider.id,
                    model_identifier=mid,
                    name=mid,
                    capabilities={"vision": True, "source": "vllm"},
                    parameters={},
                )
                seen_ids.append(result.id)
                total_synced += 1

            if seen_ids:
                await model_repo.mark_unavailable(provider.id, seen_ids)

    # ── Also sync Claude CLI wrapper models from metrics cache ──
    # Reuses the websocket-path sync (own session/commit) so the Sync All
    # button and the 10s metrics tick stay behaviorally identical.
    from app.database import async_session as _cli_session_factory
    from app.websocket.agent_handler import _sync_claude_cli_models

    for agent_name, metrics in all_metrics.items():
        cli_models = metrics.get("claude_cli_models", [])
        if not cli_models:
            continue
        try:
            await _sync_claude_cli_models(
                agent_name,
                cli_models,
                metrics.get("claude_cli_port", 3021),
                _cli_session_factory,
            )
            total_synced += len(cli_models)
        except Exception:
            pass

    # ── Also discover ComfyUI providers directly ──
    for provider in all_providers:
        if provider.provider_type != "comfyui":
            continue

        try:
            comfyui_models = await discover_comfyui_models(provider.base_url)
        except Exception:
            continue

        seen_ids = []
        for m in comfyui_models:
            result = await model_repo.upsert(
                provider_id=provider.id,
                model_identifier=m["identifier"],
                name=m["name"],
                capabilities=m.get("capabilities", {}),
                parameters=m.get("parameters", {}),
            )
            seen_ids.append(result.id)
            total_synced += 1

        if seen_ids:
            await model_repo.mark_unavailable(provider.id, seen_ids)

    await db.commit()
    return {"synced": total_synced}


# ── LLM Events (Load Balancer Activity) ──────────


@router.get("/llm-events")
async def list_llm_events(
    db: DbSession,
    user: dict = Depends(get_current_user),
    limit: int = 100,
    offset: int = 0,
    model: str | None = None,
    server: str | None = None,
    lab_id: UUID | None = None,
    conversation_id: UUID | None = None,
    event_type: str | None = None,
    since: str | None = None,
):
    """Return recent LLM events for the load-balancer activity feed.

    Non-admin callers only see events tied to a lab or conversation they
    own / edit / view via ACL. Admin sees everything.
    """
    from datetime import datetime as dt

    from sqlalchemy import desc, or_, select

    from app.models.orchestrator import Lab, LlmEvent

    q = (
        select(LlmEvent, Lab.name.label("lab_name"))
        .outerjoin(Lab, LlmEvent.lab_id == Lab.id)
        .order_by(desc(LlmEvent.created_at))
    )
    if model:
        q = q.where(LlmEvent.model_identifier == model)
    if server:
        q = q.where(LlmEvent.server_name == server)
    if lab_id:
        q = q.where(LlmEvent.lab_id == lab_id)
    if conversation_id:
        q = q.where(LlmEvent.conversation_id == conversation_id)
    if event_type:
        q = q.where(LlmEvent.event_type == event_type)
    if since:
        from datetime import timedelta, timezone

        period_map = {
            "1h": timedelta(hours=1),
            "1d": timedelta(days=1),
            "1w": timedelta(weeks=1),
            "1m": timedelta(days=30),
            "1y": timedelta(days=365),
        }
        if since in period_map:
            q = q.where(LlmEvent.created_at >= dt.now(timezone.utc) - period_map[since])
        else:
            try:
                since_dt = dt.fromisoformat(since)
                q = q.where(LlmEvent.created_at >= since_dt)
            except ValueError:
                pass

    if user.get("role") != "admin":
        # Restrict to events whose lab or conversation the user can VIEW.
        # Events with neither (system-level) are admin-only.
        visible_labs = filter_query_by_access(select(Lab.id), Lab, user).subquery()
        visible_convs = filter_query_by_access(
            select(Conversation.id), Conversation, user
        ).subquery()
        q = q.where(
            or_(
                LlmEvent.lab_id.in_(select(visible_labs)),
                LlmEvent.conversation_id.in_(select(visible_convs)),
            )
        )

    q = q.offset(offset).limit(limit)
    result = await db.execute(q)
    rows = result.all()
    return [
        {
            "id": str(r.LlmEvent.id),
            "request_id": str(r.LlmEvent.request_id) if r.LlmEvent.request_id else None,
            "event_type": r.LlmEvent.event_type,
            "model_identifier": r.LlmEvent.model_identifier,
            "provider_name": r.LlmEvent.provider_name,
            "server_name": r.LlmEvent.server_name,
            "caller_type": r.LlmEvent.caller_type,
            "caller_name": r.LlmEvent.caller_name,
            "lab_id": str(r.LlmEvent.lab_id) if r.LlmEvent.lab_id else None,
            "lab_name": r.lab_name,
            "conversation_id": str(r.LlmEvent.conversation_id)
            if r.LlmEvent.conversation_id
            else None,
            "tokens_in": r.LlmEvent.tokens_in,
            "tokens_out": r.LlmEvent.tokens_out,
            "duration_ms": r.LlmEvent.duration_ms,
            "attempt": r.LlmEvent.attempt,
            "max_attempts": r.LlmEvent.max_attempts,
            "error": r.LlmEvent.error,
            "has_input": r.LlmEvent.input_messages is not None,
            "has_output": r.LlmEvent.output_content is not None,
            "created_at": r.LlmEvent.created_at.isoformat() if r.LlmEvent.created_at else None,
        }
        for r in rows
    ]


@router.get("/llm-events/stats")
async def llm_event_stats(
    db: DbSession,
    user: dict = Depends(get_current_user),
    period: str = "1h",
    model: str | None = None,
    server: str | None = None,
    lab_id: UUID | None = None,
    status: str | None = None,
):
    """Return aggregated LLM event statistics for charts.

    period: '1h' | '1d' | '1w' | '1m' | '1y' | 'all'
    Summary counts unique requests (by request_id or fallback to queue events).
    - total: number of unique requests
    - succeeded: requests that got a 'response' event
    - failed: requests that got a 'failed' event with no subsequent response
    - queued: requests currently waiting (queue event without response/failed)

    Non-admin callers only see events tied to a lab or conversation they own /
    edit / view via ACL.
    """
    from datetime import datetime as dt
    from datetime import timedelta, timezone

    from sqlalchemy import text

    period_map = {
        "1h": timedelta(hours=1),
        "1d": timedelta(days=1),
        "1w": timedelta(weeks=1),
        "1m": timedelta(days=30),
        "1y": timedelta(days=365),
        "all": timedelta(days=36500),
    }
    delta = period_map.get(period, timedelta(hours=1))
    since = dt.now(timezone.utc) - delta

    # Build optional WHERE clauses for raw SQL
    extra_where = ""
    params = {"since": since}
    if model:
        extra_where += " AND model_identifier = :model"
        params["model"] = model
    if server:
        extra_where += " AND server_name = :server"
        params["server"] = server
    if lab_id:
        extra_where += " AND lab_id = :lab_id"
        params["lab_id"] = str(lab_id)
    if user.get("role") != "admin":
        # Same visibility rule as /llm-events: a lab or conversation the user
        # can VIEW must own the event. Events with neither stay admin-only.
        extra_where += (
            " AND ("
            "(lab_id IS NOT NULL AND lab_id IN ("
            "  SELECT id FROM labs"
            "   WHERE acl->>'owner' = :acl_email"
            "      OR acl->'editors' ? :acl_email"
            "      OR acl->'viewers' ? :acl_email))"
            " OR (conversation_id IS NOT NULL AND conversation_id IN ("
            "  SELECT id FROM conversations"
            "   WHERE acl->>'owner' = :acl_email"
            "      OR acl->'editors' ? :acl_email"
            "      OR acl->'viewers' ? :acl_email))"
            ")"
        )
        params["acl_email"] = user.get("sub", "")

    # Summary: for events WITH request_id, group by request_id to determine status.
    # For legacy events (no request_id), count response/failed events directly.
    # "Queued" only makes sense for events with request_id (legacy events are all completed).
    summary_q = text(f"""
        WITH
        -- New events (have request_id): group by request_id
        new_requests AS (
            SELECT
                request_id AS req_id,
                bool_or(event_type = 'response') AS has_response,
                bool_or(event_type = 'failed') AS has_failed
            FROM llm_events
            WHERE created_at >= :since AND request_id IS NOT NULL {extra_where}
            GROUP BY request_id
        ),
        -- Legacy events (no request_id): count terminal events directly
        legacy AS (
            SELECT
                COUNT(*) FILTER (WHERE event_type = 'response') AS succeeded,
                COUNT(*) FILTER (WHERE event_type = 'failed') AS failed
            FROM llm_events
            WHERE created_at >= :since AND request_id IS NULL {extra_where}
        )
        SELECT
            (SELECT COUNT(*) FROM new_requests) + (SELECT succeeded + failed FROM legacy) AS total,
            (SELECT COUNT(*) FILTER (WHERE has_response) FROM new_requests) + (SELECT succeeded FROM legacy) AS succeeded,
            (SELECT COUNT(*) FILTER (WHERE has_failed AND NOT has_response) FROM new_requests) + (SELECT failed FROM legacy) AS failed,
            (SELECT COUNT(*) FILTER (WHERE NOT has_response AND NOT has_failed) FROM new_requests) AS queued
    """)
    sr = (await db.execute(summary_q, params)).first()

    # By model — count terminal events (response/failed) per model
    by_model_q = text(f"""
        SELECT
            model_identifier AS model,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE event_type = 'response') AS succeeded,
            COUNT(*) FILTER (WHERE event_type = 'failed') AS failed
        FROM llm_events
        WHERE created_at >= :since AND event_type IN ('response', 'failed') {extra_where}
        GROUP BY model_identifier
        ORDER BY total DESC
    """)
    by_model = [
        {"model": r.model, "total": r.total, "succeeded": r.succeeded, "failed": r.failed}
        for r in (await db.execute(by_model_q, params)).all()
    ]

    # By server — count terminal events (response/failed) per server
    by_server_q = text(f"""
        SELECT
            server_name AS server,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE event_type = 'response') AS succeeded,
            COUNT(*) FILTER (WHERE event_type = 'failed') AS failed
        FROM llm_events
        WHERE created_at >= :since AND event_type IN ('response', 'failed') AND server_name IS NOT NULL {extra_where}
        GROUP BY server_name
        ORDER BY total DESC
    """)
    by_server = [
        {"server": r.server, "total": r.total, "succeeded": r.succeeded, "failed": r.failed}
        for r in (await db.execute(by_server_q, params)).all()
    ]

    # Timeline (bucketed by time period)
    step_map = {
        "1h": "5 minutes",
        "1d": "1 hour",
        "1w": "6 hours",
        "1m": "1 day",
        "1y": "1 week",
        "all": "1 week",
    }
    step = step_map.get(period, "5 minutes")
    timeline_q = text(f"""
        SELECT
            date_trunc('minute', created_at) - (EXTRACT(minute FROM created_at)::int % {_step_minutes(step)}) * interval '1 minute' AS bucket,
            COUNT(*) FILTER (WHERE event_type = 'response') AS succeeded,
            COUNT(*) FILTER (WHERE event_type = 'failed') AS failed,
            COUNT(*) FILTER (WHERE event_type = 'dispatch') AS dispatched
        FROM llm_events
        WHERE created_at >= :since {extra_where}
        GROUP BY bucket
        ORDER BY bucket
    """)
    timeline_result = await db.execute(timeline_q, params)
    timeline = [
        {
            "time": r.bucket.isoformat(),
            "succeeded": r.succeeded,
            "failed": r.failed,
            "dispatched": r.dispatched,
        }
        for r in timeline_result.all()
    ]

    return {
        "summary": {
            "total": sr.total or 0,
            "succeeded": sr.succeeded or 0,
            "failed": sr.failed or 0,
            "queued": sr.queued or 0,
        },
        "by_model": by_model,
        "by_server": by_server,
        "timeline": timeline,
    }


def _step_minutes(step: str) -> int:
    """Convert step string to minutes for bucket rounding."""
    if "minute" in step:
        return int(step.split()[0])
    elif "hour" in step:
        return int(step.split()[0]) * 60
    elif "day" in step:
        return int(step.split()[0]) * 1440
    elif "week" in step:
        return int(step.split()[0]) * 10080
    return 5


@router.get("/llm-events/{event_id}")
async def get_llm_event_detail(
    event_id: UUID,
    db: DbSession,
    user: dict = Depends(get_current_user),
):
    """Return a single LLM event with full input_messages and output_content.

    Non-admin callers must have VIEW on the event's lab or conversation.
    """
    from sqlalchemy import select

    from app.models.orchestrator import Lab, LlmEvent
    from app.services.authorization import Permission, check_permission

    q = (
        select(LlmEvent, Lab.name.label("lab_name"))
        .outerjoin(Lab, LlmEvent.lab_id == Lab.id)
        .where(LlmEvent.id == event_id)
    )
    result = await db.execute(q)
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Event not found")
    ev = row.LlmEvent

    # Authorize non-admin via lab or conversation ACL.
    if user.get("role") != "admin":
        allowed = False
        if ev.lab_id is not None:
            lab = (await db.execute(select(Lab).where(Lab.id == ev.lab_id))).scalar_one_or_none()
            if lab is not None:
                try:
                    check_permission(user, lab.acl, Permission.VIEW)
                    allowed = True
                except HTTPException:
                    pass
        if not allowed and ev.conversation_id is not None:
            conv = (
                await db.execute(select(Conversation).where(Conversation.id == ev.conversation_id))
            ).scalar_one_or_none()
            if conv is not None:
                try:
                    check_permission(user, conv.acl, Permission.VIEW)
                    allowed = True
                except HTTPException:
                    pass
        if not allowed:
            raise HTTPException(status_code=404, detail="Event not found")
    return {
        "id": str(ev.id),
        "request_id": str(ev.request_id) if ev.request_id else None,
        "event_type": ev.event_type,
        "model_identifier": ev.model_identifier,
        "provider_name": ev.provider_name,
        "server_name": ev.server_name,
        "caller_type": ev.caller_type,
        "caller_name": ev.caller_name,
        "lab_id": str(ev.lab_id) if ev.lab_id else None,
        "lab_name": row.lab_name,
        "conversation_id": str(ev.conversation_id) if ev.conversation_id else None,
        "tokens_in": ev.tokens_in,
        "tokens_out": ev.tokens_out,
        "duration_ms": ev.duration_ms,
        "attempt": ev.attempt,
        "max_attempts": ev.max_attempts,
        "error": ev.error,
        "input_messages": ev.input_messages,
        "output_content": ev.output_content,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }


# ── AI Agents ─────────────────────────────────────


@router.get("/agents", response_model=list[AIAgentResponse])
async def list_agents(db: DbSession):
    repo = AIAgentRepository(db)
    return await repo.get_all()


@router.post(
    "/agents",
    response_model=AIAgentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent(data: AIAgentCreate, db: DbSession):
    repo = AIAgentRepository(db)
    agent = AIAgent(
        name=data.name,
        description=data.description,
        system_prompt=data.system_prompt,
        model_id=data.model_id,
        temperature=data.temperature,
        max_tokens=data.max_tokens,
        tools=data.tools,
        is_active=data.is_active,
    )
    return await repo.create(agent)


@router.put("/agents/{agent_id}", response_model=AIAgentResponse)
async def update_agent(agent_id: UUID, data: AIAgentUpdate, db: DbSession):
    repo = AIAgentRepository(db)
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        agent = await repo.get_by_id(agent_id)
        if not agent:
            raise HTTPException(404, "Agent not found")
        return agent
    result = await repo.update(agent_id, **updates)
    if result is None:
        raise HTTPException(404, "Agent not found")
    return result


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: UUID, db: DbSession):
    repo = AIAgentRepository(db)
    if not await repo.delete(agent_id):
        raise HTTPException(404, "Agent not found")


# ── Conversations ─────────────────────────────────


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    db: DbSession, conv_status: str | None = None, user: dict = Depends(get_current_user)
):
    svc = ConversationService(db)
    return await svc.list_conversations(status=conv_status, user=user)


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    data: ConversationCreate, db: DbSession, user: dict = Depends(get_current_user)
):
    svc = ConversationService(db)
    conv = await svc.create_conversation(data, user=user)
    return {
        "id": conv.id,
        "title": conv.title,
        "status": conv.status,
        "agent_id": conv.agent_id,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
        "last_message": None,
        "message_count": 0,
    }


@router.get("/conversations/{conv_id}", response_model=ConversationResponse)
async def get_conversation(conv_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    svc = ConversationService(db)
    conv = await svc.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    check_permission(user, conv.acl, Permission.VIEW)
    return conv


@router.put("/conversations/{conv_id}", response_model=ConversationResponse)
async def update_conversation(
    conv_id: UUID, data: ConversationUpdate, db: DbSession, user: dict = Depends(get_current_user)
):
    svc = ConversationService(db)
    conv = await svc.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    check_permission(user, conv.acl, Permission.EDIT)
    conv = await svc.update_conversation(conv_id, data)
    return conv


@router.delete("/conversations/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conv_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    svc = ConversationService(db)
    conv = await svc.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    check_permission(user, conv.acl, Permission.DELETE)
    await svc.delete_conversation(conv_id)


# ── Messages ──────────────────────────────────────


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageResponse])
async def get_messages(
    conv_id: UUID, db: DbSession, limit: int = 200, user: dict = Depends(get_current_user)
):
    svc = ConversationService(db)
    conv = await svc.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    check_permission(user, conv.acl, Permission.VIEW)
    return await svc.get_messages(conv_id, limit=limit)


@router.post("/conversations/{conv_id}/messages")
async def send_message(
    conv_id: UUID, data: MessageCreate, db: DbSession, user: dict = Depends(get_current_user)
):
    """Send a user message and stream the orchestrator's response via SSE."""
    svc = ConversationService(db)
    conv = await svc.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    check_permission(user, conv.acl, Permission.EDIT)

    # Resolve agent: per-message override > conversation default
    agent_id = data.agent_id or conv.agent_id

    # Resolve ad-hoc tools: per-message override > conversation default
    adhoc_tools = data.tools or (conv.tools if conv.tools else None)

    orch = OrchestratorService(db)
    return StreamingResponse(
        orch.process_message(
            conv_id,
            data.content,
            model_override=data.model,
            images=data.images,
            context_mode=data.context_mode,
            agent_id=agent_id,
            adhoc_tools=adhoc_tools,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Tasks / Activity ─────────────────────────────


@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    db: DbSession,
    conversation_id: UUID | None = None,
    limit: int = 50,
):
    svc = TaskQueueService(db)
    return await svc.get_tasks(conversation_id=conversation_id, limit=limit)


@router.get("/activity")
async def get_activity(
    db: DbSession,
    user: dict = Depends(get_current_user),
    conversation_id: UUID | None = None,
    limit: int = 100,
):
    """Combined activity feed of messages + tasks.

    Non-admin callers only see entries from conversations they own / edit /
    view via ACL. Admin sees everything (or, when ``conversation_id`` is
    specified, just that conversation).
    """
    from sqlalchemy import select

    from app.models.orchestrator import Message, OrchestratorTask

    is_admin = user.get("role") == "admin"

    # Resolve which conversations the user is allowed to see.
    restrict_conv_ids: set[UUID] | None = None
    if not is_admin:
        conv_q = filter_query_by_access(select(Conversation.id), Conversation, user)
        if conversation_id:
            conv_q = conv_q.where(Conversation.id == conversation_id)
        rows = (await db.execute(conv_q)).all()
        restrict_conv_ids = {r[0] for r in rows}
        if not restrict_conv_ids:
            return []

    items: list[dict] = []

    # Tasks
    task_q = select(OrchestratorTask).order_by(OrchestratorTask.queued_at.desc()).limit(limit)
    if conversation_id:
        task_q = task_q.where(OrchestratorTask.conversation_id == conversation_id)
    if restrict_conv_ids is not None:
        task_q = task_q.where(OrchestratorTask.conversation_id.in_(restrict_conv_ids))
    tasks = (await db.execute(task_q)).scalars().all()
    for t in tasks:
        items.append(
            {
                "id": str(t.id),
                "type": "task",
                "conversation_id": str(t.conversation_id),
                "timestamp": (t.started_at or t.queued_at).isoformat(),
                "task_type": t.task_type,
                "task_status": t.status,
                "task_error": t.error,
            }
        )

    # Messages
    msg_q = select(Message).order_by(Message.created_at.desc()).limit(limit)
    if conversation_id:
        msg_q = msg_q.where(Message.conversation_id == conversation_id)
    if restrict_conv_ids is not None:
        msg_q = msg_q.where(Message.conversation_id.in_(restrict_conv_ids))
    messages = (await db.execute(msg_q)).scalars().all()
    for m in messages:
        items.append(
            {
                "id": str(m.id),
                "type": "message",
                "conversation_id": str(m.conversation_id),
                "timestamp": m.created_at.isoformat(),
                "role": m.role,
                "content": (m.content[:200] + "...") if len(m.content) > 200 else m.content,
                "agent_name": m.agent_name,
            }
        )

    # Sort by timestamp descending
    items.sort(key=lambda x: x["timestamp"], reverse=True)
    return items[:limit]


# ── Pipelines ─────────────────────────────────────


@router.get("/builtin-tools")
async def list_builtin_tools():
    """Return all registered builtin tools with their descriptions.

    Each tool has: name, description, and optionally expandable (bool)
    or subTools (list of sub-actions for tools like mail/twitter).
    """
    from app.services.tools import BUILTIN_TOOLS
    from app.services.tools.mcp_registry import MCP_TOOL_META

    # Tools that have sub-action patterns (action parameter with fixed options)
    SUB_ACTION_TOOLS = {
        "mail": [
            {"name": "read", "desc": "Read emails from inbox"},
            {"name": "send", "desc": "Send emails via SMTP"},
        ],
        "twitter": [
            {"name": "read", "desc": "Read timeline/mentions"},
            {"name": "post", "desc": "Post tweets"},
        ],
        "media_post": [
            {"name": "x", "desc": "Post to X (Twitter)"},
            {"name": "linkedin", "desc": "Post to LinkedIn"},
            {"name": "instagram", "desc": "Post to Instagram"},
            {"name": "facebook", "desc": "Post to Facebook"},
        ],
        "youtube": [
            {"name": "download_audio", "desc": "Download YouTube audio"},
            {"name": "list_channel", "desc": "List channel videos"},
        ],
        "trading": [
            {"name": "list_wallets", "desc": "List hot wallets"},
            {"name": "wallet_balance", "desc": "Native + token balances"},
            {"name": "gas_price", "desc": "Current gas price"},
            {"name": "token_allowance", "desc": "Check ERC-20 allowance"},
            {"name": "quote", "desc": "DEX swap quote"},
            {"name": "send_native", "desc": "Send ETH/BNB"},
            {"name": "send_token", "desc": "Transfer ERC-20 tokens"},
            {"name": "approve_token", "desc": "Approve DEX spending"},
            {"name": "swap", "desc": "Execute DEX swap"},
            {"name": "open_position", "desc": "Record trading position"},
            {"name": "close_position", "desc": "Close open position"},
            {"name": "list_positions", "desc": "View positions with P&L"},
            {"name": "trade_history", "desc": "Recent executed trades"},
            {"name": "portfolio_pnl", "desc": "Aggregate portfolio P&L"},
        ],
        "defi_data": [
            {"name": "prices", "desc": "Token prices (CoinGecko)"},
            {"name": "token_search", "desc": "Search tokens by name"},
            {"name": "protocol_tvl", "desc": "Protocol TVL (DeFiLlama)"},
            {"name": "chain_tvl", "desc": "Chain TVL rankings"},
            {"name": "yields", "desc": "Yield pools by chain/APY"},
            {"name": "dex_pair", "desc": "DEX pair data"},
            {"name": "dex_search", "desc": "Search DEX pairs"},
            {"name": "gas_tracker", "desc": "Gas prices across chains"},
        ],
        "web3_portfolio": [
            {"name": "list_addresses", "desc": "List tracked addresses granted to the lab"},
            {"name": "wallet_balances", "desc": "Balances for one tracked wallet"},
            {
                "name": "wallet_transactions",
                "desc": "Transactions and transfers for one tracked wallet",
            },
            {"name": "portfolio_total", "desc": "Aggregate value across the lab's tracked wallets"},
            {
                "name": "portfolio_history",
                "desc": "Historical snapshots for one or all granted tracked wallets",
            },
        ],
    }

    result = []
    # MCP tools are grouped per-server into one synthetic expandable entry
    # named ``mcp:<slug>`` (reusing the SubToolGroup picker exactly like
    # mail/twitter). They are collected here and appended after the flat tools.
    mcp_groups: dict[str, dict] = {}

    for name, schema in sorted(BUILTIN_TOOLS.items()):
        meta = MCP_TOOL_META.get(name)
        if meta:
            slug = meta["server_slug"]
            group = mcp_groups.setdefault(
                slug,
                {
                    "name": f"mcp:{slug}",
                    "description": f"MCP · {meta['server_name']}",
                    "mcp": True,
                    "subTools": [],
                },
            )
            group["subTools"].append({"name": meta["tool"], "desc": schema.get("description", "")})
            continue

        entry = {
            "name": name,
            "description": schema.get("description", ""),
        }
        if schema.get("sensitive"):
            entry["sensitive"] = True
            entry["sensitive_reason"] = schema.get(
                "sensitive_reason",
                "This tool can perform real, hard-to-reverse actions on external accounts or assets.",
            )
        if name == "media_pipeline":
            entry["expandable"] = True
        elif name in SUB_ACTION_TOOLS:
            entry["subTools"] = SUB_ACTION_TOOLS[name]
        result.append(entry)

    # Append MCP server groups (sorted by server name for stable ordering).
    result.extend(sorted(mcp_groups.values(), key=lambda g: g["description"]))
    return result


@router.get("/pipelines")
async def list_pipelines(db: DbSession):
    """Return registered media pipelines and whether each has an active provider."""
    from sqlalchemy import select

    from app.models.orchestrator import AIProvider
    from app.services.pipelines import get_available_pipelines

    pipelines = get_available_pipelines()

    # Fetch active provider types to check which pipelines are configured
    result = await db.execute(select(AIProvider.provider_type).where(AIProvider.is_active == True))
    active_types = {row[0] for row in result.all()}

    for p in pipelines:
        p["has_provider"] = p["name"] in active_types

    return pipelines
