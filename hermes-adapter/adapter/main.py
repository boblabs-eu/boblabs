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
import base64
import logging
import os
import threading
import time
from importlib import metadata
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
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
    resources: list[dict] = []  # operator-attached input files: {name, content_b64, size_bytes?}


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


# ── The agent's persistent workspace (cwd) + operator file I/O ───────
# TERMINAL_CWD (set in the image) pins Hermes' working directory HERE, on its
# own ~/.hermes volume, so everything it builds — projects, renders, scripts —
# is durable AND captured, instead of scattering to /tmp (invisible + wiped).
# Operator-attached inputs are written straight into the workspace so the agent
# reads them from its cwd; whatever it creates/changes THIS turn is captured
# back as OUTPUTS. The workspace is NOT cleared between turns — it accumulates
# the agent's work, exactly like a native Hermes project dir.
WORKSPACE = Path(os.environ.get("TERMINAL_CWD") or (Path.home() / ".hermes" / "workspace"))

_MAX_OUTPUT_FILE_BYTES = 20 * 1024 * 1024
_MAX_OUTPUT_TOTAL_BYTES = 50 * 1024 * 1024
# Never captured as outputs: dependency trees, VCS, virtualenvs, build
# intermediates, and the redirected tool caches (all under ~/.hermes/cache|data).
_CAPTURE_EXCLUDE_DIRS = {
    "node_modules", ".git", ".venv", "venv", "__pycache__", ".cache", ".npm",
    ".bun", "dist", "build", ".next", ".turbo", ".pytest_cache", ".mypy_cache",
}


def _ensure_workspace() -> None:
    """Create the workspace + redirected cache dirs on the mounted volume.
    A build-time mkdir is hidden by the runtime volume mount, so do it here —
    and before TERMINAL_CWD is resolved, or Hermes falls back to the launch dir."""
    dirs = [WORKSPACE]
    for var in ("XDG_CACHE_HOME", "XDG_DATA_HOME", "BUN_INSTALL", "npm_config_cache", "PIP_CACHE_DIR"):
        val = os.environ.get(var)
        if val:
            dirs.append(Path(val))
    for d in dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("could not create dir %s: %s", d, exc)
    # Anchor the process cwd to the workspace too. TERMINAL_CWD already pins the
    # tools' cwd, but a few tool paths fall back to os.getcwd() if TERMINAL_CWD is
    # ever unset/invalid — chdir'ing here keeps that fallback on the captured
    # volume instead of the adapter's launch dir. Adapter I/O is all absolute paths,
    # so this is safe.
    try:
        if WORKSPACE.is_dir():
            os.chdir(WORKSPACE)
    except OSError as exc:
        logger.warning("could not chdir to workspace %s: %s", WORKSPACE, exc)


@app.on_event("startup")
async def _prepare_workspace():
    _ensure_workspace()


def _safe_name(name: str) -> str:
    """Strip any directory component — defeats ``../`` and absolute-path tricks."""
    return os.path.basename((name or "").strip())


def _materialize_inputs(resources: list[dict]) -> list[str]:
    """Write operator-attached inputs into the workspace (the agent's cwd).
    Returns the basenames written, so the capture step won't echo them back."""
    _ensure_workspace()
    names: list[str] = []
    for item in resources or []:
        if not isinstance(item, dict):
            continue
        name = _safe_name(item.get("name", ""))
        b64 = item.get("content_b64")
        if not name or not isinstance(b64, str):
            continue
        try:
            data = base64.b64decode(b64)
        except (ValueError, TypeError):
            logger.warning("input '%s' is not valid base64 — skipped", name)
            continue
        try:
            (WORKSPACE / name).write_bytes(data)
        except OSError as exc:
            logger.warning("could not write input '%s': %s", name, exc)
            continue
        names.append(name)
    return names


