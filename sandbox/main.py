"""Sandbox service — isolated execution of python_exec and shell_exec.

Runs in a separate container with NO access to the API, DB, or secrets.
Only has access to the lab_resources volume.
"""

import asyncio
import ipaddress
import json
import logging
import os
import re
import shlex
import socket
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("sandbox")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="bob-sandbox", docs_url=None, redoc_url=None)

LAB_RESOURCES_ROOT = Path(os.environ.get("LAB_RESOURCES_PATH", "/data/lab_resources"))

SHELL_WHITELIST = {
    "curl", "wget", "python3", "python", "pip", "pip3",
    "cat", "head", "tail", "wc", "grep", "awk", "sed", "sort", "uniq",
    "ls", "find", "echo", "date", "whoami", "uname", "pwd",
    "jq", "bc", "tr", "cut", "tee", "xargs",
    # Audio/video tools
    "ffmpeg", "ffprobe",
    # YouTube download
    "yt-dlp",
    # CAD tools
    "freecadcmd", "freecad", "kicad-cli",
}


class ExecRequest(BaseModel):
    lab_id: str
    timeout_sec: int = 60
    max_output_kb: int = 256


class PythonExecRequest(ExecRequest):
    code: str


class ShellExecRequest(ExecRequest):
    command: str


class DbRequest(BaseModel):
    lab_id: str
    timeout_sec: int = 30
    max_output_kb: int = 256


class DbSqlRequest(DbRequest):
    sql: str
    params: list[Any] | None = None


def _workspace(lab_id: str) -> Path:
    """Resolve and validate workspace path for a lab.

    A09 — segment-aware containment via ``Path.is_relative_to``. The
    previous ``str(ws).startswith(str(root))`` was technically vulnerable
    to a sibling-prefix collision (``/data/lab_resources`` vs
    ``/data/lab_resources_evil``); UUIDs make this practically
    impossible but the safer primitive costs nothing.
    """
    ws = (LAB_RESOURCES_ROOT / lab_id).resolve()
    if not ws.is_relative_to(LAB_RESOURCES_ROOT.resolve()):
        raise HTTPException(400, "Invalid lab_id")
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "output").mkdir(exist_ok=True)
    return ws


def _truncate(text: str, max_kb: int) -> str:
    limit = max_kb * 1024
    if len(text) > limit:
        return text[:limit] + "\n... [output truncated]"
    return text


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/python_exec")
async def python_exec(req: PythonExecRequest):
    ws = _workspace(req.lab_id)
    # R07 — fixed `_exec_tmp.py` raced when two python_exec calls hit the
    # same lab concurrently (e.g. an agent firing parallel tool calls).
    # Use a per-request UUID-suffix file so the two runs cannot clobber
    # each other's script source. `tempfile.NamedTemporaryFile` would
    # work too but keeping the file inside the workspace preserves the
    # behaviour that `import` from sibling files (via PYTHONPATH=ws)
    # continues to resolve.
    import uuid as _uuid
    script_path = ws / f"_exec_tmp_{_uuid.uuid4().hex}.py"
    script_path.write_text(req.code)

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ws),
            env={
                "HOME": os.environ.get("HOME", "/home/sandbox"),
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(ws),
                "OUTPUT_DIR": str(ws / "output"),
            },
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=req.timeout_sec
        )
        parts = []
        if stdout:
            parts.append(stdout.decode(errors="replace"))
        if stderr:
            parts.append(f"STDERR:\n{stderr.decode(errors='replace')}")
        output = "\n".join(parts) if parts else "(no output)"
        return {
            "success": proc.returncode == 0,
            "output": _truncate(output, req.max_output_kb),
        }
    except asyncio.TimeoutError:
        # R07 — actually await the killed process so it doesn't linger
        # as a zombie under the asyncio child watcher.
        if proc is not None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        return {"success": False, "output": f"Python execution timed out after {req.timeout_sec}s"}
    except Exception as e:
        logger.exception("python_exec failed for lab %s", req.lab_id)
        return {"success": False, "output": f"Execution error: {e}"}
    finally:
        try:
            script_path.unlink(missing_ok=True)
        except Exception:
            pass


