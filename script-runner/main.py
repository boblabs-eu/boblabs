"""Bob Script Runner — GPU-side service for heavy model execution.

Discovers executable scripts from a configurable directory and exposes
them as HTTP endpoints.  Each script follows a convention:
  - A docstring with BOB_SCRIPT_META JSON defining name, description, parameters
  - An optional "env" field in metadata specifying the Python interpreter:
      "env": "conda:riffusion_old"         → uses conda run -n ...
      "env": "/path/to/.venv"              → uses /path/to/.venv/bin/python
      "env": "/path/to/.venv/bin/python"   → used directly
    If omitted, uses the system python3.
  - A ``run(args: dict, output_dir: str) -> dict`` entry point

Scripts are executed as **subprocesses** so each can use its own virtualenv
with the correct dependencies and CUDA libraries.

The control-plane calls POST /scripts/{name}/run and receives results
plus base64-encoded output files.

Runs directly on the GPU server (not in Docker) so it has full CUDA access.
"""

import asyncio
import base64
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bob-script-runner")

SCRIPTS_DIR = Path(os.environ.get("BOB_SCRIPTS_DIR", "/opt/bob-scripts"))
OUTPUT_ROOT = Path(os.environ.get("BOB_SCRIPTS_OUTPUT", "/tmp/bob-script-output"))
MAX_OUTPUT_SIZE_MB = int(os.environ.get("BOB_SCRIPTS_MAX_OUTPUT_MB", "100"))

__version__ = "0.1.0"

app = FastAPI(title="bob-script-runner", version=__version__, docs_url=None, redoc_url=None)

# ── Script discovery helpers ──────────────────────

_META_MARKER = "BOB_SCRIPT_META:"


def _extract_json_block(text: str, start: int) -> str | None:
    """Extract a balanced JSON object starting at position *start* (must be '{')."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            if in_string:
                escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _parse_script_meta(path: Path) -> dict | None:
    """Extract BOB_SCRIPT_META JSON from a script's docstring."""
    try:
        source = path.read_text()
    except Exception:
        return None

    idx = source.find(_META_MARKER)
    if idx == -1:
        return None
    # Find the opening brace after the marker
    brace_start = source.find("{", idx + len(_META_MARKER))
    if brace_start == -1:
        return None
    raw = _extract_json_block(source, brace_start)
    if raw is None:
        logger.warning("Unbalanced braces in BOB_SCRIPT_META of %s", path.name)
        return None
    try:
        meta = json.loads(raw)
        meta["_path"] = str(path)
        return meta
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in BOB_SCRIPT_META of %s", path.name)
        return None


# P08 — cache the discovery scan and invalidate on mtime drift. The
# previous implementation re-stat'd every file on every request, which
# adds a meaningful penalty on a busy GPU box with dozens of scripts on
# a slow disk. Cache shape:
#   { signature: tuple[(name, mtime_ns)], result: dict[name, meta] }
# ``signature`` is recomputed on every call (cheap — one ``scandir``
# per call) and compared against the cached one. If the set of script
# files or any mtime has changed, we rescan; otherwise we return the
# cached dict.
_DISCOVERY_CACHE: dict[str, Any] = {"signature": None, "result": {}}


def _scripts_dir_signature() -> tuple[tuple[str, int], ...] | None:
    """Lightweight fingerprint of the scripts dir (sorted name+mtime)."""
    if not SCRIPTS_DIR.is_dir():
        return None
    entries: list[tuple[str, int]] = []
    try:
        with os.scandir(SCRIPTS_DIR) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                if not entry.name.endswith(".py") or entry.name.startswith("_"):
                    continue
                try:
                    st = entry.stat()
                except OSError:
                    continue
                entries.append((entry.name, st.st_mtime_ns))
    except OSError:
        return None
    entries.sort()
    return tuple(entries)


def discover_scripts() -> dict[str, dict]:
    """Scan SCRIPTS_DIR for valid scripts and return {name: meta}.

    P08 — result is cached by ``(filename, mtime_ns)`` so a request that
    arrives with no on-disk drift returns the cached dict without
    re-parsing.
    """
    signature = _scripts_dir_signature()
    if signature is None:
        logger.warning("Scripts directory does not exist: %s", SCRIPTS_DIR)
        _DISCOVERY_CACHE["signature"] = None
        _DISCOVERY_CACHE["result"] = {}
        return {}
    if _DISCOVERY_CACHE["signature"] == signature and _DISCOVERY_CACHE["result"]:
        return _DISCOVERY_CACHE["result"]

    scripts: dict[str, dict] = {}
    for fname, _mtime in signature:
        py_file = SCRIPTS_DIR / fname
        meta = _parse_script_meta(py_file)
        if meta:
            name = meta.get("name", py_file.stem)
            scripts[name] = meta
            logger.info("Discovered script: %s (%s) env=%s", name, py_file.name, meta.get("env", "system"))
        else:
            logger.debug("Skipping %s (no BOB_SCRIPT_META)", py_file.name)

    _DISCOVERY_CACHE["signature"] = signature
    _DISCOVERY_CACHE["result"] = scripts
    return scripts


