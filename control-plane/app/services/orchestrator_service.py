"""Bob Manager — Orchestrator service.

Core engine that processes user messages, calls LLM providers,
and manages the orchestration loop.
"""

import logging
import time
import traceback
import uuid as _uuid
from typing import AsyncGenerator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orchestrator import AIAgent, AIModel, AIProvider, Message, OrchestratorSettings
from app.repositories.orchestrator_repo import (
    AIAgentRepository,
    AIModelRepository,
    AIProviderRepository,
    OrchestratorSettingsRepository,
)
from app.services.comfyui_discovery import comfyui_health_check
from app.services.conversation_service import ConversationService
from app.services.llm_provider import LLMProvider, create_provider
from app.services.pipelines import is_media_pipeline, get_pipeline
from app.websocket.hub import manager

logger = logging.getLogger(__name__)

# System prompt for the orchestrator itself
ORCHESTRATOR_SYSTEM_PROMPT = """You are Bob Manager's AI Orchestrator — a powerful assistant that helps manage GPU servers, deploy models, generate code, and coordinate complex tasks.

You have access to a fleet of GPU servers and can orchestrate AI agents to accomplish tasks. When a user asks something:
- For simple questions: answer directly and concisely.
- For complex tasks: explain your plan, then execute step by step.

Be helpful, precise, and proactive. Format your responses with Markdown when appropriate."""