@app.post("/shell_exec")
async def shell_exec(req: ShellExecRequest):
    ws = _workspace(req.lab_id)

    # Validate: first token must be in whitelist
    try:
        tokens = shlex.split(req.command)
    except ValueError as e:
        return {"success": False, "output": f"Invalid command syntax: {e}"}

    if not tokens:
        return {"success": False, "output": "Empty command."}

    base_cmd = Path(tokens[0]).name
    if base_cmd not in SHELL_WHITELIST:
        return {
            "success": False,
            "output": f"Command '{base_cmd}' not allowed. Whitelisted: {', '.join(sorted(SHELL_WHITELIST))}",
        }

    proc = None
    try:
        proc = await asyncio.create_subprocess_shell(
            req.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ws),
            env={
                "HOME": os.environ.get("HOME", "/home/sandbox"),
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "OUTPUT_DIR": str(ws / "output"),
            },
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=req.timeout_sec
        )
        parts = []
        if stdout:
            parts.append(stdout.decode(errors="replace"))
        if stderr:
            parts.append(f"STDERR:\n{stderr.decode(errors='replace')}")
        output = "\n".join(parts) if parts else "(no output)"
        return {
            "success": proc.returncode == 0,
            "output": _truncate(output, req.max_output_kb),
        }
    except asyncio.TimeoutError:
        # R07 — await the killed process so it doesn't linger as a
        # zombie. Same pattern as python_exec.
        if proc is not None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        return {"success": False, "output": f"Shell execution timed out after {req.timeout_sec}s"}
    except Exception as e:
        logger.exception("shell_exec failed for lab %s", req.lab_id)
        return {"success": False, "output": f"Execution error: {e}"}


# ── YouTube ───────────────────────────────────────

_YOUTUBE_ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be"}

# Path patterns (applied AFTER hostname is verified via urlparse)
_YOUTUBE_VIDEO_PATH_RE = re.compile(
    r'^/(?:watch\?v=|shorts/)[A-Za-z0-9_-]{11}',
)
_YOUTU_BE_PATH_RE = re.compile(
    r'^/[A-Za-z0-9_-]{11}$',
)
_YOUTUBE_CHANNEL_PATH_RE = re.compile(
    r'^/(?:@[\w.-]{1,100}|channel/[A-Za-z0-9_-]{20,30}|c/[\w.-]{1,100})(?:/videos)?/?$',
)


def _is_youtube_video_url(url: str) -> bool:
    """Validate that url points to a single YouTube video (not channel/playlist)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if host not in _YOUTUBE_ALLOWED_HOSTS:
            return False
        if host == "youtu.be":
            return bool(_YOUTU_BE_PATH_RE.match(parsed.path))
        return bool(_YOUTUBE_VIDEO_PATH_RE.match(parsed.path + ("?" + parsed.query if parsed.query else "")))
    except Exception:
        return False


def _is_youtube_channel_url(url: str) -> bool:
    """Validate that url points to a YouTube channel page."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if host not in _YOUTUBE_ALLOWED_HOSTS or host == "youtu.be":
            return False
        return bool(_YOUTUBE_CHANNEL_PATH_RE.match(parsed.path))
    except Exception:
        return False


class YouTubeDownloadRequest(BaseModel):
    lab_id: str
    url: str
    audio_format: str = "mp3"
    timeout_sec: int = 300
    max_output_kb: int = 256