def _find_conda() -> str | None:
    """Find the conda binary, searching common locations."""
    import shutil
    conda = shutil.which("conda")
    if conda:
        return conda
    # Search common install locations
    for pattern in [
        Path.home() / "miniconda3" / "bin" / "conda",
        Path.home() / "anaconda3" / "bin" / "conda",
        Path.home() / "miniforge3" / "bin" / "conda",
        Path("/opt/conda/bin/conda"),
    ]:
        if pattern.is_file():
            return str(pattern)
    # Broader search across /home
    for p in Path("/home").glob("*/miniconda3/bin/conda"):
        if p.is_file():
            return str(p)
    for p in Path("/home").glob("*/anaconda3/bin/conda"):
        if p.is_file():
            return str(p)
    return None


# Cache conda path at startup
_CONDA_BIN = _find_conda()
if _CONDA_BIN:
    logger.info("Found conda: %s", _CONDA_BIN)


def _resolve_python(env_spec: str | None) -> list[str]:
    """Resolve the env spec to a command prefix for subprocess execution.

    Supports:
      - None / ""               -> ["python3"]
      - "conda:<env_name>"      -> ["/path/to/conda", "run", "--no-capture-output", "-n", "<env_name>", "python"]
      - "/path/to/.venv"        -> ["/path/to/.venv/bin/python"]
      - "/path/to/bin/python"   -> ["/path/to/bin/python"]
    """
    if not env_spec:
        return ["python3"]

    if env_spec.startswith("conda:"):
        env_name = env_spec[6:].strip()
        if not _CONDA_BIN:
            logger.error("conda env '%s' requested but conda not found on this system", env_name)
            return ["python3"]
        return [_CONDA_BIN, "run", "--no-capture-output", "-n", env_name, "python"]

    p = Path(env_spec)
    # Direct path to a python binary
    if p.is_file() and os.access(str(p), os.X_OK):
        return [str(p)]
    # Path to a venv directory — use its bin/python
    venv_python = p / "bin" / "python"
    if venv_python.is_file():
        return [str(venv_python)]

    logger.warning("Cannot resolve env '%s', falling back to system python3", env_spec)
    return ["python3"]


# ── Subprocess wrapper script ─────────────────────

_WRAPPER_TEMPLATE = '''\
import json, sys, os, importlib.util
sys.path.insert(0, os.path.dirname(SCRIPT_PATH))
spec = importlib.util.spec_from_file_location("bob_target", SCRIPT_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
with open(ARGS_PATH) as f:
    args = json.load(f)
try:
    result = mod.run(args, OUTPUT_DIR)
except Exception as e:
    result = {"success": False, "message": f"Script error: {e}"}
with open(RESULT_PATH, "w") as f:
    json.dump(result, f)
'''


def _build_wrapper(script_path: str, args_path: str, output_dir: str, result_path: str) -> str:
    """Build the wrapper script with paths substituted."""
    code = _WRAPPER_TEMPLATE
    code = code.replace("SCRIPT_PATH", repr(script_path))
    code = code.replace("ARGS_PATH", repr(args_path))
    code = code.replace("OUTPUT_DIR", repr(output_dir))
    code = code.replace("RESULT_PATH", repr(result_path))
    return code


# ── API models ────────────────────────────────────


class ScriptRunRequest(BaseModel):
    arguments: dict[str, Any] = {}
    timeout_sec: int = 300


class ScriptInfo(BaseModel):
    name: str
    description: str = ""
    parameters: dict = {}
    env: str = ""


class ScriptRunResult(BaseModel):
    success: bool
    message: str = ""
    output_files: list[dict] = []  # [{name, size_bytes, base64}]
    stdout: str = ""
    duration_sec: float = 0.0


# ── Endpoints ─────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok", "version": __version__, "scripts_dir": str(SCRIPTS_DIR)}


@app.get("/scripts", response_model=list[ScriptInfo])
async def list_scripts():
    """Return all discovered scripts with their metadata."""
    scripts = discover_scripts()
    return [
        ScriptInfo(
            name=name,
            description=meta.get("description", ""),
            parameters=meta.get("parameters", {}),
            env=meta.get("env", ""),
        )
        for name, meta in scripts.items()
    ]


