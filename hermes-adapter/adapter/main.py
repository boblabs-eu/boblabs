"""bob hermes-adapter — HTTP front for the real NousResearch Hermes agent.

Implements the contract in ../ADAPTER_CONTRACT.md for the Bob Lab
control-plane (`app/services/hermes/`):

    GET  /health        → 200 once Hermes is importable
    GET  /v1/info       → version info
    POST /v1/agent/run  → run ONE full Hermes turn, return the final reply

Integration is in-process: `run_agent.AIAgent` is a library class that takes
the LLM connection (base_url / api_key / provider / model) directly in its
constructor and exposes `run_conversation(prompt) -> reply`. The Bob Lab
`model` block arrives on EVERY request, so a fresh AIAgent is constructed per
turn — switching the model in the Bob Lab UI takes effect on the next task
with no container restart. Hermes' persistent state (memory, skills,
sessions) lives in ~/.hermes, which the control-plane mounts as a named
volume, so continuity survives both new AIAgent instances and restarts.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from importlib import metadata
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("hermes-adapter")

app = FastAPI(title="bob hermes-adapter")

# Hermes is a single-loop agent and AIAgent isn't documented thread-safe:
# serialize turns. (The control-plane also serializes per container.)
_run_lock = asyncio.Lock()

# ── Session conversation history ──────────────────────────────────────
# run_conversation() does NOT accumulate history on its own — Hermes' CLI
# passes the running transcript via the `conversation_history` parameter on
# every call (verified: history=0 on every turn otherwise, so "continue"
# rounds and follow-up tasks arrived context-free). The adapter owns that
# transcript per session: kept in memory and mirrored to the persistent
# ~/.hermes volume so continuity survives container restarts.
_histories: dict[str, list[dict]] = {}
_HISTORY_MAX_MSGS = 60
_HIST_DIR = Path.home() / ".hermes" / "bob_sessions"


def _history_path(sid: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in sid)[:80]
    return _HIST_DIR / f"{safe}.json"


def _get_history(sid: str) -> list[dict]:
    if sid not in _histories:
        loaded: list[dict] = []
        try:
            import json

            path = _history_path(sid)
            if path.exists():
                data = json.loads(path.read_text())
                if isinstance(data, list):
                    loaded = data
        except Exception:  # noqa: BLE001 — corrupt history: start fresh
            loaded = []
        _histories[sid] = loaded
    return _histories[sid]


def _save_history(sid: str) -> None:
    try:
        import json

        _HIST_DIR.mkdir(parents=True, exist_ok=True)
        _history_path(sid).write_text(json.dumps(_histories.get(sid, []), ensure_ascii=False))
    except Exception:  # noqa: BLE001 — persistence is best-effort
        logger.warning("could not persist session history for %s", sid)


def _append_turn_messages(history: list[dict], turn_messages: list) -> None:
    """Fold a turn's messages into the session transcript (user/assistant
    text only — tool internals stay inside Hermes), then trim."""
    for m in turn_messages or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            history.append({"role": role, "content": content})
    del history[:-_HISTORY_MAX_MSGS]


# AIAgent import is deferred so /health can report a broken install clearly.
_import_error: str | None = None
_import_done = threading.Event()


def _try_import() -> bool:
    global _import_error
    try:
        import run_agent  # noqa: F401  (hermes-agent's library entrypoint)

        _import_error = None
        return True
    except Exception as exc:  # noqa: BLE001
        _import_error = f"{type(exc).__name__}: {exc}"
        return False
    finally:
        _import_done.set()


@app.on_event("startup")
async def warm_import():
    # Import in a thread — hermes pulls a large dependency tree.
    await asyncio.to_thread(_try_import)
    if _import_error:
        logger.error("Hermes import failed: %s", _import_error)
    else:
        logger.info("Hermes imported OK")


class ModelSpec(BaseModel):
    provider_type: str
    base_url: str | None = None
    api_key: str | None = None
    model_identifier: str


class RunIn(BaseModel):
    system_prompt: str = ""
    instruction: str
    history: list[dict] = []  # reserved — Hermes' own session memory carries continuity
    model: ModelSpec
    options: dict = {}


def _write_context_override(context_length: int) -> None:
    """Merge Hermes' documented small-context escape hatches into
    ~/.hermes/config.yaml: ``model.context_length`` clears the 64K init
    guardrail, ``model.ollama_num_ctx`` makes Hermes request that runtime
    context from Ollama per call (its own error message recommends 65536)."""
    import yaml

    cfg_path = Path.home() / ".hermes" / "config.yaml"
    cfg: dict = {}
    if cfg_path.exists():
        try:
            cfg = yaml.safe_load(cfg_path.read_text()) or {}
        except Exception:  # noqa: BLE001 — corrupt config: rebuild the key we need
            cfg = {}
    cfg.setdefault("model", {})
    if not isinstance(cfg["model"], dict):
        cfg["model"] = {}
    cfg["model"]["context_length"] = context_length
    cfg["model"]["ollama_num_ctx"] = context_length
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.safe_dump(cfg))


# Cloud presets mirror the control-plane's _OPENAI_COMPATIBLE_PRESETS.
_OPENAI_PRESETS = {
    "openai_cloud": "https://api.openai.com/v1",
    "xai": "https://api.x.ai/v1",
    "groq": "https://api.groq.com/openai/v1",
    "deepseek": "https://api.deepseek.com/v1",
}


def _hermes_connection(spec: ModelSpec) -> dict:
    """Map a Bob Lab model spec to AIAgent constructor kwargs.

    Anthropic gets Hermes' native `anthropic` api_mode. Everything else Bob
    Lab serves (ollama, openai, huggingface, groq, …) speaks OpenAI-compatible
    chat-completions: pass a `/v1` base_url and let Hermes' base_url
    auto-detection pick the default chat_completions mode.
    """
    pt = (spec.provider_type or "").lower()
    base = (spec.base_url or "").rstrip("/")

    if pt == "anthropic":
        return {
            "provider": "anthropic",
            "base_url": base or "https://api.anthropic.com",
            "api_key": spec.api_key,
            "model": spec.model_identifier,
        }

    if not base:
        base = _OPENAI_PRESETS.get(pt, "")
    if not base:
        raise HTTPException(400, f"No base_url for provider_type '{spec.provider_type}'")
    if not base.endswith("/v1"):
        base = base + "/v1"

    # Ollama ignores the key but OpenAI-SDK clients require one to be set.
    api_key = spec.api_key or "not-needed"
    return {
        "provider": None,  # auto-detect from base_url → chat_completions
        "base_url": base,
        "api_key": api_key,
        "model": spec.model_identifier,
    }


@app.get("/health")
async def health():
    if not _import_done.is_set():
        raise HTTPException(503, "Hermes still importing")
    if _import_error:
        raise HTTPException(503, f"Hermes unavailable: {_import_error}")
    return {"status": "ok"}


@app.get("/v1/info")
async def info():
    try:
        version = metadata.version("hermes-agent")
    except Exception:  # noqa: BLE001
        version = "unknown"
    return {"hermes_version": version, "adapter": "bob-hermes-adapter/1.3", "tools": []}


# ── Task-completion protocol ─────────────────────────────────────────
# Hermes ends a turn whenever the model emits text without tool calls —
# including mid-work narration ("let me browse the web…"). Bob Lab's loop
# must only re-engage when the TASK is done, so each task runs as a
# continuation loop on ONE in-memory AIAgent: keep sending "continue" until
# Hermes ends a reply with TASK_DONE (or asks the operator via NEEDS_INPUT),
# then return that as the single final result.

TASK_DONE = "TASK_DONE"
NEEDS_INPUT = "NEEDS_INPUT:"

_PROTOCOL = (
    "\n\n---\n"
    "Operating protocol (you are driven non-interactively by Bob Lab):\n"
    "- Work this task to completion in this session. If you stop early you "
    "will simply receive 'continue'.\n"
    f"- When the task is FULLY complete, end your final message with a last "
    f"line containing exactly: {TASK_DONE}\n"
    f"- If you are blocked and need operator input, end with a last line: "
    f"{NEEDS_INPUT} <your question>\n"
    "- Never end with narration about what you are about to do."
)

_CONTINUE_MSG = (
    "continue"
    f" (reminder: when the task is fully complete, end with a last line {TASK_DONE};"
    f" if blocked, end with {NEEDS_INPUT} <question>)"
)


def _check_markers(reply: str) -> tuple[bool, bool, str]:
    """Return (done, blocked, cleaned_reply).

    Markers count ONLY on the last two non-empty lines (so merely mentioning
    the protocol mid-text never ends the task), tolerating markdown wrapping
    (e.g. **TASK_DONE**). TASK_DONE lines are stripped from the reply; a
    NEEDS_INPUT line is kept so the operator sees the question.
    """
    lines = (reply or "").rstrip().splitlines()
    nonempty = [i for i, line in enumerate(lines) if line.strip()]
    tail = set(nonempty[-2:])
    done = blocked = False
    kept: list[str] = []
    for i, line in enumerate(lines):
        bare = line.strip().strip("*_`# ").strip()
        if i in tail and (bare == TASK_DONE or bare.endswith(TASK_DONE)):
            done = True
            remainder = bare[: -len(TASK_DONE)].strip().strip("*_`# ").strip()
            if remainder:
                kept.append(remainder)
            continue
        if i in tail and bare.upper().startswith(NEEDS_INPUT):
            blocked = True
        kept.append(line)
    return done, blocked, "\n".join(kept).strip()


@app.post("/v1/agent/run")
async def run(payload: RunIn):
    if _import_error:
        raise HTTPException(503, f"Hermes unavailable: {_import_error}")
    if not payload.instruction.strip():
        raise HTTPException(400, "instruction is empty")

    conn = _hermes_connection(payload.model)
    options = payload.options or {}

    def _make_agent():
        from run_agent import AIAgent

        return AIAgent(
            base_url=conn["base_url"],
            api_key=conn["api_key"],
            provider=conn["provider"],
            model=conn["model"],
            max_iterations=int(options.get("max_iterations", 30)),
            quiet_mode=True,
            session_id=str(options.get("session_id") or "boblab"),
            ephemeral_system_prompt=(payload.system_prompt or None),
        )

    def _turn():
        try:
            agent = _make_agent()
        except ValueError as exc:
            # Hermes enforces a 64K-context minimum and points at the
            # model.context_length config override. Bob Lab operators pick
            # models from their whole fleet (many report 32K), so apply the
            # documented override once and retry — with a logged warning,
            # since Hermes will assume more headroom than the model has.
            if "context window" in str(exc) and "below the minimum" in str(exc):
                _write_context_override(65536)
                logger.warning(
                    "Model %s under Hermes' 64K context minimum — applied "
                    "model.context_length override (%s)",
                    conn["model"],
                    exc,
                )
                agent = _make_agent()
            else:
                raise

        sid = str(options.get("session_id") or "boblab")
        history = _get_history(sid)
        max_rounds = 1 + max(0, int(options.get("max_continuations", 6)))
        message = payload.instruction + _PROTOCOL
        reply, steps = "", []

        try:
            for round_no in range(1, max_rounds + 1):
                result = agent.run_conversation(message, conversation_history=list(history))
                # run_conversation returns a rich dict (final_response,
                # messages, token counts, turn_exit_reason, ...) — or
                # occasionally a plain string.
                if isinstance(result, dict):
                    reply = result.get("final_response") or ""
                    exit_reason = str(result.get("turn_exit_reason", ""))
                    turn_failed = bool(result.get("failed", False))
                    api_calls = int(result.get("api_calls") or 0)
                    turn_msgs = result.get("messages") or []
                    reasoning = str(result.get("last_reasoning") or "")[:300]
                    tools_used = sorted(
                        {
                            tc.get("function", {}).get("name") or tc.get("name") or "?"
                            for m in turn_msgs
                            if isinstance(m, dict)
                            for tc in (m.get("tool_calls") or [])
                            if isinstance(tc, dict)
                        }
                    )
                else:
                    reply = result if isinstance(result, str) else str(result or "")
                    exit_reason, turn_failed, api_calls = "", False, 0
                    turn_msgs, reasoning, tools_used = [], "", []

                _append_turn_messages(history, turn_msgs)
                done, blocked, cleaned = _check_markers(reply)
                steps.append(
                    {
                        "type": "turn",
                        "round": round_no,
                        "exit_reason": exit_reason,
                        "api_calls": api_calls,
                        "tools": tools_used,
                        "reasoning": reasoning,
                        "task_done": done,
                        "needs_input": blocked,
                    }
                )
                if done or blocked or turn_failed or not reply.strip():
                    reply = cleaned if (done or blocked) else reply
                    break
                logger.info("round %d ended without %s — continuing", round_no, TASK_DONE)
                message = _CONTINUE_MSG
            else:
                steps.append(
                    {"type": "note", "detail": f"max_continuations reached ({max_rounds})"}
                )
        finally:
            _save_history(sid)

        usage = {
            "tokens_in": int(getattr(agent, "session_prompt_tokens", 0) or 0),
            "tokens_out": int(getattr(agent, "session_completion_tokens", 0) or 0),
        }
        return reply, usage, steps

    async with _run_lock:
        logger.info(
            "turn start (model=%s via %s)", conn["model"], conn["base_url"] or conn["provider"]
        )
        try:
            reply, usage, steps = await asyncio.to_thread(_turn)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Hermes turn failed")
            raise HTTPException(500, f"Hermes run failed: {exc}")

    if not isinstance(reply, str):
        reply = str(reply or "")
    logger.info(
        "turn done (%d chars, in=%d out=%d)", len(reply), usage["tokens_in"], usage["tokens_out"]
    )
    return {"content": reply, "usage": usage, "steps": steps}
