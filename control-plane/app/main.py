"""Bob Manager Control Plane — FastAPI application entry point."""

import asyncio
import fcntl
import logging
import os
import sys
import warnings

# Pydantic v2 reserves the ``model_`` prefix for its own attributes and emits
# UserWarnings when user fields collide (``model_id``, ``model_identifier``,
# ``model_used``, ``model_name``). All of ours refer to LLM models — they
# never collide with pydantic internals. Suppress the noise at startup so
# the bob-api logs stay readable.
warnings.filterwarnings(
    "ignore",
    message=r'Field "model_.*" has conflict with protected namespace "model_"\.',
    category=UserWarning,
)


# ── Cluster N — enforce single-worker uvicorn ─────────────────────────
#
# A lot of bob-api state is per-process: the WebSocket hub (_agents,
# _clients, _pending, _metrics_cache, _terminal_sessions), the lab runner
# registry (_active_runners), the loop-detection manager (_buffers), the
# GPU semaphores in tool_media (_gpu_slots), and trading_service's hot
# wallet dict. Multi-worker uvicorn silently partitions every one of
# those, so an agent socket lands on worker A while a UI client on
# worker B waits for events it will never receive.
#
# The Dockerfile already pins ``--workers 1`` but an operator editing
# docker-compose to override that command could break the invariant
# without realising. Two defences fire at import time:
#   1) WEB_CONCURRENCY / UVICORN_WORKERS > 1 → exit non-zero immediately.
#   2) A non-blocking flock on /tmp/bob-api.lock — a second worker in the
#      same container can't acquire it and exits cleanly.
# Operators who genuinely need to externalise state to Redis/SQL must
# set BOB_API_ALLOW_MULTI_WORKER=1 *after* doing that work; the env is
# undocumented on purpose so it can't be set accidentally.


def _enforce_single_worker() -> None:
    if os.environ.get("BOB_API_ALLOW_MULTI_WORKER", "").lower() in {"1", "true", "yes"}:
        return
    for env in ("WEB_CONCURRENCY", "UVICORN_WORKERS", "GUNICORN_WORKERS"):
        raw = os.environ.get(env, "").strip()
        if not raw:
            continue
        try:
            if int(raw) > 1:
                sys.stderr.write(
                    f"FATAL: bob-api requires a single worker process but "
                    f"{env}={raw}. The control-plane keeps WebSocket, lab-"
                    f"runner and trading state in-process; multi-worker "
                    f"deployments silently partition that state. Externalise "
                    f"the affected stores (Redis / SQL) and set "
                    f"BOB_API_ALLOW_MULTI_WORKER=1 to override.\n"
                )
                sys.exit(1)
        except ValueError:
            pass
    lock_path = os.environ.get("BOB_API_LOCK_PATH", "/tmp/bob-api.lock")
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        sys.stderr.write(
            f"FATAL: another bob-api worker is already running (holds "
            f"{lock_path}). Single-worker invariant violated.\n"
        )
        sys.exit(1)
    # Keep ``fd`` open for the process lifetime — Python closes the fd
    # when the interpreter exits, releasing the lock.
    globals()["_BOB_API_LOCK_FD"] = fd


_enforce_single_worker()

from fastapi import FastAPI, WebSocket  # noqa: E402  (after warnings filter)
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.api.routes import (  # noqa: E402
    access_tokens,
    admin_consumer_apps,
    admin_labs,
    admin_logs,
    auth,
    blog_seo,
    commands,
    cron_jobs,
    hermes,
    internal_apps,
    labs,
    library_agents,
    llm_gateway,
    mcp,
    metrics,
    modules,
    news,
    orchestrator,
    outreach,
    projects,
    prompt_templates,
    public,
    rag,
    resources,
    server_access,
    servers,
    tool_configs,
    tool_sets,
    web3,
    web3_access,
    workflows,
)
from app.database import async_session
from app.middleware.request_logger import RequestLoggerMiddleware
from app.version import __version__
from app.websocket.agent_handler import handle_agent_connection
from app.websocket.client_handler import handle_client_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Bob Manager",
    description="Distributed GPU Server Management Platform — Control Plane API",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ─────────────────────────────────────────
_cors_origins = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request logging (for /admin/logs) ────────────
app.add_middleware(RequestLoggerMiddleware)

