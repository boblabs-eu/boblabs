"""Bob Manager — internal OpenAI-compatible LLM gateway.

Lets external agent runtimes (the Hermes containers) consume Bob Lab models
THROUGH the LabDispatcher instead of calling providers directly. Every call
gets the same treatment as a native agent's: load balancing across all
providers hosting the model, per-provider concurrency slots, caller affinity
(Ollama KV-cache reuse), failover, and LLM-event logging — so external
inference shows up in the load-balancer feed like everything else.

Mounted at /api/v1/llm-gateway/{tag}/v1/* — `tag` is the calling lab-agent's
id (set by the hermes executor when building the model spec) and is resolved
to a caller name + lab for the event feed. The surface speaks the OpenAI
chat-completions dialect (incl. tools and SSE streaming) because that is what
Hermes' OpenAI client emits.

Auth: machine channel — ``Authorization: Bearer <AGENT_SECRET>`` (the hermes
executor injects it as the api_key of the model spec; Hermes' OpenAI client
sends it back as the bearer token). Not a user-facing endpoint.
"""

import json
import logging
import time
import uuid as uuid_mod
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.config import settings
from app.services.lab_dispatcher import LabDispatcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm-gateway", tags=["llm-gateway"])


def _check_auth(authorization: str | None) -> None:
    if not authorization or authorization != f"Bearer {settings.agent_secret}":
        raise HTTPException(401, "Invalid gateway token")


async def _resolve_caller(db, tag: str) -> tuple[str, UUID | None]:
    """Map the path tag (a lab-agent or library-agent id) to a display name
    and lab id for the LLM-event feed. Falls back gracefully."""
    try:
        agent_id = UUID(tag)
    except ValueError:
        return f"Hermes '{tag[:24]}'", None
    try:
        from app.models.orchestrator import LabAgent, LibraryAgent

        row = (await db.execute(select(LabAgent).where(LabAgent.id == agent_id))).scalars().first()
        if row is not None:
            return f"Hermes '{row.name}'", row.lab_id
        lib = (
            (await db.execute(select(LibraryAgent).where(LibraryAgent.id == agent_id)))
            .scalars()
            .first()
        )
        if lib is not None:
            return f"Hermes '{lib.name}'", None
    except Exception:  # noqa: BLE001 — display metadata only, never block the call
        pass
    return f"Hermes '{str(agent_id)[:12]}'", None


# ── OpenAI dialect ↔ dispatcher-internal conversion ──────────────────


def _content_to_text(content) -> str:
    """OpenAI message content may be a string or a multimodal part array."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text") or "")
        return "\n".join(parts)
    return "" if content is None else str(content)


def _openai_to_internal(messages: list) -> list[dict]:
    """OpenAI chat messages → the dispatcher's provider-neutral format
    (assistant tool_calls flattened to {id, name, arguments-dict})."""
    internal: list[dict] = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role") or "user"
        msg: dict = {"role": role, "content": _content_to_text(m.get("content"))}
        if role == "assistant" and m.get("tool_calls"):
            tcs = []
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {"_raw": args}
                tcs.append(
                    {
                        "id": tc.get("id") or f"call_{uuid_mod.uuid4().hex[:8]}",
                        "name": fn.get("name") or "",
                        "arguments": args or {},
                    }
                )
            msg["tool_calls"] = tcs
        if role == "tool":
            msg["tool_call_id"] = m.get("tool_call_id") or ""
        internal.append(msg)
    return internal


def _tool_calls_to_openai(tool_calls: list | None) -> list[dict] | None:
    if not tool_calls:
        return None
    out = []
    for tc in tool_calls:
        out.append(
            {
                "id": tc.get("id") or f"call_{uuid_mod.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": tc.get("name") or "",
                    "arguments": json.dumps(tc.get("arguments") or {}, ensure_ascii=False),
                },
            }
        )
    return out


# ── Endpoints ─────────────────────────────────────────────────────────


@router.get("/{tag}/v1/models")
async def list_models(tag: str, db: DbSession, authorization: str | None = Header(None)):
    """Minimal OpenAI models listing (some clients probe it on startup)."""
    _check_auth(authorization)
    from app.models.orchestrator import AIModel

    rows = (
        (await db.execute(select(AIModel.model_identifier).where(AIModel.is_available.is_(True))))
        .scalars()
        .all()
    )
    seen, data = set(), []
    for ident in rows:
        if ident in seen:
            continue
        seen.add(ident)
        data.append({"id": ident, "object": "model", "created": 0, "owned_by": "bob-lab"})
    return {"object": "list", "data": data}


@router.post("/{tag}/v1/chat/completions")
async def chat_completions(
    tag: str, request: Request, db: DbSession, authorization: str | None = Header(None)
):
    _check_auth(authorization)
    body = await request.json()

    model = (body.get("model") or "").strip()
    if not model:
        raise HTTPException(400, "model is required")
    messages = _openai_to_internal(body.get("messages") or [])
    if not messages:
        raise HTTPException(400, "messages is required")
    temperature = float(body.get("temperature") if body.get("temperature") is not None else 0.7)
    max_tokens = int(body.get("max_tokens") or body.get("max_completion_tokens") or 4096)
    tools = body.get("tools") or None  # already OpenAI function schema — pass through
    stream = bool(body.get("stream"))

    caller_name, lab_id = await _resolve_caller(db, tag)
    dispatcher = LabDispatcher(db)
    try:
        result = await dispatcher._call_with_loadbalance(
            model_identifier=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            caller_name=caller_name,
            caller_type="hermes",
            lab_id=lab_id,
            tools=tools,
        )
    except RuntimeError as exc:
        # "no provider hosts model" and friends — surface as a clean API error
        raise HTTPException(404, str(exc))

    content = result.get("content") or ""
    tool_calls = _tool_calls_to_openai(result.get("tool_calls"))
    finish_reason = "tool_calls" if tool_calls else "stop"
    usage = {
        "prompt_tokens": int(result.get("tokens_in") or 0),
        "completion_tokens": int(result.get("tokens_out") or 0),
        "total_tokens": int(result.get("tokens_in") or 0) + int(result.get("tokens_out") or 0),
    }
    resp_id = f"chatcmpl-{uuid_mod.uuid4().hex[:24]}"
    created = int(time.time())

    if not stream:
        message: dict = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {
            "id": resp_id,
            "object": "chat.completion",
            "created": created,
            "model": result.get("model") or model,
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": usage,
        }

    # SSE streaming — the dispatcher path is collect-then-return (the
    # concurrency slot is held during generation), so emit the result as a
    # short, valid OpenAI stream: role delta → content delta → tool_calls
    # delta → finish → [DONE]. OpenAI SDK clients accumulate this correctly.
    def _chunk(delta: dict, finish: str | None = None) -> str:
        payload = {
            "id": resp_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": result.get("model") or model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def _gen():
        yield _chunk({"role": "assistant"})
        if content:
            yield _chunk({"content": content})
        if tool_calls:
            yield _chunk(
                {
                    "tool_calls": [
                        {
                            "index": i,
                            "id": tc["id"],
                            "type": "function",
                            "function": tc["function"],
                        }
                        for i, tc in enumerate(tool_calls)
                    ]
                }
            )
        yield _chunk({}, finish=finish_reason)
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")