@app.post("/youtube_download")
async def youtube_download(req: YouTubeDownloadRequest):
    """Download audio from a YouTube video URL using yt-dlp.

    Security:
      - URL validated against youtube.com/youtu.be domains only
      - No playlist support (--no-playlist)
      - File size capped (--max-filesize)
      - Timeout enforced
      - Runs in sandbox container with no host access
    """
    ws = _workspace(req.lab_id)

    # Validate URL — only YouTube domains (urlparse hostname check)
    if not _is_youtube_video_url(req.url):
        return {
            "success": False,
            "output": "Invalid URL. Only youtube.com and youtu.be video URLs are allowed.",
        }

    # Validate format
    allowed_formats = {"mp3", "wav", "m4a", "flac", "ogg"}
    fmt = req.audio_format.lower()
    if fmt not in allowed_formats:
        return {
            "success": False,
            "output": f"Invalid format '{fmt}'. Allowed: {', '.join(sorted(allowed_formats))}",
        }

    output_dir = ws / "output"
    output_dir.mkdir(exist_ok=True)
    output_template = str(output_dir / "%(title).80s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--format", "bestaudio",
        "--extract-audio",
        "--audio-format", fmt,
        "--audio-quality", "0",
        "--no-playlist",
        "--restrict-filenames",
        "--max-filesize", "500M",
        "--no-overwrites",
        "--print-json",
        "--no-simulate",
        "-o", output_template,
        req.url,
    ]

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ws),
            env={
                "HOME": os.environ.get("HOME", "/home/sandbox"),
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            },
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=req.timeout_sec
        )
    except asyncio.TimeoutError:
        if proc is not None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        return {"success": False, "output": f"Download timed out after {req.timeout_sec}s"}
    except FileNotFoundError:
        return {"success": False, "output": "yt-dlp not found. Is it installed?"}
    except Exception as e:
        logger.exception("youtube_download failed for lab %s", req.lab_id)
        return {"success": False, "output": f"Download error: {e}"}

    if proc.returncode != 0:
        err = stderr.decode(errors="replace")[-500:]
        return {"success": False, "output": f"yt-dlp failed (rc={proc.returncode}): {err}"}

    # Parse yt-dlp JSON output for metadata
    title = "unknown"
    duration = 0
    try:
        info = json.loads(stdout.decode(errors="replace").strip().split("\n")[-1])
        title = info.get("title", "unknown")
        duration = info.get("duration", 0)
    except (json.JSONDecodeError, IndexError):
        pass

    # Find the downloaded file
    downloaded = None
    for f in sorted(output_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in {f".{fmt}", ".mp3", ".wav", ".m4a", ".flac", ".ogg"}:
            downloaded = f
            break

    if not downloaded or not downloaded.is_file():
        return {"success": False, "output": "Download completed but no audio file found."}

    rel_path = f"output/{downloaded.name}"
    size_bytes = downloaded.stat().st_size

    return {
        "success": True,
        "output": json.dumps({
            "output_path": rel_path,
            "title": title,
            "duration_seconds": duration,
            "filesize_bytes": size_bytes,
            "format": fmt,
        }),
    }


# ── YouTube channel listing ──────────────────────────


class YouTubeChannelListRequest(BaseModel):
    lab_id: str
    channel_url: str
    max_videos: int = 20
    timeout_sec: int = 120


@app.post("/youtube_channel_list")
async def youtube_channel_list(req: YouTubeChannelListRequest):
    """List recent videos from a YouTube channel using yt-dlp --flat-playlist.

    Security:
      - URL validated against youtube.com channel patterns only
      - No downloads (--flat-playlist + --no-download)
      - Result count capped (--playlist-end)
      - Timeout enforced
      - Runs in sandbox container with no host access
    """
    # Validate URL — only YouTube channel patterns (urlparse hostname check)
    if not _is_youtube_channel_url(req.channel_url):
        return {
            "success": False,
            "output": (
                "Invalid channel URL. Accepted formats:\n"
                "  https://www.youtube.com/@handle\n"
                "  https://www.youtube.com/channel/UCxxxx\n"
                "  https://www.youtube.com/c/ChannelName"
            ),
        }

    max_v = max(1, min(req.max_videos, 50))

    # Append /videos to ensure we get the uploads tab
    channel_url = req.channel_url.rstrip("/")
    if not channel_url.endswith("/videos"):
        channel_url += "/videos"

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--no-download",
        "--print-json",
        f"--playlist-end={max_v}",
        "--no-warnings",
        channel_url,
    ]

    # R11 — pin yt-dlp's cwd to the lab workspace so cookies, cache,
    # debug dumps, and other side-effect files land under
    # LAB_RESOURCES_ROOT/<lab_id>/ rather than the container's /app or
    # the bob-sandbox user's $HOME. youtube_download already does this
    # implicitly via cwd=str(ws); youtube_channel_list omitted it.
    ws = _workspace(req.lab_id)

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ws),
            env={
                "HOME": os.environ.get("HOME", "/home/sandbox"),
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            },
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=req.timeout_sec
        )
    except asyncio.TimeoutError:
        if proc is not None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        return {"success": False, "output": f"Channel listing timed out after {req.timeout_sec}s"}
    except FileNotFoundError:
        return {"success": False, "output": "yt-dlp not found. Is it installed?"}
    except Exception as e:
        logger.exception("youtube_channel_list failed for lab %s", req.lab_id)
        return {"success": False, "output": f"Channel listing error: {e}"}

    if proc.returncode != 0:
        err = stderr.decode(errors="replace")[-500:]
        return {"success": False, "output": f"yt-dlp failed (rc={proc.returncode}): {err}"}

    # Parse one JSON object per line
    videos = []
    for line in stdout.decode(errors="replace").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            info = json.loads(line)
        except json.JSONDecodeError:
            continue

        video_id = info.get("id", "")
        title = info.get("title", "Untitled")
        upload_date = info.get("upload_date", "")  # YYYYMMDD or empty

        # Format publish_date as YYYY-MM-DD if available
        pub_date = ""
        if upload_date and len(upload_date) == 8:
            pub_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"

        if video_id:
            videos.append({
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": title,
                "publish_date": pub_date,
            })

    if not videos:
        return {"success": False, "output": "No videos found on this channel."}

    return {
        "success": True,
        "output": json.dumps({
            "channel": req.channel_url,
            "count": len(videos),
            "videos": videos,
        }),
    }


