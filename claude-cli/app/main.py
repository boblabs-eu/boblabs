"""bob claude-cli wrapper — OpenAI-compatible HTTP front for Claude Code CLI.

Claude CLI has no HTTP server or model-list API, so this wrapper runs next
to the `claude` binary in the same container and exposes the minimal OpenAI
surface the control plane's OpenAICompatibleProvider expects:

    GET  /health               → wrapper + CLI + token status
    GET  /v1/models            → models from CLAUDE_CLI_MODELS (env-driven)
    POST /v1/chat/completions  → one `claude -p` one-shot per request
                                 (SSE streaming and plain JSON)

Role in the fleet mirrors Ollama: a per-server model provider. The GPU
agent probes /v1/models and reports the list over its websocket; the
control plane syncs the models into AIProvider/AIModel (pending approval)
and dispatches inference here via LabDispatcher.

Model identifiers are namespaced ``claude-cli:<id>`` (e.g. claude-cli:opus)
so they can never collide with — or be mistaken for — Anthropic API models
in the shared model list. The set of ids comes ONLY from the
CLAUDE_CLI_MODELS env var (default ``haiku,opus,sonnet`` — bare aliases
track the latest model of each tier; pin e.g. ``claude-opus-4-8`` for a
fixed version).

v1 is text-only at the OpenAI layer: ``tools`` schemas are accepted (logged) but
not advertised to the model; a native ``tool_use`` the model emits anyway is
recovered and converted to the lab's <tool_call> TEXT. Images are dropped from
multimodal content.

Auth: the CLI itself authenticates via CLAUDE_CODE_OAUTH_TOKEN (from
``claude setup-token`` — Max subscription, not API credits). The wrapper is
unauthenticated by default (same LAN trust model as Ollama on 11434); set
CLAUDE_CLI_API_KEY to require a Bearer token on /v1/*.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("claude-cli-wrapper")

app = FastAPI(title="bob claude-cli wrapper")

MODEL_PREFIX = "claude-cli:"

# Every knob is env-driven — CLAUDE_CLI_MODELS is the single source of truth
# for the model list (the literal below is only its default value).
_MODELS_ENV_DEFAULT = "haiku,opus,sonnet"
_CONCURRENCY = max(1, int(os.getenv("CLAUDE_CLI_CONCURRENCY", "2")))
_TIMEOUT_SEC = float(os.getenv("CLAUDE_CLI_TIMEOUT_SEC", "300"))
_API_KEY = os.getenv("CLAUDE_CLI_API_KEY", "")
_EXTRA_ARGS = os.getenv("CLAUDE_CLI_EXTRA_ARGS", "").split()

# One `claude -p` subprocess per request; this is the hard concurrency cap
# (the control plane's dispatcher slot count should stay at or below it).
_slots = asyncio.Semaphore(_CONCURRENCY)

# Make each one-shot a pure TEXT model: the lab owns tool execution and drives
# the loop itself (the model only emits <tool_call> TEXT blocks the control
# plane runs). If Claude keeps any usable tool it emits a real `tool_use`,
# spends its single turn on it, and aborts with `error_max_turns`.
#
# A model has TWO tool sources and BOTH must be shut off (see _one_shot args):
#   • built-in tools (Write/Bash/Task/…) → `--tools ""` (empty available list)
#   • MCP server tools                   → `--strict-mcp-config` (ignore every
#     ambient MCP config; with no --mcp-config that loads ZERO MCP servers).
# `--tools ""` alone is NOT enough — it does not touch MCP tools, so a stray
# MCP server in the persisted ~/.claude volume still leaks tools and brings back
# the error_max_turns failure. Override only to ALLOW built-ins (rare): CLAUDE_CLI_TOOLS="Read".
_CLI_TOOLS = os.getenv("CLAUDE_CLI_TOOLS", "")  # "" = disable all built-in tools

_claude_version: str | None = None


def configured_models() -> list[str]:
    """Bare model ids from CLAUDE_CLI_MODELS (read per call so a container
    env change only needs a restart, never a rebuild)."""
    raw = os.getenv("CLAUDE_CLI_MODELS", _MODELS_ENV_DEFAULT)
    return [m.strip() for m in raw.split(",") if m.strip()]


def namespaced_models() -> list[str]:
    return [f"{MODEL_PREFIX}{m}" for m in configured_models()]


def strip_prefix(model: str) -> str:
    """Accept both 'claude-cli:opus' (control plane) and bare 'opus' (curl)."""
    return model[len(MODEL_PREFIX) :] if model.startswith(MODEL_PREFIX) else model


def _check_auth(request: Request) -> None:
    if not _API_KEY:
        return
    if request.headers.get("authorization", "") != f"Bearer {_API_KEY}":
        raise HTTPException(401, "Invalid or missing bearer token")


# ── Message flattening (OpenAI messages → system prompt + CLI prompt) ──


def _content_to_text(content) -> str:
    """OpenAI content is a string or a multimodal part array; v1 keeps text
    parts only (images are dropped — the CLI one-shot is text-only)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        ]
        if any(isinstance(p, dict) and p.get("type") == "image_url" for p in content):
            logger.warning("dropping image content (claude-cli wrapper is text-only)")
        return "\n".join(t for t in texts if t)
    return str(content or "")