@app.post("/scripts/{script_name}/run", response_model=ScriptRunResult)
async def run_script(script_name: str, req: ScriptRunRequest):
    """Execute a script by name with the given arguments."""
    scripts = discover_scripts()
    meta = scripts.get(script_name)
    if not meta:
        raise HTTPException(404, f"Script not found: {script_name}")

    script_path = meta["_path"]
    env_spec = meta.get("env")
    output_dir = OUTPUT_ROOT / f"{script_name}_{int(time.time())}_{os.getpid()}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Prepare temp files for IPC
    args_path = str(output_dir / "_args.json")
    result_path = str(output_dir / "_result.json")
    wrapper_path = output_dir / "_wrapper.py"

    Path(args_path).write_text(json.dumps(req.arguments))
    wrapper_code = _build_wrapper(script_path, args_path, str(output_dir), result_path)
    wrapper_path.write_text(wrapper_code)

    # Resolve Python interpreter
    cmd_prefix = _resolve_python(env_spec)
    cmd = cmd_prefix + [str(wrapper_path)]

    logger.info("Running script '%s': %s", script_name, " ".join(cmd))
    start = time.monotonic()

    try:
        proc = await asyncio.wait_for(
            _run_subprocess(cmd, output_dir),
            timeout=req.timeout_sec,
        )
    except asyncio.TimeoutError:
        _cleanup(output_dir)
        return ScriptRunResult(
            success=False,
            message=f"Script timed out after {req.timeout_sec}s",
            duration_sec=time.monotonic() - start,
        )
    except Exception as e:
        _cleanup(output_dir)
        logger.exception("Script '%s' crashed", script_name)
        return ScriptRunResult(
            success=False,
            message=f"Script execution error: {e}",
            duration_sec=time.monotonic() - start,
        )

    duration = time.monotonic() - start

    # Read result JSON
    result = {}
    if Path(result_path).is_file():
        try:
            result = json.loads(Path(result_path).read_text())
        except json.JSONDecodeError:
            result = {"success": False, "message": "Script returned invalid JSON"}
    else:
        result = {
            "success": False,
            "message": f"Script crashed (exit code {proc['returncode']}). stderr: {proc['stderr'][:2000]}",
        }

    # Collect output files (skip internal temp files starting with _)
    output_files = []
    max_bytes = MAX_OUTPUT_SIZE_MB * 1024 * 1024
    total_size = 0
    for f in sorted(output_dir.iterdir()):
        if f.is_file() and not f.name.startswith("_"):
            size = f.stat().st_size
            if total_size + size > max_bytes:
                logger.warning("Skipping %s: would exceed max output size", f.name)
                continue
            total_size += size
            output_files.append({
                "name": f.name,
                "size_bytes": size,
                "base64": base64.b64encode(f.read_bytes()).decode(),
            })

    stdout_text = proc.get("stdout", "")
    if proc.get("stderr"):
        stdout_text += f"\nSTDERR:\n{proc['stderr']}" if stdout_text else proc["stderr"]

    _cleanup(output_dir)

    return ScriptRunResult(
        success=result.get("success", False),
        message=result.get("message", ""),
        output_files=output_files,
        stdout=stdout_text[:10000],
        duration_sec=round(duration, 2),
    )


# R18 — stdout/stderr are streamed line-by-line into bounded buffers so a
# chatty script (think tqdm or transformers warm-up logs) can't OOM the
# script-runner. Per-stream cap defaults to 1 MiB; older output is
# discarded once the cap is hit and a single ``[truncated …]`` marker
# is appended. The container-wide ``stdout_text[:10000]`` slice that
# the run handler already applies still wins for the final response,
# so this is purely about peak memory during execution.
_SUBPROCESS_STREAM_CAP_BYTES = int(os.environ.get("BOB_SCRIPTS_STREAM_CAP_BYTES", str(1024 * 1024)))


async def _drain_stream(stream: asyncio.StreamReader, cap_bytes: int) -> bytes:
    """Read ``stream`` line-by-line until EOF, returning at most
    ``cap_bytes`` of head data plus a truncation marker on overflow."""
    chunks: list[bytes] = []
    used = 0
    overflow = False
    marker = b"\n[truncated: stream cap reached]\n"
    while True:
        line = await stream.readline()
        if not line:
            break
        if overflow:
            # Keep draining so the subprocess doesn't block on a full pipe.
            continue
        room = cap_bytes - used
        if len(line) > room:
            if room > 0:
                chunks.append(line[:room])
                used += room
            chunks.append(marker)
            overflow = True
            continue
        chunks.append(line)
        used += len(line)
    return b"".join(chunks)


async def _run_subprocess(cmd: list[str], cwd: Path) -> dict:
    """Run a command as an async subprocess, return stdout/stderr/returncode."""
    # Inherit env and forward HF_TOKEN for gated model access
    child_env = {**os.environ}
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if hf_token:
        child_env["HF_TOKEN"] = hf_token
        child_env["HUGGING_FACE_HUB_TOKEN"] = hf_token
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd),
        env=child_env,
    )
    # R18 — drain both streams concurrently with per-stream caps so a
    # chatty subprocess doesn't buffer hundreds of MB into Python.
    stdout_task = asyncio.create_task(_drain_stream(proc.stdout, _SUBPROCESS_STREAM_CAP_BYTES))
    stderr_task = asyncio.create_task(_drain_stream(proc.stderr, _SUBPROCESS_STREAM_CAP_BYTES))
    stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
    await proc.wait()
    return {
        "returncode": proc.returncode,
        "stdout": stdout.decode(errors="replace") if stdout else "",
        "stderr": stderr.decode(errors="replace") if stderr else "",
    }


def _cleanup(path: Path):
    """Remove temp output directory."""
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("BOB_SCRIPTS_PORT", "9101"))
    uvicorn.run(app, host="0.0.0.0", port=port)