# ── SQLite Database ───────────────────────────────

# Statements that must never run — they can escape the workspace.
_DB_BLOCKED_RE = re.compile(
    r'\b(ATTACH|DETACH|LOAD_EXTENSION)\b',
    re.IGNORECASE,
)

# Statements considered read-only (SELECT, EXPLAIN, PRAGMA without '=').
_DB_READ_ONLY_RE = re.compile(
    r'^\s*(SELECT|EXPLAIN|PRAGMA\s+\w+(?!\s*=))\b',
    re.IGNORECASE,
)

_DB_MAX_ROWS = 500


def _db_path(ws: Path) -> Path:
    """Return the per-lab SQLite database path."""
    return ws / "agent.db"


def _check_blocked(sql: str) -> str | None:
    """Return an error message if the SQL contains a blocked statement."""
    if _DB_BLOCKED_RE.search(sql):
        return "Blocked: ATTACH, DETACH, and LOAD_EXTENSION are not allowed."
    return None


def _sqlite_open(db_file: Path, timeout_sec: int) -> sqlite3.Connection:
    """Open a SQLite connection with both lock-wait + wall-clock query
    timeouts.

    R09 + R10 — ``sqlite3.connect(timeout=...)`` is the *lock-acquisition*
    timeout (busy-wait while another writer holds the file lock); it does
    NOT bound the execution time of a single SELECT. A pathological query
    against a large table previously could block the asyncio event loop
    for minutes. ``set_progress_handler`` is SQLite's documented way to
    enforce a wall-clock deadline: when the callback returns non-zero
    SQLite aborts with ``OperationalError("interrupted")``.

    Callers MUST use ``try/finally`` to close the returned connection;
    the helper does not provide a context-manager wrapper because the
    cursor-iterating code paths in this file want plain ``try/finally``
    for symmetry across three different db_* endpoints.
    """
    conn = sqlite3.connect(str(db_file), timeout=timeout_sec)
    deadline = time.monotonic() + timeout_sec

    def _progress() -> int:
        # Returning non-zero aborts the in-flight statement.
        return 1 if time.monotonic() > deadline else 0

    # Check every 1000 VM instructions — frequent enough to react quickly,
    # rare enough that the overhead is negligible.
    conn.set_progress_handler(_progress, 1000)
    return conn