def flatten_messages(messages: list[dict]) -> tuple[str, str]:
    """Return (system_prompt, prompt) for a `claude -p` one-shot.

    All system messages join into the system prompt. A single user message
    passes through verbatim; a longer history is flattened into a labeled
    transcript ending with an instruction to answer as the assistant.
    """
    system_parts: list[str] = []
    convo: list[tuple[str, str]] = []
    for msg in messages or []:
        role = msg.get("role", "user")
        text = _content_to_text(msg.get("content"))
        if role == "system":
            if text:
                system_parts.append(text)
        elif role == "tool":
            # Shouldn't appear (we never return tool_calls) — keep the
            # information rather than erroring if a loop sends one anyway.
            convo.append(("Tool result", text))
        else:
            convo.append(("User" if role == "user" else "Assistant", text))

    system_prompt = "\n\n".join(system_parts)

    if not convo:
        return system_prompt, ""
    if len(convo) == 1 and convo[0][0] == "User":
        return system_prompt, convo[0][1]

    transcript = "\n\n".join(f"{who}: {text}" for who, text in convo)
    prompt = (
        "Conversation so far:\n\n"
        f"{transcript}\n\n"
        "Respond as the assistant to the last user message. "
        "Output only the reply, with no role label."
    )
    return system_prompt, prompt


# ── Claude CLI invocation ─────────────────────────────────────────────


async def _run_claude(args: list[str], stdin_text: str, timeout: float) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "claude",
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(stdin_text.encode()), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HTTPException(504, f"claude CLI timed out after {timeout:.0f}s")
    return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def _one_shot(model: str, system_prompt: str, prompt: str) -> tuple[str, int, int]:
    """Run one `claude -p` turn as a TEXT model. Returns (content, tokens_in, tokens_out).

    The lab drives tools itself: the model is expected to emit <tool_call> TEXT
    blocks the control plane executes. But opus is trained toward NATIVE
    function-calling and — depending on the account's server-side flags — will
    sometimes emit a real `tool_use` instead, even though --tools "" defines no
    tools (so it can't execute and the turn aborts as error_max_turns → 502).
    Rather than fight that, we read the streamed output and CONVERT any native
    tool_use block back into the lab's <tool_call> TEXT form, so both shapes work
    identically. With no native tools defined, the model names the tool from the
    prompt (the lab's own file_read / gouv_data_fr / …), so the conversion is faithful.
    """
    # System prompt passes through VERBATIM (it teaches the <tool_call> protocol);
    # native tools are disabled at the CLI level only — --tools "" (built-ins) and
    # --strict-mcp-config (ambient MCP). stream-json exposes each content block so
    # we can recover a native tool_use instead of failing the call.
    args = [
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",  # required with stream-json under -p
        "--model",
        model,
        "--max-turns",
        "1",
        "--system-prompt",
        system_prompt,
        "--tools",
        _CLI_TOOLS,
        "--strict-mcp-config",
    ]
    args += _EXTRA_ARGS
    # Prompt goes via stdin — long lab transcripts would blow past ARG_MAX.
    rc, stdout, stderr = await _run_claude(args, prompt, _TIMEOUT_SEC)

    text_parts: list[str] = []
    tool_call_blocks: list[str] = []  # native tool_use → lab <tool_call> TEXT
    result_event: dict | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        etype = ev.get("type")
        if etype == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text") or "")
                elif btype == "tool_use":
                    tc = {"name": block.get("name"), "arguments": block.get("input") or {}}
                    tool_call_blocks.append(
                        "<tool_call>\n" + json.dumps(tc, ensure_ascii=False) + "\n</tool_call>"
                    )
        elif etype == "result":
            result_event = ev

    # Reply = model text first, then any native tool_use recovered as <tool_call>.
    parts = [p for p in text_parts if p] + tool_call_blocks
    content = "\n\n".join(parts).strip()
    if not content and result_event:
        content = str(result_event.get("result") or "")

    subtype = (result_event or {}).get("subtype")
    # error_max_turns is EXPECTED when opus emitted a native tool_use — we already
    # captured it as <tool_call> text, so it is NOT a failure. Only raise when we
    # got no usable content back at all.
    if not content:
        try:
            with open("/tmp/claude_cli_last_failure.txt", "w") as fh:
                fh.write(
                    f"model: {model}\nargs: {args!r}\nrc: {rc} subtype: {subtype}\n\n"
                    f"=== SYSTEM PROMPT ({len(system_prompt)} chars) ===\n{system_prompt}\n\n"
                    f"=== USER PROMPT ({len(prompt)} chars) ===\n{prompt}\n\n"
                    f"=== RAW CLAUDE STDOUT (8k) ===\n{stdout[:8000]}\n"
                )
        except OSError:
            pass
        tail = ((result_event or {}).get("result") or stderr or stdout or "unknown error").strip()[
            -2000:
        ]
        logger.error(
            "claude one-shot produced no content (rc=%s subtype=%s): %s", rc, subtype, tail
        )
        raise HTTPException(502, f"claude CLI error (subtype={subtype}): {tail}")

    if tool_call_blocks:
        logger.info(
            "recovered %d native tool_use block(s) → <tool_call> text (model=%s, subtype=%s)",
            len(tool_call_blocks),
            model,
            subtype,
        )

    usage = (result_event or {}).get("usage") or {}
    tokens_in = (
        int(usage.get("input_tokens") or 0)
        + int(usage.get("cache_creation_input_tokens") or 0)
        + int(usage.get("cache_read_input_tokens") or 0)
    )
    tokens_out = int(usage.get("output_tokens") or 0)
    return content, tokens_in, tokens_out