# ── REST API Routes ──────────────────────────────
app.include_router(auth.router, prefix="/api/v1")
app.include_router(servers.router, prefix="/api/v1")
app.include_router(commands.router, prefix="/api/v1")
app.include_router(workflows.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(modules.router, prefix="/api/v1")
app.include_router(resources.router, prefix="/api/v1")
app.include_router(metrics.router, prefix="/api/v1")
app.include_router(news.router, prefix="/api/v1")
app.include_router(web3.router, prefix="/api/v1")
app.include_router(web3_access.router, prefix="/api/v1")
app.include_router(orchestrator.router, prefix="/api/v1")
app.include_router(labs.router, prefix="/api/v1")
app.include_router(tool_sets.router, prefix="/api/v1")
app.include_router(prompt_templates.router, prefix="/api/v1")
app.include_router(library_agents.router, prefix="/api/v1")
app.include_router(hermes.router, prefix="/api/v1")
app.include_router(llm_gateway.router, prefix="/api/v1")
app.include_router(mcp.router, prefix="/api/v1")
app.include_router(cron_jobs.router, prefix="/api/v1")
app.include_router(rag.router, prefix="/api/v1")
app.include_router(public.router, prefix="/api/v1")
app.include_router(access_tokens.router, prefix="/api/v1")
app.include_router(tool_configs.router, prefix="/api/v1")
app.include_router(server_access.router, prefix="/api/v1")
app.include_router(internal_apps.router, prefix="/api/v1")
app.include_router(outreach.router, prefix="/api/v1")
app.include_router(admin_logs.router, prefix="/api/v1")
app.include_router(admin_consumer_apps.router, prefix="/api/v1")
app.include_router(admin_labs.router, prefix="/api/v1")

# ── SEO / Blog Prerender (no /api prefix — bots hit /blog, /sitemap.xml, /rss.xml directly) ──
app.include_router(blog_seo.router)


# ── WebSocket Endpoints ─────────────────────────
@app.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket):
    """WebSocket endpoint for agent connections."""
    await handle_agent_connection(websocket, async_session)


@app.websocket("/ws/client")
async def ws_client(websocket: WebSocket):
    """WebSocket endpoint for UI client connections."""
    await handle_client_connection(websocket)


# ── Health Check ─────────────────────────────────
@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "bob-manager-control-plane", "version": __version__}


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "Bob Manager",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
    }


# ── Background: Portfolio Snapshot Scheduler ─────
_snapshot_task: asyncio.Task | None = None


@app.on_event("startup")
async def run_database_migrations():
    """Auto-stamp + upgrade Alembic to head.

    Logic:
    - No alembic_version table: stamp 0001_baseline so migrations 0002+ run.
      Covers BOTH fresh installs (init.sql created the 0001-era schema) and
      legacy prod DBs that pre-date alembic. Every migration past 0001 must
      be idempotent (IF NOT EXISTS / IF EXISTS guards or DO blocks) because
      it runs on top of whatever init.sql last committed.
    - alembic_version table present: upgrade to head (no-op if already there).

    Earlier releases (0.11.0–0.12.1) stamped *head* when init.sql had a
    known recent column. That broke fresh installs the moment init.sql
    drifted from the live migration chain — and it had drifted by 9
    revisions. See CHANGELOG 0.12.2.
    """
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app.database import async_session

    try:
        async with async_session() as db:
            has_alembic = (
                await db.execute(text("SELECT to_regclass('public.alembic_version') IS NOT NULL"))
            ).scalar()
            # Self-heal the 0.11.0–0.12.1 broken-stamp state: alembic_version
            # claims head, but `ai_providers.pending_approval` (migration 0005)
            # is missing because init.sql drifted and the old code stamped
            # head over an incomplete schema. Down-stamp to 0001_baseline so
            # the upgrade below replays 0002-0014 on the partial schema.
            # Every migration past 0001 is idempotent — replay is safe.
            broken_stamp = False
            if has_alembic:
                has_pending_approval = (
                    await db.execute(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
                            "WHERE table_schema='public' AND table_name='ai_providers' "
                            "AND column_name='pending_approval')"
                        )
                    )
                ).scalar()
                broken_stamp = not has_pending_approval

        ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
        if not ini_path.exists():
            logger.warning("alembic.ini not found at %s; skipping migrations", ini_path)
            return
        cfg = Config(str(ini_path))
        cfg.set_main_option("script_location", str(ini_path.parent / "app" / "migrations"))

        if not has_alembic:
            logger.info("Alembic: stamping DB to 0001_baseline (first run)")
            await asyncio.to_thread(command.stamp, cfg, "0001_baseline")
        elif broken_stamp:
            logger.warning(
                "Alembic: detected broken-stamp from 0.11.0-0.12.1 "
                "(alembic_version at head but schema missing migration 0005+); "
                "re-stamping to 0001_baseline so catch-up migrations replay"
            )
            await asyncio.to_thread(command.stamp, cfg, "0001_baseline")

        logger.info("Alembic: upgrading to head")
        await asyncio.to_thread(command.upgrade, cfg, "head")
        logger.info("Alembic: migrations applied")
    except Exception as e:
        logger.exception("Alembic migration failed: %s", e)
        raise