@app.post("/db_query")
async def db_query(req: DbSqlRequest):
    """Execute a read-only SQL query and return rows with column names."""
    ws = _workspace(req.lab_id)

    blocked = _check_blocked(req.sql)
    if blocked:
        return {"success": False, "output": blocked}

    if not _DB_READ_ONLY_RE.match(req.sql):
        return {
            "success": False,
            "output": "db_query only accepts SELECT, EXPLAIN, and read-only PRAGMA statements. Use db_execute for write operations.",
        }

    db_file = _db_path(ws)
    if not db_file.exists():
        return {"success": False, "output": "No database exists yet. Use db_execute to create tables first."}

    conn = None
    try:
        conn = _sqlite_open(db_file, req.timeout_sec)
        conn.execute("PRAGMA query_only = ON")
        cursor = conn.execute(req.sql, req.params or [])
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(_DB_MAX_ROWS)
        row_count = len(rows)

        # Check if there are more rows
        extra = cursor.fetchone()
        truncated = extra is not None

        result = json.dumps({
            "columns": columns,
            "rows": [list(r) for r in rows],
            "row_count": row_count,
            "truncated": truncated,
        }, default=str)

        return {"success": True, "output": _truncate(result, req.max_output_kb)}
    except sqlite3.Error as e:
        return {"success": False, "output": f"SQL error: {e}"}
    except Exception as e:
        logger.exception("db_query failed for lab %s", req.lab_id)
        return {"success": False, "output": f"Database error: {e}"}
    finally:
        # R09 — close on every exit, including exception paths.
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


@app.post("/db_execute")
async def db_execute(req: DbSqlRequest):
    """Execute a write SQL statement (CREATE, INSERT, UPDATE, DELETE, etc.)."""
    ws = _workspace(req.lab_id)

    blocked = _check_blocked(req.sql)
    if blocked:
        return {"success": False, "output": blocked}

    db_file = _db_path(ws)

    conn = None
    try:
        conn = _sqlite_open(db_file, req.timeout_sec)
        cursor = conn.execute(req.sql, req.params or [])
        affected = cursor.rowcount
        conn.commit()

        return {
            "success": True,
            "output": json.dumps({
                "affected_rows": affected,
                "message": f"OK — {affected} row(s) affected.",
            }),
        }
    except sqlite3.Error as e:
        return {"success": False, "output": f"SQL error: {e}"}
    except Exception as e:
        logger.exception("db_execute failed for lab %s", req.lab_id)
        return {"success": False, "output": f"Database error: {e}"}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


@app.post("/db_schema")
async def db_schema(req: DbRequest):
    """Return the schema of the agent database (tables, columns, types)."""
    ws = _workspace(req.lab_id)
    db_file = _db_path(ws)

    if not db_file.exists():
        return {"success": True, "output": json.dumps({"tables": [], "message": "No database exists yet."})}

    conn = None
    try:
        conn = _sqlite_open(db_file, req.timeout_sec)
        conn.execute("PRAGMA query_only = ON")

        # Get all tables
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = []
        for (table_name,) in cursor.fetchall():
            col_cursor = conn.execute(f"PRAGMA table_info([{table_name}])")  # noqa: S608
            columns = []
            for col in col_cursor.fetchall():
                columns.append({
                    "name": col[1],
                    "type": col[2],
                    "notnull": bool(col[3]),
                    "default": col[4],
                    "pk": bool(col[5]),
                })
            row_count_cursor = conn.execute(f"SELECT COUNT(*) FROM [{table_name}]")  # noqa: S608
            row_count = row_count_cursor.fetchone()[0]
            tables.append({
                "name": table_name,
                "columns": columns,
                "row_count": row_count,
            })

        return {"success": True, "output": json.dumps({"tables": tables}, default=str)}
    except sqlite3.Error as e:
        return {"success": False, "output": f"SQL error: {e}"}
    except Exception as e:
        logger.exception("db_schema failed for lab %s", req.lab_id)
        return {"success": False, "output": f"Database error: {e}"}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ── Headless browser (Playwright) ─────────────────────────
#
# A single per-container Chromium instance is shared across all browser_* calls
# for the lab this sandbox belongs to (one sandbox = one lab).
# An idle reaper closes the browser after BROWSER_IDLE_TIMEOUT seconds with no
# activity, and `stop_sandbox` (called at end of every lab run by the control
# plane) tears down the whole container.

BROWSER_IDLE_TIMEOUT = float(os.environ.get("BROWSER_IDLE_TIMEOUT", "90"))
BROWSER_NAV_TIMEOUT_MS = int(os.environ.get("BROWSER_NAV_TIMEOUT_MS", "20000"))