def _build_workspace_preamble(input_names: list[str]) -> str:
    """Workspace/delivery directive prepended to EVERY task (not only when inputs
    exist). Native Hermes already pins the cwd here via TERMINAL_CWD, but the model
    still defaults to /tmp for scratch projects — and only the workspace is captured
    and persisted. So state the delivery contract explicitly: build here, or the
    deliverable is invisible to the operator and wiped on recreate. The input listing
    is appended only when operator files were attached."""
    lines = [
        "<workspace>",
        f"Your working directory is {WORKSPACE} — you are already in it.",
        "Build EVERYTHING for this task here: create projects, scripts, renders and",
        "final deliverables in this directory (use relative paths, or absolute paths",
        "UNDER this directory). Anything you create here is saved and handed back to",
        "the operator.",
        "Files you write to /tmp, /root, or anywhere OUTSIDE this directory are",
        "EPHEMERAL: they are NOT delivered to the operator and are wiped when the",
        "container is recreated. Do not put deliverables there.",
    ]
    if input_names:
        listing = "\n".join(f"- {n}" for n in input_names)
        lines += [
            "",
            "Files provided for THIS task are already here in your working directory:",
            listing,
            "Read/run them by name (e.g. `read_file` or `python <file>`). Do NOT assume",
            "they live in a git repo or anywhere else.",
        ]
    lines.append("</workspace>\n\n")
    return "\n".join(lines)


def _is_excluded(rel: Path) -> bool:
    return any(part in _CAPTURE_EXCLUDE_DIRS for part in rel.parts)


def _collect_outputs(since: float, input_names: list[str]) -> list[dict]:
    """Capture files the agent created/changed in the workspace THIS turn, as
    ``[{name, content_b64, size_bytes}]`` with paths relative to the workspace.
    Skips dependency/cache dirs and the just-written inputs; size-capped."""
    results: list[dict] = []
    total = 0
    if not WORKSPACE.is_dir():
        return results
    skip = set(input_names)
    for fp in sorted(WORKSPACE.rglob("*")):
        if not fp.is_file():
            continue
        rel = fp.relative_to(WORKSPACE)
        if _is_excluded(rel) or rel.name in skip:
            continue
        try:
            st = fp.stat()
            if st.st_mtime < since:
                continue  # untouched this turn
            if st.st_size > _MAX_OUTPUT_FILE_BYTES:
                logger.warning("output '%s' skipped: %d bytes over cap", rel, st.st_size)
                continue
            if total + st.st_size > _MAX_OUTPUT_TOTAL_BYTES:
                logger.warning("output '%s' skipped: total over cap", rel)
                continue
            data = fp.read_bytes()
        except OSError as exc:
            logger.warning("could not read output '%s': %s", rel, exc)
            continue
        total += len(data)
        results.append(
            {
                "name": str(rel),
                "content_b64": base64.b64encode(data).decode("ascii"),
                "size_bytes": len(data),
            }
        )
    return results


# ── Native Hermes cron, driven by Bob ───────────────────────────────
# Hermes' scheduler tick() is standalone + file-locked and expects an external
# ~60s heartbeat (normally the gateway's). Bob's control-plane loop is that
# heartbeat here: it POSTs /v1/cron/tick to run due jobs and GETs /v1/cron/output
# to surface results into the lab feed. Autonomous job runs read their model from
# ~/.hermes/config.yaml, which the adapter keeps pointed at Bob's LLM gateway.
_AGENT_SECRET = os.environ.get("AGENT_SECRET", "")
_CRON_OUTPUT_DIR = Path.home() / ".hermes" / "cron" / "output"
_JOBS_FILE = Path.home() / ".hermes" / "cron" / "jobs.json"


def _check_cron_auth(authorization: str | None) -> None:
    """Bearer-token check mirroring bob-api's llm-gateway. When AGENT_SECRET is
    unset (dev) allow — same compat posture as the gateway."""
    if not _AGENT_SECRET:
        return
    if authorization != f"Bearer {_AGENT_SECRET}":
        raise HTTPException(401, "unauthorized")


def _persist_model_config(conn: dict) -> None:
    """Mirror the per-request model into ~/.hermes/config.yaml so AUTONOMOUS cron
    runs (run_job reads it fresh each tick) reach the same provider — Bob's LLM
    gateway — with the model the operator last selected. Other keys preserved."""
    import yaml

    cfg_path = Path.home() / ".hermes" / "config.yaml"
    cfg: dict = {}
    if cfg_path.exists():
        try:
            cfg = yaml.safe_load(cfg_path.read_text()) or {}
        except Exception:  # noqa: BLE001 — corrupt config: rebuild the model key
            cfg = {}
    if not isinstance(cfg.get("model"), dict):
        cfg["model"] = {}
    m = cfg["model"]
    m["default"] = conn["model"]
    m["base_url"] = conn.get("base_url") or ""
    if conn.get("api_key"):
        m["api_key"] = conn["api_key"]
    # Persist Bob's OpenAI-compatible gateway as Hermes' generic "custom" provider
    # — NOT "openai". "openai" is not in Hermes' PROVIDER_REGISTRY, so an autonomous
    # cron run (run_job inherits the provider from here when the job pins none) would
    # raise "Unknown provider 'openai'". With provider="custom", base_url + api_key
    # resolve to the same chat_completions runtime the interactive path uses
    # (resolve_runtime_provider trusts a config base_url once the provider is custom).
    # Anthropic stays anthropic.
    m["provider"] = conn.get("provider") or "custom"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cfg_path.write_text(yaml.safe_dump(cfg))
    except OSError as exc:
        logger.warning("could not persist model config: %s", exc)