async def _snapshot_loop():
    """Periodically record portfolio snapshots and clean old data."""
    # Wait a bit for the app to fully start
    await asyncio.sleep(15)
    while True:
        try:
            async with async_session() as db:
                from app.services.web3_service import (
                    cleanup_old_snapshots,
                    get_web3_settings,
                    record_portfolio_snapshot,
                )

                settings = await get_web3_settings(db)
                interval = settings["refresh_interval"]

                result = await record_portfolio_snapshot(db)
                await db.commit()
                logger.info("Portfolio snapshot recorded: %s", result)

                cleanup = await cleanup_old_snapshots(db)
                await db.commit()
                if cleanup.get("deleted", 0) > 0:
                    logger.info("Snapshot cleanup: %s", cleanup)
        except Exception as e:
            logger.error("Snapshot scheduler error: %s", e)
            interval = 300  # fallback

        await asyncio.sleep(interval)


@app.on_event("startup")
async def start_snapshot_scheduler():
    global _snapshot_task
    _snapshot_task = asyncio.create_task(_snapshot_loop())
    logger.info("Portfolio snapshot scheduler started")


@app.on_event("startup")
async def start_lab_scheduler():
    from app.services.lab_scheduler import start_scheduler

    start_scheduler(async_session)
    logger.info("Lab cron scheduler started")


@app.on_event("startup")
async def rename_legacy_ollama_providers():
    """Rename ollama-{agent} providers to {agent} for cleaner display."""
    from sqlalchemy import text

    from app.database import async_session

    try:
        async with async_session() as db:
            result = await db.execute(
                text(
                    "UPDATE ai_providers SET name = REGEXP_REPLACE(name, '^ollama-', '') "
                    "WHERE name LIKE 'ollama-%' AND provider_type = 'ollama' "
                    "AND REGEXP_REPLACE(name, '^ollama-', '') NOT IN (SELECT name FROM ai_providers)"
                )
            )
            if result.rowcount > 0:
                await db.commit()
                logger.info("Renamed %d legacy ollama-* providers", result.rowcount)
    except Exception as e:
        logger.warning("Failed to rename legacy providers: %s", e)


@app.on_event("startup")
async def reset_stuck_labs():
    """Reset labs stuck in 'running' state after a server restart (no active runner)."""
    from sqlalchemy import text

    from app.database import async_session

    try:
        async with async_session() as db:
            result = await db.execute(
                text(
                    "UPDATE labs SET status = 'paused', paused_at = NOW() WHERE status = 'running'"
                )
            )
            if result.rowcount > 0:
                await db.commit()
                logger.info("Reset %d stuck labs from 'running' to 'paused'", result.rowcount)
    except Exception as e:
        logger.warning("Failed to reset stuck labs: %s", e)


@app.on_event("startup")
async def link_orphaned_providers():
    """Link HF/OpenAI providers that have no server_id by matching base_url host to servers.host."""
    from sqlalchemy import text

    from app.database import async_session

    try:
        async with async_session() as db:
            result = await db.execute(
                text(
                    "UPDATE ai_providers p SET server_id = s.id "
                    "FROM servers s "
                    "WHERE p.server_id IS NULL "
                    "AND p.base_url LIKE 'http://' || s.host || ':%'"
                )
            )
            if result.rowcount > 0:
                await db.commit()
                logger.info("Linked %d orphaned providers to their servers", result.rowcount)
    except Exception as e:
        logger.warning("Failed to link orphaned providers: %s", e)