_browser_lock = asyncio.Lock()
_browser_state: dict[str, Any] = {
    "pw": None,
    "browser": None,
    "context": None,
    "page": None,
    "last_used": 0.0,
    "reaper_task": None,
}


async def _browser_close_locked() -> None:
    """Close all Playwright resources. Caller must hold _browser_lock."""
    page = _browser_state.get("page")
    ctx = _browser_state.get("context")
    browser = _browser_state.get("browser")
    pw = _browser_state.get("pw")
    _browser_state["page"] = None
    _browser_state["context"] = None
    _browser_state["browser"] = None
    _browser_state["pw"] = None
    for obj, name in ((page, "page"), (ctx, "context"), (browser, "browser"), (pw, "playwright")):
        if obj is None:
            continue
        try:
            if name == "playwright":
                await obj.stop()
            else:
                await obj.close()
        except Exception:
            logger.debug("browser %s close failed", name, exc_info=True)


async def _browser_reaper() -> None:
    """Background task: close the browser after BROWSER_IDLE_TIMEOUT s of inactivity."""
    try:
        while True:
            await asyncio.sleep(max(5.0, BROWSER_IDLE_TIMEOUT / 4))
            async with _browser_lock:
                if _browser_state.get("page") is None:
                    _browser_state["reaper_task"] = None
                    return
                idle = asyncio.get_event_loop().time() - _browser_state["last_used"]
                if idle >= BROWSER_IDLE_TIMEOUT:
                    logger.info("browser idle %.1fs >= %.1fs — closing", idle, BROWSER_IDLE_TIMEOUT)
                    await _browser_close_locked()
                    _browser_state["reaper_task"] = None
                    return
    except asyncio.CancelledError:
        pass


async def _ensure_page():
    """Return a (page) object, creating the Playwright browser on first use.

    Caller MUST be inside _browser_lock.
    """
    page = _browser_state.get("page")
    if page is not None and not page.is_closed():
        _browser_state["last_used"] = asyncio.get_event_loop().time()
        return page

    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
        ],
    )
    ctx = await browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
        viewport={"width": 1280, "height": 800},
        locale="en-US",
        timezone_id="America/New_York",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9", "DNT": "1"},
    )
    await ctx.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    # Cluster E — re-check every URL Chromium opens (top-level + redirects
    # + sub-resources) against ``_is_private_host`` so a 302 to an internal
    # address cannot bypass the pre-navigation guard.
    await ctx.route("**/*", _browser_route_handler)
    page = await ctx.new_page()
    _browser_state["pw"] = pw
    _browser_state["browser"] = browser
    _browser_state["context"] = ctx
    _browser_state["page"] = page
    _browser_state["last_used"] = asyncio.get_event_loop().time()

    if _browser_state.get("reaper_task") is None:
        _browser_state["reaper_task"] = asyncio.create_task(_browser_reaper())

    return page


def _classify_ip(addr) -> bool:
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _is_private_host(hostname: str) -> bool:
    """Block access to private/internal hosts to prevent SSRF from inside sandbox.

    Cluster E — uses the ``ipaddress`` stdlib so the full 127.0.0.0/8 range,
    IPv6 loopback (``::1``), link-local (``fe80::/10``), unique-local
    (``fc00::/7``), and multicast are all blocked. Resolves the host via
    the system resolver and rejects if any A/AAAA record lands in a private
    range. Fail-closed on resolver errors.
    """
    if not hostname:
        return True
    h = hostname.strip().strip("[]").lower()
    if not h:
        return True
    if h == "localhost" or h.endswith(".local") or h.endswith(".internal"):
        return True
    # Literal IP form?
    try:
        addr = ipaddress.ip_address(h)
        return _classify_ip(addr)
    except ValueError:
        pass
    # Container hostnames (no dots, e.g. bob-db, bob-qdrant, bob-api)
    if "." not in h:
        return True
    try:
        infos = socket.getaddrinfo(h, None)
    except (socket.gaierror, UnicodeError, OSError):
        return True
    for _fam, _kind, _proto, _canon, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return True
        if _classify_ip(addr):
            return True
    return False


