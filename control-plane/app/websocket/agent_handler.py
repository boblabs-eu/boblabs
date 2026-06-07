"""Bob Manager — Agent WebSocket handler.

Handles the agent-side WebSocket protocol on the control plane.
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect

from app.config import settings
from app.websocket.hub import manager

logger = logging.getLogger(__name__)


async def handle_agent_connection(ws: WebSocket, db_session_factory) -> None:
    """Handle an incoming agent WebSocket connection.

    Protocol:
    1. Agent connects and sends `agent.register` with token + system info.
    2. Control plane validates token.
    3. Bidirectional message exchange.
    """
    await ws.accept()
    agent_name: str | None = None

    try:
        # Wait for registration message
        raw = await ws.receive_json()
        logger.debug("Agent raw registration: type=%s name=%s", raw.get("type"), raw.get("payload", {}).get("name"))
        if raw.get("type") != "agent.register":
            await ws.close(code=4001, reason="Expected agent.register")
            return

        payload = raw.get("payload", {})
        token = payload.get("token")

        # Validate agent token
        if token != settings.agent_secret:
            logger.warning("Agent registration rejected: invalid token from %s", payload.get("name", "unknown"))
            await ws.close(code=4003, reason="Invalid agent token")
            return

        agent_name = payload.get("name", "unknown")

        # Register agent in hub
        await manager.register_agent(agent_name, ws)

        agent_ver = payload.get("agent_version", "unknown")
        logger.info("Agent %s connected (agent v%s)", agent_name, agent_ver)

        # Register / update in database
        async with db_session_factory() as db:
            from app.repositories.server_repo import ServerRepository

            repo = ServerRepository(db)
            server = await repo.get_by_name(agent_name)
            now = datetime.now(timezone.utc)

            os_info = {**payload.get("os_info", {}), "agent_version": agent_ver}

            if server is None:
                # Auto-register new agent
                from app.models.server import Server

                server = Server(
                    name=agent_name,
                    host=payload.get("host", "unknown"),
                    port=payload.get("port", 9100),
                    status="online",
                    os_info=os_info,
                    gpu_info=payload.get("gpu_info", {}),
                    last_heartbeat=now,
                )
                await repo.create(server)
                logger.info("Auto-registered new agent: %s", agent_name)
            else:
                await repo.update(
                    server.id,
                    status="online",
                    os_info=os_info,
                    gpu_info=payload.get("gpu_info", {}),
                    last_heartbeat=now,
                )
            await db.commit()

        # Send ack
        await ws.send_json({"type": "register.ack", "payload": {"status": "ok"}})

        # Cache script runner info if agent has one
        script_runner = payload.get("script_runner")
        if script_runner and script_runner.get("scripts"):
            manager.update_script_runner(
                agent_name,
                host=payload.get("host", "unknown"),
                port=script_runner.get("port", 9101),
                scripts=script_runner["scripts"],
            )
            logger.info(
                "Agent %s registered %d script(s) via script runner",
                agent_name, len(script_runner["scripts"]),
            )

        # Broadcast status to UI clients
        await manager.broadcast_to_clients({
            "type": "server.status",
            "payload": {"name": agent_name, "status": "online"},
        })

        # Main message loop
        while True:
            data = await ws.receive_json()
            await _dispatch_agent_message(agent_name, data, db_session_factory)

    except WebSocketDisconnect:
        logger.info("Agent %s disconnected", agent_name)
    except Exception as e:
        logger.error("Agent connection error (%s): %s", agent_name, e, exc_info=True)
    finally:
        if agent_name:
            await manager.unregister_agent(agent_name)
            manager.clear_script_runner(agent_name)

            # Mark server offline
            try:
                async with db_session_factory() as db:
                    from app.repositories.server_repo import ServerRepository
                    from app.repositories.orchestrator_repo import AIModelRepository

                    repo = ServerRepository(db)
                    server = await repo.get_by_name(agent_name)
                    if server:
                        await repo.update(server.id, status="offline")
                        # Mark all models from this server's providers as unavailable
                        model_repo = AIModelRepository(db)
                        await model_repo.mark_all_unavailable_for_server(server.id)
                    await db.commit()
            except Exception:
                pass

            await manager.broadcast_to_clients({
                "type": "server.status",
                "payload": {"name": agent_name, "status": "offline"},
            })


async def _dispatch_agent_message(
    agent_name: str, data: dict, db_session_factory
) -> None:
    """Route incoming agent messages to appropriate handlers."""
    msg_type = data.get("type", "")
    payload = data.get("payload", {})

    if msg_type == "agent.heartbeat":
        async with db_session_factory() as db:
            from app.repositories.server_repo import ServerRepository

            repo = ServerRepository(db)
            server = await repo.get_by_name(agent_name)
            if server:
                await repo.update(
                    server.id, last_heartbeat=datetime.now(timezone.utc), status="online"
                )
            await db.commit()

    elif msg_type == "agent.metrics":
        manager.update_metrics(agent_name, payload)
        # Forward to UI
        await manager.broadcast_to_clients({
            "type": "metrics.update",
            "payload": {"server": agent_name, "metrics": payload},
        })
        # Auto-sync Ollama models to DB if present
        ollama_models = payload.get("ollama_models", [])
        if ollama_models:
            try:
                await _sync_ollama_models(agent_name, ollama_models, db_session_factory)
            except Exception as e:
                logger.warning("Failed to sync Ollama models for %s: %s", agent_name, e)

        # Auto-discover vLLM/HuggingFace containers
        docker_containers = payload.get("docker_containers", [])
        if docker_containers:
            try:
                await _sync_vllm_containers(agent_name, docker_containers, db_session_factory)
            except Exception as e:
                logger.warning("Failed to sync vLLM containers for %s: %s", agent_name, e)

        # Auto-discover ComfyUI containers (auto-creates and auto-reactivates).
        # Two code paths, OR'd together so either deployment style works:
        #  - probe of port 8188 on the agent (covers host-process ComfyUI),
        #  - scan of docker_containers (covers dockerized ComfyUI on agents
        #    that ship ComfyUI as a container with "comfy" in the image name).
        # The probe is preferred because it has zero dependency on docker
        # permissions or image naming convention.
        comfyui_status = payload.get("comfyui_status")
        if comfyui_status and comfyui_status.get("alive"):
            try:
                await _sync_comfyui_from_probe(agent_name, comfyui_status, db_session_factory)
            except Exception as e:
                logger.warning("Failed to sync ComfyUI probe for %s: %s", agent_name, e)
        elif docker_containers:
            try:
                await _sync_comfyui_containers(agent_name, docker_containers, db_session_factory)
            except Exception as e:
                logger.warning("Failed to sync ComfyUI containers for %s: %s", agent_name, e)

        # Update script runner cache
        script_runner_scripts = payload.get("script_runner_scripts", [])
        if script_runner_scripts:
            existing = manager.get_all_script_runners().get(agent_name)
            host = existing["host"] if existing else payload.get("agent_host", "unknown")
            port = existing["port"] if existing else payload.get("script_runner_port", 9101)
            manager.update_script_runner(
                agent_name,
                host=host,
                port=port,
                scripts=script_runner_scripts,
            )
            if not existing:
                logger.info(
                    "Agent %s registered %d script(s) via metrics update",
                    agent_name, len(script_runner_scripts),
                )

        # Auto-sync Riffusion models to DB if present
        riffusion_models = payload.get("riffusion_models", [])
        if riffusion_models:
            try:
                await _sync_riffusion_models(agent_name, riffusion_models, db_session_factory)
            except Exception as e:
                logger.warning("Failed to sync Riffusion models for %s: %s", agent_name, e)

        # Auto-sync GPU service providers (MusicGen, Bark, RVC, CoquiTTS)
        _GPU_SERVICES = [
            ("musicgen_models", "musicgen", 3014),
            ("bark_models", "bark", 3015),
            ("rvc_models", "rvc", 3016),
            ("coqui_tts_models", "coqui_tts", 3017),
            ("stt_models", "stt", 7865),
            ("ltx_video_models", "ltx_video", 3018),
            ("wan_video_models", "wan_video", 3019),
        ]
        for metrics_key, provider_type, default_port in _GPU_SERVICES:
            svc_models = payload.get(metrics_key, [])
            if svc_models:
                try:
                    await _sync_gpu_service_models(
                        agent_name, provider_type, default_port, svc_models, db_session_factory
                    )
                except Exception as e:
                    logger.warning("Failed to sync %s models for %s: %s", provider_type, agent_name, e)

    elif msg_type == "agent.command.output":
        # Stream to UI
        await manager.broadcast_to_clients({
            "type": "command.output",
            "payload": {
                "server": agent_name,
                "command_id": data.get("id"),
                **payload,
            },
        })

    elif msg_type == "agent.command.complete":
        # Resolve pending future
        command_id = data.get("id", "")
        manager.resolve_pending(command_id, payload)
        await manager.broadcast_to_clients({
            "type": "command.complete",
            "payload": {
                "server": agent_name,
                "command_id": command_id,
                **payload,
            },
        })

    elif msg_type == "agent.inspection.result":
        await manager.broadcast_to_clients({
            "type": "inspection.result",
            "payload": {"server": agent_name, **payload},
        })
        # Resolve if there's a pending request
        req_id = data.get("id", "")
        if req_id:
            manager.resolve_pending(req_id, payload)

    elif msg_type == "agent.ai.models":
        # AI model discovery response from agent
        req_id = data.get("id", "")
        if req_id:
            manager.resolve_pending(req_id, payload)
        await manager.broadcast_to_clients({
            "type": "ai.models.update",
            "payload": {"server": agent_name, "models": payload.get("models", [])},
        })

    elif msg_type == "agent.script.result":
        # Script execution result from agent
        req_id = data.get("id", "")
        if req_id:
            manager.resolve_pending(req_id, payload)

    elif msg_type == "agent.terminal.opened":
        session_id = data.get("id", "")
        mapping = manager.get_terminal_mapping(session_id)
        if mapping:
            if mapping["client_id"] == "__tool__":
                # Tool-driven session — put event into queue
                q = manager.get_tool_terminal_queue(session_id)
                if q:
                    await q.put({"type": "opened"})
            else:
                await manager.send_to_client(mapping["client_id"], {
                    "type": "terminal.opened",
                    "payload": {"session_id": session_id},
                })

    elif msg_type == "agent.terminal.output":
        session_id = data.get("id", "")
        mapping = manager.get_terminal_mapping(session_id)
        if mapping:
            if mapping["client_id"] == "__tool__":
                # Tool-driven session — put output into queue
                q = manager.get_tool_terminal_queue(session_id)
                if q:
                    await q.put({"type": "output", "data": payload.get("data", "")})
            else:
                await manager.send_to_client(mapping["client_id"], {
                    "type": "terminal.output",
                    "payload": {
                        "session_id": session_id,
                        "data": payload.get("data", ""),
                    },
                })

    else:
        logger.warning("Unknown message type from %s: %s", agent_name, msg_type)


async def _sync_ollama_models(
    agent_name: str, ollama_models: list[dict], db_session_factory
) -> None:
    """Auto-create an Ollama provider for this agent (if needed) and sync models."""
    async with db_session_factory() as db:
        from app.repositories.server_repo import ServerRepository
        from app.repositories.orchestrator_repo import AIProviderRepository, AIModelRepository
        from app.models.orchestrator import AIProvider

        server_repo = ServerRepository(db)
        server = await server_repo.get_by_name(agent_name)
        if not server:
            return

        provider_repo = AIProviderRepository(db)
        provider_name = agent_name
        provider = await provider_repo.get_by_name(provider_name)
        # Fallback: check legacy name
        if provider is None:
            provider = await provider_repo.get_by_name(f"ollama-{agent_name}")
            if provider:
                await provider_repo.update(provider.id, name=provider_name)

        if provider is None:
            # Cluster I — auto-created providers default to pending+inactive.
            # The agent self-reports its host and any peer who learned
            # AGENT_SECRET could publish an arbitrary base_url; require an
            # admin to approve the row (sets pending_approval=False,
            # is_active=True) via /api/v1/admin/providers/<id>/approve
            # before the engine routes dispatch to it.
            provider = AIProvider(
                name=provider_name,
                provider_type="ollama",
                base_url=f"http://{server.host}:11434",
                server_id=server.id,
                is_active=False,
                pending_approval=True,
            )
            provider = await provider_repo.create(provider)
            logger.info(
                "Auto-discovered Ollama provider (pending admin approval): %s -> %s",
                provider_name, server.host,
            )

        # Upsert models
        model_repo = AIModelRepository(db)
        seen_ids = []
        for m in ollama_models:
            model_id = m.get("name", m.get("model", ""))
            if not model_id:
                continue
            result = await model_repo.upsert(
                provider_id=provider.id,
                model_identifier=model_id,
                name=model_id,
                capabilities={"family": m.get("family", ""), "format": m.get("format", "")},
                parameters={
                    "parameter_size": m.get("parameter_size", ""),
                    "quantization": m.get("quantization", ""),
                    "size": m.get("size", 0),
                },
            )
            seen_ids.append(result.id)

        # Mark stale models
        if seen_ids:
            await model_repo.mark_unavailable(provider.id, seen_ids)

        await db.commit()


def _parse_host_port(ports_str: str, container_port: int = 8000) -> int | None:
    """Extract the host-side port mapped to a given container port from docker ports string.

    Example: '0.0.0.0:8050->8000/tcp, :::8050->8000/tcp' -> 8050
    """
    import re
    for match in re.finditer(r'(\d+)->(\d+)', ports_str):
        host_port, cont_port = int(match.group(1)), int(match.group(2))
        if cont_port == container_port:
            return host_port
    return None


async def _sync_riffusion_models(
    agent_name: str, riffusion_models: list[dict], db_session_factory
) -> None:
    """Auto-create a Riffusion provider for this agent (if needed) and sync models."""
    async with db_session_factory() as db:
        from app.repositories.server_repo import ServerRepository
        from app.repositories.orchestrator_repo import AIProviderRepository, AIModelRepository
        from app.models.orchestrator import AIProvider

        server_repo = ServerRepository(db)
        server = await server_repo.get_by_name(agent_name)
        if not server:
            return

        provider_repo = AIProviderRepository(db)
        provider_name = f"riffusion-{agent_name}"
        provider = await provider_repo.get_by_name(provider_name)

        if provider is None:
            # Cluster I — pending+inactive on first sight.
            provider = AIProvider(
                name=provider_name,
                provider_type="riffusion",
                base_url=f"http://{server.host}:3013",
                server_id=server.id,
                is_active=False,
                pending_approval=True,
            )
            provider = await provider_repo.create(provider)
            logger.info(
                "Auto-discovered Riffusion provider (pending admin approval): %s -> %s",
                provider_name, server.host,
            )

        # Upsert models
        model_repo = AIModelRepository(db)
        seen_ids = []
        for m in riffusion_models:
            model_id = m.get("name", m.get("model", ""))
            if not model_id:
                continue
            result = await model_repo.upsert(
                provider_id=provider.id,
                model_identifier=model_id,
                name=model_id,
                capabilities={"family": m.get("family", ""), "format": m.get("format", "")},
                parameters={
                    "quantization": m.get("quantization", ""),
                },
            )
            seen_ids.append(result.id)

        if seen_ids:
            await model_repo.mark_unavailable(provider.id, seen_ids)

        await db.commit()


async def _sync_gpu_service_models(
    agent_name: str,
    provider_type: str,
    default_port: int,
    models: list[dict],
    db_session_factory,
) -> None:
    """Auto-create a GPU service provider (musicgen/bark/rvc) and sync its models."""
    async with db_session_factory() as db:
        from app.repositories.server_repo import ServerRepository
        from app.repositories.orchestrator_repo import AIProviderRepository, AIModelRepository
        from app.models.orchestrator import AIProvider

        server_repo = ServerRepository(db)
        server = await server_repo.get_by_name(agent_name)
        if not server:
            return

        provider_repo = AIProviderRepository(db)
        provider_name = f"{provider_type}-{agent_name}"
        provider = await provider_repo.get_by_name(provider_name)

        if provider is None:
            # Cluster I — pending+inactive on first sight.
            provider = AIProvider(
                name=provider_name,
                provider_type=provider_type,
                base_url=f"http://{server.host}:{default_port}",
                server_id=server.id,
                is_active=False,
                pending_approval=True,
            )
            provider = await provider_repo.create(provider)
            logger.info(
                "Auto-discovered %s provider (pending admin approval): %s -> %s:%d",
                provider_type, provider_name, server.host, default_port,
            )

        model_repo = AIModelRepository(db)
        seen_ids = []
        for m in models:
            model_id = m.get("name", m.get("model", ""))
            if not model_id:
                continue
            result = await model_repo.upsert(
                provider_id=provider.id,
                model_identifier=model_id,
                name=model_id,
                capabilities={"family": m.get("family", ""), "format": m.get("format", "")},
                parameters={
                    "quantization": m.get("quantization", ""),
                    "gpu": m.get("gpu", ""),
                    "vram_used_mb": m.get("vram_used_mb", 0),
                },
            )
            seen_ids.append(result.id)

        if seen_ids:
            await model_repo.mark_unavailable(provider.id, seen_ids)

        await db.commit()


async def _sync_vllm_containers(
    agent_name: str, containers: list[dict], db_session_factory
) -> None:
    """Detect running vLLM containers and auto-register as HuggingFace providers."""
    import httpx

    vllm_containers = [
        c for c in containers
        if c.get("state") == "running"
        and "vllm" in (c.get("image", "") or "").lower()
    ]
    if not vllm_containers:
        return

    async with db_session_factory() as db:
        from app.repositories.server_repo import ServerRepository
        from app.repositories.orchestrator_repo import AIProviderRepository, AIModelRepository
        from app.models.orchestrator import AIProvider

        server_repo = ServerRepository(db)
        server = await server_repo.get_by_name(agent_name)
        if not server:
            return

        provider_repo = AIProviderRepository(db)
        model_repo = AIModelRepository(db)

        for container in vllm_containers:
            host_port = _parse_host_port(container.get("ports", ""), 8000)
            if not host_port:
                continue

            base_url = f"http://{server.host}:{host_port}"
            container_name = container.get("name", "vllm")

            # Query the vLLM /v1/models endpoint to find served models
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                    resp = await client.get(f"{base_url}/v1/models")
                    resp.raise_for_status()
                    data = resp.json()
            except Exception as e:
                logger.debug("vLLM container %s not reachable at %s: %s", container_name, base_url, e)
                continue

            served_models = data.get("data", [])
            if not served_models:
                continue

            # Use first model name for provider naming
            model_id = served_models[0].get("id", container_name)
            provider_name = f"{model_id}"

            provider = await provider_repo.get_by_name(provider_name)
            if provider is None:
                # Cluster I — pending+inactive on first sight.
                provider = AIProvider(
                    name=provider_name,
                    provider_type="huggingface",
                    base_url=base_url,
                    server_id=server.id,
                    is_active=False,
                    pending_approval=True,
                )
                provider = await provider_repo.create(provider)
                logger.info(
                    "Auto-discovered HuggingFace provider (pending admin approval): %s -> %s",
                    provider_name, base_url,
                )
            elif provider.base_url != base_url:
                # Update base_url if port changed
                await provider_repo.update(provider.id, base_url=base_url)

            # Upsert models. Cluster I — drop the blanket vision=True claim;
            # admins set capabilities per model explicitly after they
            # approve the provider. ``source: vllm`` survives as a
            # provenance breadcrumb.
            seen_ids = []
            for m in served_models:
                mid = m.get("id", "")
                if not mid:
                    continue
                result = await model_repo.upsert(
                    provider_id=provider.id,
                    model_identifier=mid,
                    name=mid,
                    capabilities={"source": "vllm"},
                    parameters={},
                )
                seen_ids.append(result.id)

            if seen_ids:
                await model_repo.mark_unavailable(provider.id, seen_ids)

        await db.commit()


async def _sync_comfyui_from_probe(
    agent_name: str, comfyui_status: dict, db_session_factory
) -> None:
    """Auto-register a ComfyUI provider from an agent's port-8188 liveness probe.

    Preferred over the docker-container scan (``_sync_comfyui_containers``)
    because ComfyUI is often run as a host process — `docker ps` won't see
    it. The agent's :func:`gpu_services.get_comfyui_status` GETs
    ``/system_stats`` on the configured ComfyUI URL; if 200 OK, this
    handler ensures a provider row exists, is correctly addressed, and is
    ``is_active=True``.

    The base_url is extracted from the probe payload's ``base_url`` field
    (the agent reports the exact URL it just probed), but the host part is
    rewritten to the server's network-reachable host so bob-api on a
    different machine can resolve it.
    """
    probe_base = (comfyui_status or {}).get("base_url") or "http://localhost:8188"
    # Parse port off the probe URL; default 8188 if anything goes wrong.
    try:
        from urllib.parse import urlparse
        probe_port = urlparse(probe_base).port or 8188
    except Exception:
        probe_port = 8188

    async with db_session_factory() as db:
        from sqlalchemy import select
        from app.repositories.server_repo import ServerRepository
        from app.repositories.orchestrator_repo import AIProviderRepository
        from app.models.orchestrator import AIProvider

        server_repo = ServerRepository(db)
        server = await server_repo.get_by_name(agent_name)
        if not server:
            return

        base_url = f"http://{server.host}:{probe_port}"
        canonical_name = f"{server.name}-ComfyUI"
        provider_repo = AIProviderRepository(db)

        # Match by canonical name first; fall back to a same-URL row created
        # by hand under a different name.
        provider = await provider_repo.get_by_name(canonical_name)
        if provider is None:
            result = await db.execute(
                select(AIProvider).where(
                    AIProvider.provider_type == "comfyui",
                    AIProvider.base_url == base_url,
                )
            )
            provider = result.scalar_one_or_none()

        if provider is None:
            # Cluster I — pending+inactive on first sight.
            provider = AIProvider(
                name=canonical_name,
                provider_type="comfyui",
                base_url=base_url,
                server_id=server.id,
                is_active=False,
                pending_approval=True,
            )
            await provider_repo.create(provider)
            logger.info(
                "Auto-discovered ComfyUI provider via probe (pending admin approval): %s -> %s",
                canonical_name, base_url,
            )
        else:
            # Cluster I — never flip is_active=True on an existing row from
            # the sync path; admins do that via /admin/providers/<id>/approve.
            # base_url/server_id may move (port change, agent migration); keep
            # those in sync.
            updates: dict = {}
            if provider.base_url != base_url:
                updates["base_url"] = base_url
            if provider.server_id != server.id:
                updates["server_id"] = server.id
            if updates:
                await provider_repo.update(provider.id, **updates)

        await db.commit()


async def _sync_comfyui_containers(
    agent_name: str, containers: list[dict], db_session_factory
) -> None:
    """Auto-register and auto-(re)activate ComfyUI providers from agent reports.

    Mirrors :func:`_sync_vllm_containers`. When the agent reports a running
    container whose image matches ``comfy``, we ensure a corresponding
    ``ai_providers`` row exists for the agent's host:port, that its base_url
    is current, and that ``is_active=True``. Admins never have to flip the
    active flag by hand — installing the agent is enough.
    """
    comfyui_containers = [
        c for c in containers
        if c.get("state") == "running"
        and "comfy" in (c.get("image", "") or "").lower()
    ]
    if not comfyui_containers:
        return

    async with db_session_factory() as db:
        from sqlalchemy import select
        from app.repositories.server_repo import ServerRepository
        from app.repositories.orchestrator_repo import AIProviderRepository
        from app.models.orchestrator import AIProvider

        server_repo = ServerRepository(db)
        server = await server_repo.get_by_name(agent_name)
        if not server:
            return

        provider_repo = AIProviderRepository(db)

        for container in comfyui_containers:
            host_port = _parse_host_port(container.get("ports", ""), 8188)
            if not host_port:
                continue

            base_url = f"http://{server.host}:{host_port}"
            canonical_name = f"{server.name}-ComfyUI"

            # Match by canonical name first; fall back to base_url for rows
            # that were originally created by hand under a different name.
            provider = await provider_repo.get_by_name(canonical_name)
            if provider is None:
                result = await db.execute(
                    select(AIProvider).where(
                        AIProvider.provider_type == "comfyui",
                        AIProvider.base_url == base_url,
                    )
                )
                provider = result.scalar_one_or_none()

            if provider is None:
                # Cluster I — pending+inactive on first sight.
                provider = AIProvider(
                    name=canonical_name,
                    provider_type="comfyui",
                    base_url=base_url,
                    server_id=server.id,
                    is_active=False,
                    pending_approval=True,
                )
                await provider_repo.create(provider)
                logger.info(
                    "Auto-discovered ComfyUI provider (pending admin approval): %s -> %s",
                    canonical_name, base_url,
                )
                continue

            # Cluster I — never auto-flip is_active=True on an existing row.
            updates: dict = {}
            if provider.base_url != base_url:
                updates["base_url"] = base_url
            if provider.server_id != server.id:
                updates["server_id"] = server.id
            if updates:
                await provider_repo.update(provider.id, **updates)

        await db.commit()