def _count_cron_jobs() -> int:
    """How many cron jobs the agent currently has (any state). Bob uses this to
    auto-activate — keep the container always-on while it has schedules."""
    try:
        import json

        data = json.loads(_JOBS_FILE.read_text())
        jobs = data.get("jobs", []) if isinstance(data, dict) else data
        return len(jobs) if isinstance(jobs, list) else 0
    except Exception:  # noqa: BLE001 — missing/corrupt = no jobs
        return 0


@app.post("/v1/cron/tick")
async def cron_tick(authorization: str | None = Header(default=None)):
    """Run due cron jobs once (fire-and-forget — a job can take minutes). Bob's
    scheduler loop calls this each poll as the native scheduler's external
    heartbeat. tick() is file-locked, so overlapping calls are safe (a second
    tick returns 0 while one is running)."""
    _check_cron_auth(authorization)
    if _import_error:
        raise HTTPException(503, f"Hermes unavailable: {_import_error}")

    def _do_tick():
        try:
            from cron.scheduler import tick

            ran = tick(verbose=False)
            if ran:
                logger.info("cron tick ran %d job(s)", ran)
        except Exception:  # noqa: BLE001
            logger.exception("cron tick failed")

    threading.Thread(target=_do_tick, daemon=True).start()
    return {"triggered": True}


@app.get("/v1/cron/output")
async def cron_output(since: float = 0.0, authorization: str | None = Header(default=None)):
    """Cron job outputs written since ``since`` (epoch seconds). Bob polls this
    and posts new entries to the lab feed. Output lives at
    ~/.hermes/cron/output/{job_id}/{timestamp}.md."""
    _check_cron_auth(authorization)
    results: list[dict] = []
    if _CRON_OUTPUT_DIR.is_dir():
        for fp in sorted(_CRON_OUTPUT_DIR.rglob("*.md")):
            if not fp.is_file():
                continue
            try:
                st = fp.stat()
                if st.st_mtime <= since:
                    continue
                content = fp.read_text(errors="replace")[:_MAX_OUTPUT_FILE_BYTES]
            except OSError:
                continue
            results.append(
                {"job_id": fp.parent.name, "file": fp.name, "mtime": st.st_mtime, "content": content}
            )
    return {"outputs": results, "now": time.time()}


@app.post("/v1/agent/run")
async def run(payload: RunIn):
    if _import_error:
        raise HTTPException(503, f"Hermes unavailable: {_import_error}")
    if not payload.instruction.strip():
        raise HTTPException(400, "instruction is empty")

    conn = _hermes_connection(payload.model)
    options = payload.options or {}
    # Keep ~/.hermes/config.yaml pointed at the operator's current model so any
    # cron jobs run autonomously through the same provider (Bob's LLM gateway).
    _persist_model_config(conn)

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
        input_names = _materialize_inputs(payload.resources)
        message = _build_workspace_preamble(input_names) + payload.instruction + _PROTOCOL
        turn_start = time.time()
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

        outputs = _collect_outputs(turn_start, input_names)
        usage = {
            "tokens_in": int(getattr(agent, "session_prompt_tokens", 0) or 0),
            "tokens_out": int(getattr(agent, "session_completion_tokens", 0) or 0),
        }
        return reply, usage, steps, outputs

    async with _run_lock:
        logger.info(
            "turn start (model=%s via %s)", conn["model"], conn["base_url"] or conn["provider"]
        )
        try:
            reply, usage, steps, outputs = await asyncio.to_thread(_turn)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Hermes turn failed")
            raise HTTPException(500, f"Hermes run failed: {exc}")

    if not isinstance(reply, str):
        reply = str(reply or "")
    logger.info(
        "turn done (%d chars, in=%d out=%d, %d output file(s))",
        len(reply),
        usage["tokens_in"],
        usage["tokens_out"],
        len(outputs),
    )
    return {
        "content": reply,
        "usage": usage,
        "steps": steps,
        "outputs": outputs,
        "cron_jobs": _count_cron_jobs(),
    }