async def _browser_route_handler(route, request) -> None:
    """Playwright route interceptor that aborts any request whose host
    fails ``_is_private_host``. Installed on the browser context so it
    applies to top-level navigations, redirects, sub-resource loads, and
    any JS-initiated fetch.

    Cluster E — Chromium follows 3xx redirects natively without consulting
    the Python guard; this handler re-runs the check on every URL.
    """
    try:
        host = urlparse(request.url).hostname or ""
    except Exception:
        await route.abort()
        return
    if _is_private_host(host):
        await route.abort()
        return
    await route.continue_()


class BrowserNavigateRequest(BaseModel):
    url: str
    max_output_kb: int = 256
    timeout_ms: int = BROWSER_NAV_TIMEOUT_MS


class BrowserSnapshotRequest(BaseModel):
    max_output_kb: int = 256


class BrowserFileRenderRequest(BaseModel):
    """Render a local HTML file (already written to the workspace) and extract output."""
    lab_id: str
    html_path: str  # absolute path inside the sandbox container's filesystem
    wait_selector: str | None = None
    error_selector: str | None = None
    timeout_ms: int = 20000


class BrowserScreenshotElementRequest(BrowserFileRenderRequest):
    selector: str
    output_path: str  # absolute path where to save the PNG


class BrowserEvalSelectorRequest(BrowserFileRenderRequest):
    selector: str
    js_expression: str  # JS expression evaluated against the matched element


@app.post("/browser_navigate")
async def browser_navigate(req: BrowserNavigateRequest):
    url = (req.url or "").strip()
    if not url:
        return {"success": False, "output": "browser_navigate requires 'url'"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    hostname = urlparse(url).hostname or ""
    if _is_private_host(hostname):
        return {"success": False, "output": "Access to private/internal URLs is not allowed."}

    async with _browser_lock:
        try:
            page = await _ensure_page()
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=req.timeout_ms)
            status = resp.status if resp else "unknown"
            title = await page.title()
            text = await page.evaluate("""() => {
                const sel = document.querySelectorAll('script, style, nav, footer, header, [role="banner"], [role="navigation"]');
                sel.forEach(el => el.remove());
                return document.body?.innerText?.substring(0, 50000) || '';
            }""")
            _browser_state["last_used"] = asyncio.get_event_loop().time()
            return {
                "success": True,
                "output": _truncate(
                    f"Navigated to: {url}\nStatus: {status}\nTitle: {title}\n---\n{text}",
                    req.max_output_kb,
                ),
            }
        except Exception as e:
            return {"success": False, "output": f"Browser navigation failed: {e}"}


@app.post("/browser_snapshot")
async def browser_snapshot(req: BrowserSnapshotRequest):
    async with _browser_lock:
        page = _browser_state.get("page")
        if page is None or page.is_closed():
            return {"success": False, "output": "No browser page open. Call browser_navigate first."}
        try:
            title = await page.title()
            url = page.url
            text = await page.evaluate("""() => {
                const sel = document.querySelectorAll('script, style');
                sel.forEach(el => el.remove());
                return document.body?.innerText?.substring(0, 50000) || '';
            }""")
            _browser_state["last_used"] = asyncio.get_event_loop().time()
            return {
                "success": True,
                "output": _truncate(f"Page: {url}\nTitle: {title}\n---\n{text}", req.max_output_kb),
            }
        except Exception as e:
            return {"success": False, "output": f"Browser snapshot failed: {e}"}


@app.post("/browser_close")
async def browser_close():
    async with _browser_lock:
        await _browser_close_locked()
        task = _browser_state.get("reaper_task")
        _browser_state["reaper_task"] = None
    # R08 — await cancellation OUTSIDE the lock so the reaper coroutine
    # (which itself takes the lock on its next iteration) can actually
    # unwind. ``await task`` raises CancelledError; suppress it.
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    return {"success": True, "output": "Browser closed."}


def _validate_workspace_path(lab_id: str, abs_path: str) -> Path:
    """Ensure `abs_path` lives under this lab's workspace; raise HTTPException otherwise.

    A09 — same segment-aware containment as ``_workspace``.
    """
    ws = _workspace(lab_id).resolve()
    p = Path(abs_path).resolve()
    if not p.is_relative_to(ws):
        raise HTTPException(400, f"Path escapes lab workspace: {abs_path}")
    return p