# ── Endpoints ─────────────────────────────────────────────────────────


@app.on_event("startup")
async def detect_cli():
    global _claude_version
    if not shutil.which("claude"):
        logger.error("`claude` binary not found on PATH")
        return
    try:
        rc, stdout, _ = await _run_claude(["--version"], "", 30.0)
        if rc == 0:
            _claude_version = stdout.strip()
            logger.info("claude CLI detected: %s", _claude_version)
    except Exception as exc:  # noqa: BLE001
        logger.error("claude --version failed: %s", exc)


@app.get("/health")
async def health(deep: bool = False):
    token_present = bool(os.getenv("CLAUDE_CODE_OAUTH_TOKEN"))
    status = "ok" if (_claude_version and token_present) else "error"
    out = {
        "status": status,
        "claude_version": _claude_version,
        "token_present": token_present,
        "models": namespaced_models(),
    }
    if deep and status == "ok":
        # Real round-trip through the CLI + auth — setup-time check only,
        # never called by the agent's discovery loop (it burns a request).
        try:
            content, _, _ = await _one_shot(configured_models()[0], "", "Reply with exactly: OK")
            out["probe"] = "ok" if content.strip() else "empty-reply"
        except HTTPException as exc:
            out["status"] = "error"
            out["probe"] = str(exc.detail)
    return out


@app.get("/v1/models")
async def list_models(request: Request):
    _check_auth(request)
    return {
        "object": "list",
        "data": [
            {"id": mid, "object": "model", "created": 0, "owned_by": "anthropic"}
            for mid in namespaced_models()
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    _check_auth(request)
    body = await request.json()

    requested = str(body.get("model") or "")
    bare = strip_prefix(requested)
    if bare not in configured_models():
        raise HTTPException(
            400,
            f"Unknown model '{requested}'. Configured (CLAUDE_CLI_MODELS): "
            + ", ".join(namespaced_models()),
        )

    if body.get("tools"):
        logger.warning("ignoring %d tools (claude-cli wrapper is text-only v1)", len(body["tools"]))
    # temperature / max_tokens have no CLI equivalent — accepted and ignored.

    system_prompt, prompt = flatten_messages(body.get("messages") or [])
    if not prompt.strip():
        raise HTTPException(400, "messages contain no user content")

    async with _slots:
        started = time.time()
        content, tokens_in, tokens_out = await _one_shot(bare, system_prompt, prompt)
        logger.info(
            "one-shot done (model=%s, %.1fs, in=%d out=%d)",
            bare,
            time.time() - started,
            tokens_in,
            tokens_out,
        )

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    usage = {
        "prompt_tokens": tokens_in,
        "completion_tokens": tokens_out,
        "total_tokens": tokens_in + tokens_out,
    }

    if not body.get("stream"):
        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": requested,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
        }

    # The control plane always streams: the CLI gives us the full reply at
    # once, so emit it as a single content chunk, then a stop chunk carrying
    # usage, then [DONE] — exactly what OpenAICompatibleProvider parses.
    def _chunk(delta: dict, finish: str | None = None, with_usage: bool = False) -> str:
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": requested,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        if with_usage:
            payload["usage"] = usage
        return f"data: {json.dumps(payload)}\n\n"

    async def _stream():
        yield _chunk({"role": "assistant", "content": content})
        yield _chunk({}, finish="stop", with_usage=True)
        yield "data: [DONE]\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