class OrchestratorService:
    """Core orchestration engine.

    Phase 1: Direct LLM response (single model, streaming).
    Phase 2 will add: task decomposition, multi-agent dispatch, result aggregation.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings_repo = OrchestratorSettingsRepository(db)
        self.provider_repo = AIProviderRepository(db)
        self.model_repo = AIModelRepository(db)
        self.conv_service = ConversationService(db)

    async def _get_settings(self) -> OrchestratorSettings:
        settings = await self.settings_repo.get()
        if settings is None:
            settings = await self.settings_repo.upsert()
        return settings

    async def _resolve_provider(self, model_override: str | None = None) -> tuple[LLMProvider | None, str, str, str, AIProvider]:
        """Resolve the orchestrator's LLM provider and model.

        If *model_override* is given, look up which provider actually hosts
        that model (via the ai_models table) and use it directly.

        Returns (provider_instance_or_None, model_identifier, provider_name, server_name, provider_obj).
        For non-LLM providers (e.g. riffusion), provider_instance is None.
        """
        settings = await self._get_settings()
        model_id = model_override or settings.orchestrator_model
        provider_type = settings.orchestrator_provider

        logger.info("_resolve_provider: model_override=%s, model_id=%s", model_override, model_id)

        providers = await self.provider_repo.get_all(active_only=True)
        target: AIProvider | None = None

        # Always look up which provider hosts the requested model
        from sqlalchemy import select
        from app.models.orchestrator import AIModel
        stmt = select(AIModel).where(
            AIModel.model_identifier == model_id,
            AIModel.is_available == True,
        )
        result = await self.db.execute(stmt)
        ai_model = result.scalars().first()
        if ai_model:
            logger.info("_resolve_provider: found model in DB, provider_id=%s", ai_model.provider_id)
            for p in providers:
                if p.id == ai_model.provider_id:
                    target = p
                    logger.info("_resolve_provider: matched provider %s at %s", p.name, p.base_url)
                    break

        # Fallback: first active provider of the configured type
        if target is None:
            logger.warning("_resolve_provider: no DB match for model '%s', falling back to first '%s' provider", model_id, provider_type)
            for p in providers:
                if p.provider_type == provider_type:
                    target = p
                    break

        if target is None:
            raise RuntimeError(
                f"No active '{provider_type}' provider configured. "
                "Add one in Settings → AI Providers."
            )

        logger.info("_resolve_provider: using provider %s at %s for model %s", target.name, target.base_url, model_id)
        # Non-LLM provider types get None for the LLM instance
        llm = None
        if not is_media_pipeline(target.provider_type):
            llm = create_provider(target.provider_type, target.base_url, target.api_key)
        # Resolve actual server name from server_id (provider name may be model name for HuggingFace)
        server_name = target.name
        if target.server_id:
            from app.models.server import Server
            sr = await self.db.execute(select(Server).where(Server.id == target.server_id))
            srv = sr.scalars().first()
            if srv:
                server_name = srv.name
        return llm, model_id, target.name, server_name, target

    def _build_messages(
        self,
        history: list[Message],
        user_content: str,
        images: list[str] | None = None,
        context_mode: str = "minimal",
        system_prompt: str | None = None,
    ) -> list[dict]:
        """Build the messages array for the LLM call.

        context_mode controls how historical images are handled:
        - 'full': include images from ALL previous messages (for large-context
          models that accept multiple images, e.g. Qwen-VL, LLaVA-Next).
        - 'minimal': only the current user message carries images (safe for
          models with a 1-image limit like GLM-4V).
        """
        include_history_images = context_mode == "full"
        msgs: list[dict] = [{"role": "system", "content": system_prompt or ORCHESTRATOR_SYSTEM_PROMPT}]
        for m in history:
            if m.role in ("user", "assistant"):
                msg_dict: dict = {"role": m.role, "content": m.content}
                if include_history_images:
                    prev_images = (m.extra or {}).get("images")
                    if prev_images:
                        msg_dict["images"] = prev_images
                msgs.append(msg_dict)
        user_msg: dict = {"role": "user", "content": user_content}
        if images:
            user_msg["images"] = images
            logger.info(
                "Attaching %d image(s) to user message (sizes: %s, context_mode=%s)",
                len(images),
                [len(img) for img in images],
                context_mode,
            )
        msgs.append(user_msg)
        return msgs

    async def _load_agent(self, agent_id: UUID) -> tuple[AIAgent | None, str | None]:
        """Load an AIAgent and resolve its model_identifier.

        Returns (agent, model_identifier) or (None, None) if not found.
        """
        repo = AIAgentRepository(self.db)
        agent = await repo.get_by_id(agent_id)
        if not agent:
            return None, None
        model_identifier = None
        if agent.model_id:
            from sqlalchemy import select
            result = await self.db.execute(
                select(AIModel).where(AIModel.id == agent.model_id)
            )
            ai_model = result.scalars().first()
            if ai_model:
                model_identifier = ai_model.model_identifier
        return agent, model_identifier

    async def process_message(
        self, conversation_id: UUID, user_content: str, model_override: str | None = None,
        images: list[str] | None = None, context_mode: str | None = None,
        agent_id: UUID | None = None, adhoc_tools: list[str] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Process a user message and stream the response.

        1. Saves user message
        2. Builds context from conversation history
        3. If agent with tools: runs tool call loop, streams tool events
        4. Calls LLM with streaming for the final response
        5. Saves assistant message when complete

        Yields SSE-formatted strings:
            data: {"token": "...", "done": false}
            data: {"tool_call": {...}, "done": false}
            data: {"tool_result": {...}, "done": false}
            data: {"token": "", "done": true, "message_id": "..."}
        """
        import json

        # Save user message (store image refs in extra metadata)
        extra_kwargs: dict = {}
        if images:
            extra_kwargs["extra"] = {"images": images}
        user_msg = await self.conv_service.add_message(
            conversation_id, "user", user_content, **extra_kwargs
        )
        await self.db.commit()

        # Broadcast activity to connected UI clients
        await manager.broadcast_to_clients(
            {
                "type": "orchestrator.message",
                "payload": {
                    "conversation_id": str(conversation_id),
                    "message_id": str(user_msg.id),
                    "role": "user",
                    "content": user_content,
                },
            }
        )

        # Get conversation history
        history = await self.conv_service.get_messages(conversation_id)

        # ── Load agent if specified ──────────────────────
        agent: AIAgent | None = None
        agent_model_id: str | None = None
        agent_tool_names: list[str] = []
        if agent_id:
            agent, agent_model_id = await self._load_agent(agent_id)
            if agent:
                agent_tool_names = list(agent.tools or [])

        # Merge ad-hoc tools (conversation-level or per-message)
        if adhoc_tools:
            merged = set(agent_tool_names) | set(adhoc_tools)
            agent_tool_names = list(merged)

        # Determine effective model (agent model > user override > settings default)
        effective_model = model_override or agent_model_id

        # Resolve LLM provider
        try:
            llm, model_id, provider_name, server_name, target_provider = await self._resolve_provider(effective_model)
        except RuntimeError as e:
            error_msg = str(e)
            err = await self.conv_service.add_message(
                conversation_id,
                "assistant",
                f"⚠️ {error_msg}",
                metadata={"error": True},
            )
            await self.db.commit()
            yield f"data: {json.dumps({'token': f'⚠️ {error_msg}', 'done': False})}\n\n"
            yield f"data: {json.dumps({'token': '', 'done': True, 'message_id': str(err.id)})}\n\n"
            return

        # ── Media pipeline path (riffusion, etc.) ────────────────
        if is_media_pipeline(target_provider.provider_type):
            async for sse in self._handle_media_pipeline(
                conversation_id, user_content, model_id,
                provider_name, server_name, target_provider,
            ):
                yield sse
            return

        # Log LLM dispatch event
        from app.services.lab_dispatcher import _log_llm_event, _strip_images

        # Determine system prompt and LLM params
        system_prompt = agent.system_prompt if agent else None
        temperature = float(agent.temperature) if agent else 0.7
        max_tokens = agent.max_tokens if agent else 16384

        # Build messages for LLM
        llm_messages = self._build_messages(
            history[:-1], user_content, images=images,
            context_mode=context_mode or "minimal",
            system_prompt=system_prompt,
        )

        # If agent has tools, inject tool descriptions into system prompt
        if agent_tool_names:
            from app.services.tool_executor import format_tool_descriptions, build_native_tools_schema
            tool_desc = format_tool_descriptions(agent_tool_names)
            llm_messages[0]["content"] += "\n\n" + tool_desc

        req_id = _uuid.uuid4()

        await _log_llm_event(
            self.db,
            request_id=req_id,
            event_type="dispatch",
            model_identifier=model_id,
            provider_name=provider_name,
            server_name=server_name,
            caller_type="conversation",
            caller_name=agent.name if agent else None,
            conversation_id=conversation_id,
            input_messages=_strip_images(llm_messages),
        )

        # ── Agent with tools: tool call loop ─────────────
        if agent_tool_names:
            # For ad-hoc tools without agent, create a minimal agent-like object
            effective_agent = agent
            if not effective_agent:
                effective_agent = AIAgent(
                    name="Assistant", description="", system_prompt="",
                    tools=agent_tool_names, is_active=True,
                )
            async for sse in self._process_with_tools(
                conversation_id=conversation_id,
                llm=llm,
                llm_messages=llm_messages,
                model_id=model_id,
                provider_name=provider_name,
                server_name=server_name,
                temperature=temperature,
                max_tokens=max_tokens,
                agent=effective_agent,
                agent_tool_names=agent_tool_names,
                req_id=req_id,
            ):
                yield sse
            return

        # ── Standard streaming (no tools) ────────────────
        full_response = []
        tokens_in = 0
        tokens_out = 0
        t0 = time.monotonic()

        try:
            async for chunk in llm.chat_completion(
                llm_messages, model_id, temperature=temperature, max_tokens=max_tokens
            ):
                if chunk.get("done"):
                    tokens_in = chunk.get("tokens_in", 0)
                    tokens_out = chunk.get("tokens_out", 0)
                else:
                    token = chunk.get("token", "")
                    full_response.append(token)
                    yield f"data: {json.dumps({'token': token, 'done': False})}\n\n"

        except Exception as e:
            logger.error("LLM error: %s", e)
            error_text = f"⚠️ LLM error: {e}"
            full_response.append(error_text)
            yield f"data: {json.dumps({'token': error_text, 'done': False})}\n\n"
            # Log failed event
            await _log_llm_event(
                self.db,
                request_id=req_id,
                event_type="failed",
                model_identifier=model_id,
                provider_name=provider_name,
                server_name=server_name,
                caller_type="conversation",
                conversation_id=conversation_id,
                error=str(e),
            )

        duration_ms = int((time.monotonic() - t0) * 1000)
        content = "".join(full_response)

        # Log response event
        if not any(error_text in r for r in full_response for error_text in ["⚠️ LLM error:"]):
            await _log_llm_event(
                self.db,
                request_id=req_id,
                event_type="response",
                model_identifier=model_id,
                provider_name=provider_name,
                server_name=server_name,
                caller_type="conversation",
                conversation_id=conversation_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                duration_ms=duration_ms,
                output_content=content,
            )

        # Save assistant message
        msg_kwargs: dict = {
            "model_used": model_id,
            "provider_used": provider_name,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "duration_ms": duration_ms,
        }
        if agent:
            msg_kwargs["agent_id"] = agent.id
            msg_kwargs["agent_name"] = agent.name
        assistant_msg = await self.conv_service.add_message(
            conversation_id, "assistant", content, **msg_kwargs,
        )
        await self.db.commit()

        # Broadcast assistant message to UI
        await manager.broadcast_to_clients(
            {
                "type": "orchestrator.message",
                "payload": {
                    "conversation_id": str(conversation_id),
                    "message_id": str(assistant_msg.id),
                    "role": "assistant",
                    "content": content,
                    "model_used": model_id,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "duration_ms": duration_ms,
                },
            }
        )

        yield f"data: {json.dumps({'token': '', 'done': True, 'message_id': str(assistant_msg.id)})}\n\n"

    # ── Tool call loop for agents ───────────────────

    async def _process_with_tools(
        self,
        conversation_id: UUID,
        llm: LLMProvider,
        llm_messages: list[dict],
        model_id: str,
        provider_name: str,
        server_name: str,
        temperature: float,
        max_tokens: int,
        agent: AIAgent,
        agent_tool_names: list[str],
        req_id,
    ) -> AsyncGenerator[str, None]:
        """Run the tool call loop then stream the final response."""
        import json
        from app.services.lab_dispatcher import _log_llm_event
        from app.services.tool_executor import (
            ToolExecutor,
            build_native_tools_schema,
            parse_tool_calls,
        )
        from app.services.pipelines import normalize_tool_names, extract_pipeline_names

        native_tools = build_native_tools_schema(agent_tool_names)
        normalized_tools = set(normalize_tool_names(agent_tool_names))

        # Create a tool executor using conversation_id as workspace id
        tool_executor = ToolExecutor(
            lab_id=conversation_id,
            db=self.db,
            timeout_sec=120,
            max_output_kb=256,
            allowed_pipelines=extract_pipeline_names(agent_tool_names),
        )

        MAX_TOOL_ROUNDS = 10
        total_tokens_in = 0
        total_tokens_out = 0
        t0 = time.monotonic()
        content = ""

        for _round in range(MAX_TOOL_ROUNDS):
            # Call LLM (non-streaming) with tools
            try:
                result = await llm.chat(
                    llm_messages, model_id,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=native_tools,
                )
            except Exception as e:
                logger.error("LLM error during tool loop: %s\n%s", e, traceback.format_exc())
                error_text = f"⚠️ LLM error: {e}"
                err_msg = await self.conv_service.add_message(
                    conversation_id, "assistant", error_text,
                    agent_id=agent.id, agent_name=agent.name,
                    model_used=model_id, provider_used=provider_name,
                )
                await self.db.commit()
                yield f"data: {json.dumps({'token': error_text, 'done': False})}\n\n"
                yield f"data: {json.dumps({'token': '', 'done': True, 'message_id': str(err_msg.id)})}\n\n"
                return

            total_tokens_in += result.get("tokens_in", 0)
            total_tokens_out += result.get("tokens_out", 0)
            content = result.get("content", "")

            # Check for tool calls: native first, then text-parsed
            tool_calls = []
            native_tc = result.get("tool_calls")
            if native_tc:
                tool_calls = [{"name": tc.get("name", ""), "arguments": tc.get("arguments", {})} for tc in native_tc]
            elif content:
                tool_calls = parse_tool_calls(content, agent_tools=agent_tool_names)

            if not tool_calls:
                # No more tool calls — stream the final text response
                break

            # Execute each tool call
            for tc in tool_calls:
                tool_name = tc["name"]
                tool_args = tc.get("arguments", {})

                # Validate tool is allowed
                tc_normalized = normalize_tool_names([tool_name])
                if not set(tc_normalized).issubset(normalized_tools):
                    logger.warning("Agent tried disallowed tool: %s", tool_name)
                    continue

                # Emit tool_call event to frontend
                yield f"data: {json.dumps({'tool_call': {'name': tool_name, 'arguments': tool_args}, 'done': False})}\n\n"

                # Execute
                tr = await tool_executor.execute(tool_name, tool_args)

                # Emit tool_result event to frontend
                yield f"data: {json.dumps({'tool_result': {'name': tool_name, 'success': tr.get('success', False), 'output': tr.get('output', '')[:2000]}, 'done': False})}\n\n"

                # Append assistant tool call + result to messages for next LLM round
                if native_tc:
                    # Native format: assistant message with tool_calls, then tool result
                    # Use flat internal format (id/name/arguments) – _convert_messages_ollama
                    # converts to provider-specific shape before sending.
                    llm_messages.append({
                        "role": "assistant",
                        "content": content or "",
                        "tool_calls": [{"id": f"call_{tool_name}", "name": tool_name, "arguments": tool_args}],
                    })
                    llm_messages.append({
                        "role": "tool",
                        "tool_call_id": f"call_{tool_name}",
                        "content": tr.get("output", ""),
                    })
                else:
                    # Text-based: append as assistant + user messages
                    llm_messages.append({"role": "assistant", "content": content})
                    llm_messages.append({
                        "role": "user",
                        "content": f"<tool_result>\n{json.dumps(tr)}\n</tool_result>",
                    })

            # Save tool messages to conversation for history
            tool_summary_parts = []
            for tc in tool_calls:
                tr_text = f"🔧 **{tc['name']}**({json.dumps(tc.get('arguments', {}), ensure_ascii=False)[:200]})"
                tool_summary_parts.append(tr_text)
            tool_summary = "\n".join(tool_summary_parts)
            await self.conv_service.add_message(
                conversation_id, "assistant", tool_summary,
                agent_id=agent.id, agent_name=agent.name,
                model_used=model_id, provider_used=provider_name,
                extra={"tool_calls": [tc for tc in tool_calls]},
            )
            await self.db.commit()

        # Stream the final response
        duration_ms = int((time.monotonic() - t0) * 1000)
        final_content = content  # from the last non-tool-call result

        if not final_content:
            # If the final result was empty, do one more streaming call without tools
            final_parts = []
            try:
                async for chunk in llm.chat_completion(
                    llm_messages, model_id,
                    temperature=temperature, max_tokens=max_tokens,
                ):
                    if chunk.get("done"):
                        total_tokens_in += chunk.get("tokens_in", 0)
                        total_tokens_out += chunk.get("tokens_out", 0)
                    else:
                        token = chunk.get("token", "")
                        final_parts.append(token)
                        yield f"data: {json.dumps({'token': token, 'done': False})}\n\n"
            except Exception as e:
                logger.error("LLM streaming error: %s", e)
                final_parts.append(f"⚠️ LLM error: {e}")
                yield f"data: {json.dumps({'token': f'⚠️ LLM error: {e}', 'done': False})}\n\n"
            final_content = "".join(final_parts)
            duration_ms = int((time.monotonic() - t0) * 1000)
        else:
            # Stream the already-collected final content
            yield f"data: {json.dumps({'token': final_content, 'done': False})}\n\n"

        # Log response
        await _log_llm_event(
            self.db,
            request_id=req_id,
            event_type="response",
            model_identifier=model_id,
            provider_name=provider_name,
            server_name=server_name,
            caller_type="conversation",
            caller_name=agent.name,
            conversation_id=conversation_id,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            duration_ms=duration_ms,
            output_content=final_content,
        )

        # Save final assistant message
        assistant_msg = await self.conv_service.add_message(
            conversation_id, "assistant", final_content,
            agent_id=agent.id, agent_name=agent.name,
            model_used=model_id, provider_used=provider_name,
            tokens_in=total_tokens_in, tokens_out=total_tokens_out,
            duration_ms=duration_ms,
        )
        await self.db.commit()

        await manager.broadcast_to_clients(
            {
                "type": "orchestrator.message",
                "payload": {
                    "conversation_id": str(conversation_id),
                    "message_id": str(assistant_msg.id),
                    "role": "assistant",
                    "content": final_content,
                    "model_used": model_id,
                    "agent_name": agent.name,
                    "tokens_in": total_tokens_in,
                    "tokens_out": total_tokens_out,
                    "duration_ms": duration_ms,
                },
            }
        )

        yield f"data: {json.dumps({'token': '', 'done': True, 'message_id': str(assistant_msg.id)})}\n\n"

    # ── Media pipeline path (riffusion, etc.) ──────────

    async def _handle_media_pipeline(
        self,
        conversation_id: UUID,
        prompt: str,
        model_id: str,
        provider_name: str,
        server_name: str,
        provider: AIProvider,
    ) -> AsyncGenerator[str, None]:
        """LLM plans params → pipeline generates media → stream result as SSE."""
        import json
        import re

        pipeline = get_pipeline(provider.provider_type, provider.base_url)
        _is_video_pipeline = provider.provider_type in ("ltx_video", "wan_video")
        _emoji = "🎬" if _is_video_pipeline else "🎵"

        # Step 1 — Ask an LLM to produce structured params
        yield f"data: {json.dumps({'token': f'{_emoji} Interpreting prompt with LLM...\\n', 'done': False})}\n\n"

        planner_llm, planner_model = await self._get_planner_llm()
        if planner_llm is None:
            err_msg = await self.conv_service.add_message(
                conversation_id, "assistant",
                "⚠️ No LLM provider available to plan generation parameters.",
                model_used=model_id, provider_used=provider_name,
            )
            await self.db.commit()
            yield f"data: {json.dumps({'token': '⚠️ No LLM available to plan params.', 'done': False})}\n\n"
            yield f"data: {json.dumps({'token': '', 'done': True, 'message_id': str(err_msg.id)})}\n\n"
            return

        llm_messages = [
            {"role": "system", "content": pipeline.system_prompt()},
            {"role": "user", "content": prompt},
        ]

        llm_tokens: list[str] = []
        try:
            got_first_token = False
            async for chunk in planner_llm.chat_completion(
                llm_messages, planner_model, temperature=0.3, max_tokens=512
            ):
                if not chunk.get("done"):
                    llm_tokens.append(chunk.get("token", ""))
                    if not got_first_token:
                        got_first_token = True
                        yield f"data: {json.dumps({'token': '🤖 Planning parameters...\n', 'done': False})}\n\n"
        except Exception as e:
            logger.error("LLM planning error for %s pipeline: %s", provider.provider_type, e)
            err_msg = await self.conv_service.add_message(
                conversation_id, "assistant",
                f"⚠️ LLM failed to generate parameters: {e}",
                model_used=model_id, provider_used=provider_name,
            )
            await self.db.commit()
            yield f"data: {json.dumps({'token': f'⚠️ LLM planning error: {e}', 'done': False})}\n\n"
            yield f"data: {json.dumps({'token': '', 'done': True, 'message_id': str(err_msg.id)})}\n\n"
            return

        raw_llm = "".join(llm_tokens).strip()

        # Extract JSON (LLM may wrap it in ```json ... ```)
        json_match = re.search(r'\{[\s\S]*\}', raw_llm)
        if not json_match:
            err_msg = await self.conv_service.add_message(
                conversation_id, "assistant",
                f"⚠️ LLM did not return valid JSON.\n\nRaw:\n```\n{raw_llm[:500]}\n```",
                model_used=model_id, provider_used=provider_name,
            )
            await self.db.commit()
            yield f"data: {json.dumps({'token': '⚠️ LLM did not return valid JSON.', 'done': False})}\n\n"
            yield f"data: {json.dumps({'token': '', 'done': True, 'message_id': str(err_msg.id)})}\n\n"
            return

        try:
            raw_params = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            err_msg = await self.conv_service.add_message(
                conversation_id, "assistant",
                f"⚠️ Invalid JSON from LLM: {e}\n\n```\n{raw_llm[:500]}\n```",
                model_used=model_id, provider_used=provider_name,
            )
            await self.db.commit()
            yield f"data: {json.dumps({'token': '⚠️ Invalid JSON from LLM.', 'done': False})}\n\n"
            yield f"data: {json.dumps({'token': '', 'done': True, 'message_id': str(err_msg.id)})}\n\n"
            return

        # Step 2 — Validate & sanitise through the pipeline
        try:
            clean_params = pipeline.validate_params(raw_params)
        except ValueError as e:
            err_msg = await self.conv_service.add_message(
                conversation_id, "assistant",
                f"⚠️ Invalid parameters: {e}",
                model_used=model_id, provider_used=provider_name,
            )
            await self.db.commit()
            yield f"data: {json.dumps({'token': f'⚠️ Invalid parameters: {e}', 'done': False})}\n\n"
            yield f"data: {json.dumps({'token': '', 'done': True, 'message_id': str(err_msg.id)})}\n\n"
            return

        param_summary = pipeline.format_summary(clean_params)
        is_video = provider.provider_type in ("ltx_video", "wan_video")
        gen_label = "video" if is_video else "audio"
        yield f"data: {json.dumps({'token': param_summary + f'\\n\\n⏳ Generating {gen_label}...\\n', 'done': False})}\n\n"

        # Step 3 — Execute the pipeline
        # For video pipelines, poll the GPU service /status endpoint every 10s
        # to relay step progress via SSE (keeps the connection alive and shows
        # live progress in the UI even for 2h+ generations).
        t0 = time.monotonic()

        if _is_video_pipeline:
            import asyncio
            import httpx as _httpx

            gen_task = asyncio.create_task(pipeline.generate(clean_params))
            _poll_timeout = _httpx.Timeout(5.0)
            _last_step_reported = -1

            while not gen_task.done():
                await asyncio.sleep(10)
                if gen_task.done():
                    break
                try:
                    async with _httpx.AsyncClient(timeout=_poll_timeout) as _hc:
                        sr = await _hc.get(f"{provider.base_url}/status")
                    if sr.status_code == 200:
                        st = sr.json()
                        step = st.get("step", 0)
                        total = st.get("total_steps", 0)
                        if st.get("generating") and step > _last_step_reported and total > 0:
                            _last_step_reported = step
                            pct = int(step / total * 100)
                            elapsed = int(time.monotonic() - t0)
                            yield f"data: {json.dumps({'token': f'⏳ Step {step}/{total} ({pct}%) — {elapsed}s elapsed\\n', 'done': False})}\n\n"
                except Exception:
                    pass  # GPU service may not support /status yet

            result = gen_task.result()
        else:
            result = await pipeline.generate(clean_params)

        duration_ms = int((time.monotonic() - t0) * 1000)

        if not result.success:
            err_msg = await self.conv_service.add_message(
                conversation_id, "assistant",
                f"🎵 {param_summary}\n\n⚠️ {result.error}",
                model_used=model_id, provider_used=provider_name,
            )
            await self.db.commit()
            yield f"data: {json.dumps({'token': f'\\n⚠️ {result.error}', 'done': False})}\n\n"
            yield f"data: {json.dumps({'token': '', 'done': True, 'message_id': str(err_msg.id)})}\n\n"
            return

        # Build final message — adapt label for audio vs video
        is_video_result = result.media_type == "video"
        emoji = "🎬" if is_video_result else "🎵"
        kind_label = "Video" if is_video_result else "Text to Audio"
        content = (
            f"{emoji} **{kind_label}** — \"{prompt}\"\n\n"
            f"{param_summary}\n\n"
            f"Duration: {result.duration_s:.1f}s · Inference: {duration_ms}ms "
            f"(planned by {planner_model})"
        )

        # Store result under the correct media key
        extra_data = {
            "pipeline": provider.provider_type,
            "duration_s": result.duration_s,
            "prompt": prompt,
            "params": result.params_used,
        }
        if is_video_result:
            extra_data["video"] = result.media_url
        else:
            extra_data["audio"] = result.media_url
            extra_data["image"] = result.preview_url

        assistant_msg = await self.conv_service.add_message(
            conversation_id, "assistant", content,
            model_used=model_id,
            provider_used=provider_name,
            duration_ms=duration_ms,
            extra=extra_data,
        )
        await self.db.commit()

        # SSE: media event then done
        if is_video_result:
            yield f"data: {json.dumps({'token': '', 'done': False, 'video': result.media_url, 'duration_s': result.duration_s})}\n\n"
        else:
            yield f"data: {json.dumps({'token': '', 'done': False, 'audio': result.media_url, 'image': result.preview_url, 'duration_s': result.duration_s})}\n\n"
        yield f"data: {json.dumps({'token': '', 'done': True, 'message_id': str(assistant_msg.id)})}\n\n"

    async def _get_planner_llm(self) -> tuple[LLMProvider | None, str]:
        """Resolve the default LLM to use as a planner for media pipelines."""
        try:
            llm, model, _, _, prov = await self._resolve_provider(None)
            if llm is not None:
                return llm, model
        except RuntimeError:
            pass

        # Fallback: first active Ollama provider
        providers = await self.provider_repo.get_all(active_only=True)
        for p in providers:
            if p.provider_type == "ollama":
                return create_provider(p.provider_type, p.base_url, p.api_key), "gemma3:4b"
        return None, ""

    async def test_provider(self, provider_id: UUID) -> dict:
        """Test connectivity to a provider."""
        provider = await self.provider_repo.get_by_id(provider_id)
        if provider is None:
            raise ValueError("Provider not found")

        if provider.provider_type == "comfyui":
            healthy = await comfyui_health_check(provider.base_url)
            return {"provider_id": str(provider_id), "healthy": healthy}

        # Media pipeline providers have their own health_check via the pipeline class
        from app.services.pipelines import is_media_pipeline, get_pipeline
        if is_media_pipeline(provider.provider_type):
            try:
                pipeline = get_pipeline(provider.provider_type, provider.base_url)
                healthy = await pipeline.health_check()
            except Exception:
                healthy = False
            return {"provider_id": str(provider_id), "healthy": healthy}

        llm = create_provider(provider.provider_type, provider.base_url, provider.api_key)
        healthy = await llm.health_check()
        return {"provider_id": str(provider_id), "healthy": healthy}