@app.post("/browser_render_file")
async def browser_render_file(req: BrowserFileRenderRequest):
    """Open a local HTML file in the browser and wait for a selector to appear.

    Used by mermaid_to_img / excalidraw to render local templates.
    """
    file_path = _validate_workspace_path(req.lab_id, req.html_path)
    if not file_path.is_file():
        return {"success": False, "output": f"HTML file not found: {req.html_path}"}

    async with _browser_lock:
        try:
            page = await _ensure_page()
            await page.goto(f"file://{file_path}", wait_until="networkidle", timeout=req.timeout_ms)
            sel = req.wait_selector or "body"
            await page.wait_for_selector(sel, timeout=req.timeout_ms)
            err = None
            if req.error_selector:
                el = await page.query_selector(req.error_selector)
                if el:
                    err = await el.text_content()
            _browser_state["last_used"] = asyncio.get_event_loop().time()
            if err:
                return {"success": False, "output": f"Render error: {err}"}
            return {"success": True, "output": "rendered"}
        except Exception as e:
            return {"success": False, "output": f"Render failed: {e}"}


@app.post("/browser_screenshot_element")
async def browser_screenshot_element(req: BrowserScreenshotElementRequest):
    """Open HTML, wait for selector, screenshot it to PNG.

    `html_path` and `output_path` MUST both live under the lab workspace.
    """
    file_path = _validate_workspace_path(req.lab_id, req.html_path)
    out_path = _validate_workspace_path(req.lab_id, req.output_path)
    if not file_path.is_file():
        return {"success": False, "output": f"HTML file not found: {req.html_path}"}

    async with _browser_lock:
        try:
            page = await _ensure_page()
            await page.goto(f"file://{file_path}", wait_until="networkidle", timeout=req.timeout_ms)
            await page.wait_for_selector(req.wait_selector or req.selector, timeout=req.timeout_ms)
            if req.error_selector:
                err_el = await page.query_selector(req.error_selector)
                if err_el:
                    err_msg = await err_el.text_content()
                    return {"success": False, "output": f"Render error: {err_msg}"}
            locator = page.locator(req.selector).first
            out_path.parent.mkdir(parents=True, exist_ok=True)
            await locator.screenshot(path=str(out_path), type="png")
            _browser_state["last_used"] = asyncio.get_event_loop().time()
            return {
                "success": True,
                "output": str(out_path),
                "size_bytes": out_path.stat().st_size,
            }
        except Exception as e:
            return {"success": False, "output": f"Screenshot failed: {e}"}


@app.post("/browser_eval_selector")
async def browser_eval_selector(req: BrowserEvalSelectorRequest):
    """Open HTML, wait for selector, evaluate JS against it. Returns the result as a string.

    Used by mermaid_to_img to extract `el.outerHTML` for SVG output.
    """
    file_path = _validate_workspace_path(req.lab_id, req.html_path)
    if not file_path.is_file():
        return {"success": False, "output": f"HTML file not found: {req.html_path}"}

    async with _browser_lock:
        try:
            page = await _ensure_page()
            await page.goto(f"file://{file_path}", wait_until="networkidle", timeout=req.timeout_ms)
            await page.wait_for_selector(req.wait_selector or req.selector, timeout=req.timeout_ms)
            if req.error_selector:
                err_el = await page.query_selector(req.error_selector)
                if err_el:
                    err_msg = await err_el.text_content()
                    return {"success": False, "output": f"Render error: {err_msg}"}
            locator = page.locator(req.selector).first
            value = await locator.evaluate(req.js_expression)
            _browser_state["last_used"] = asyncio.get_event_loop().time()
            return {"success": True, "output": value if isinstance(value, str) else json.dumps(value)}
        except Exception as e:
            return {"success": False, "output": f"Eval failed: {e}"}


@app.on_event("shutdown")
async def _on_shutdown():
    async with _browser_lock:
        await _browser_close_locked()
        task = _browser_state.get("reaper_task")
        _browser_state["reaper_task"] = None
    # R08 — same cleanup pattern as /browser_close: cancel + await
    # outside the lock so the reaper unwinds cleanly on graceful uvicorn
    # shutdown instead of being abandoned mid-iteration.
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