@app.on_event("startup")
async def configure_loop_manager():
    """Wire the loop-detection manager to the DB session factory."""
    from app.services.loop_detection import get_loop_manager

    try:
        get_loop_manager().configure(async_session)
        logger.info("Loop manager configured")
    except Exception as e:
        logger.warning("Failed to configure loop manager: %s", e)


# ── Background: request_log retention purge ──────
_request_log_purge_task: asyncio.Task | None = None


async def _request_log_purge_loop():
    """Drop request_log rows older than LOG_RETENTION_DAYS (default 30) every hour."""
    from sqlalchemy import text

    retention_days = max(1, int(os.environ.get("LOG_RETENTION_DAYS", "30")))
    await asyncio.sleep(60)  # let the app boot first
    while True:
        try:
            async with async_session() as db:
                result = await db.execute(
                    text(
                        "DELETE FROM request_log "
                        "WHERE timestamp < NOW() - (INTERVAL '1 day' * :days)"
                    ),
                    {"days": retention_days},
                )
                await db.commit()
                if result.rowcount:
                    logger.info(
                        "Purged %d request_log rows older than %d days",
                        result.rowcount,
                        retention_days,
                    )
        except Exception as e:
            logger.warning("request_log purge error: %s", e)
        await asyncio.sleep(3600)


@app.on_event("startup")
async def start_request_log_purge():
    global _request_log_purge_task
    _request_log_purge_task = asyncio.create_task(_request_log_purge_loop())


@app.on_event("startup")
async def cleanup_sandbox_containers():
    """Remove orphaned per-lab sandbox containers from previous API runs."""
    try:
        from app.services.container_manager import cleanup_orphaned

        removed = await cleanup_orphaned()
        if removed:
            logger.info("Cleaned up %d orphaned sandbox containers on startup", removed)
    except Exception as e:
        logger.warning("Failed to cleanup sandbox containers: %s", e)


@app.on_event("startup")
async def sweep_lightrag_orphans():
    """OP04 — drop on-disk LightRAG dirs whose rag_collections row vanished."""
    try:
        from app.services.lightrag_service import LightRagService

        removed = await LightRagService.sweep_orphans()
        if removed:
            logger.info("OP04: swept %d orphan LightRAG dirs on startup", removed)
    except Exception as e:
        logger.warning("OP04: LightRAG orphan sweep failed: %s", e)


@app.on_event("startup")
async def seed_agent_template_presets():
    """Seed reusable agent template presets (OpenClaw, Hermes, ...)."""
    try:
        from app.services.agent_template_seed import seed_agent_templates

        await seed_agent_templates(async_session)
    except Exception as e:
        logger.warning("Failed to seed agent templates: %s", e)


@app.on_event("startup")
async def sync_mcp_servers():
    """Register tools from every enabled MCP server into the tool registry."""
    try:
        from app.services.tools.mcp_registry import sync_mcp_tools

        result = await sync_mcp_tools(async_session)
        if result["tools"]:
            logger.info(
                "MCP: registered %d tools from %d server(s)",
                result["tools"],
                result["servers"],
            )
    except Exception as e:
        logger.warning("Failed to sync MCP servers: %s", e)


@app.on_event("startup")
async def cleanup_hermes_containers():
    """Remove stale Hermes containers from a previous run (volumes kept —
    re-activation restores each agent's memory)."""
    try:
        from app.services.hermes import cleanup_orphaned_hermes

        removed = await cleanup_orphaned_hermes()
        if removed:
            logger.info("Cleaned up %d orphaned Hermes containers on startup", removed)
    except Exception as e:
        logger.warning("Hermes container cleanup failed: %s", e)


@app.on_event("shutdown")
async def stop_snapshot_scheduler():
    global _snapshot_task
    if _snapshot_task:
        _snapshot_task.cancel()
        try:
            await _snapshot_task
        except asyncio.CancelledError:
            pass

    from app.services.lab_scheduler import stop_scheduler

    stop_scheduler()
