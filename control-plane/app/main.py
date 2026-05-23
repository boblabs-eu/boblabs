"""Bob Manager Control Plane — FastAPI application entry point."""

import asyncio
import logging
import os
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

from fastapi import FastAPI, WebSocket  # noqa: E402  (after warnings filter)
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.api.routes import auth, servers, commands, workflows, projects, metrics, modules, resources, news, web3, web3_access, orchestrator, labs, tool_sets, prompt_templates, library_agents, cron_jobs, rag, public, access_tokens, tool_configs, server_access, internal_apps, outreach, admin_logs, admin_consumer_apps, admin_labs, blog_seo  # noqa: E402
from app.database import async_session
from app.middleware.request_logger import RequestLoggerMiddleware
from app.websocket.agent_handler import handle_agent_connection
from app.websocket.client_handler import handle_client_connection
from app.version import __version__

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
    - Fresh install (init.sql already created schema with slug column): stamp head, no-op upgrade.
    - Legacy prod (blog_posts exists, no slug column, no alembic_version): stamp 0001, upgrade to head.
    - Already-migrated DB: upgrade to head (no-op if up-to-date).
    """
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app.database import async_session

    try:
        async with async_session() as db:
            has_alembic = (await db.execute(text(
                "SELECT to_regclass('public.alembic_version') IS NOT NULL"
            ))).scalar()
            has_blog = (await db.execute(text(
                "SELECT to_regclass('public.blog_posts') IS NOT NULL"
            ))).scalar()
            has_slug = False
            if has_blog:
                has_slug = (await db.execute(text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='blog_posts' AND column_name='slug')"
                ))).scalar()

        ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
        if not ini_path.exists():
            logger.warning("alembic.ini not found at %s; skipping migrations", ini_path)
            return
        cfg = Config(str(ini_path))
        cfg.set_main_option("script_location", str(ini_path.parent / "app" / "migrations"))

        if not has_alembic:
            # First time alembic sees this DB. Decide stamp target.
            if has_blog and has_slug:
                # Fresh install via init.sql (slug already present). Stamp to head.
                logger.info("Alembic: stamping fresh DB to head")
                await asyncio.to_thread(command.stamp, cfg, "head")
            else:
                # Legacy prod (no slug). Stamp baseline so 0002 will run.
                logger.info("Alembic: stamping legacy DB to 0001_baseline")
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
                    get_web3_settings,
                    record_portfolio_snapshot,
                    cleanup_old_snapshots,
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
    from app.database import async_session
    from sqlalchemy import text

    try:
        async with async_session() as db:
            result = await db.execute(
                text("UPDATE ai_providers SET name = REGEXP_REPLACE(name, '^ollama-', '') "
                     "WHERE name LIKE 'ollama-%' AND provider_type = 'ollama' "
                     "AND REGEXP_REPLACE(name, '^ollama-', '') NOT IN (SELECT name FROM ai_providers)")
            )
            if result.rowcount > 0:
                await db.commit()
                logger.info("Renamed %d legacy ollama-* providers", result.rowcount)
    except Exception as e:
        logger.warning("Failed to rename legacy providers: %s", e)


@app.on_event("startup")
async def reset_stuck_labs():
    """Reset labs stuck in 'running' state after a server restart (no active runner)."""
    from app.database import async_session
    from sqlalchemy import text

    try:
        async with async_session() as db:
            result = await db.execute(
                text(
                    "UPDATE labs SET status = 'paused', paused_at = NOW() "
                    "WHERE status = 'running'"
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
    from app.database import async_session
    from sqlalchemy import text

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
                    text("DELETE FROM request_log "
                         "WHERE timestamp < NOW() - (INTERVAL '1 day' * :days)"),
                    {"days": retention_days},
                )
                await db.commit()
                if result.rowcount:
                    logger.info("Purged %d request_log rows older than %d days",
                                result.rowcount, retention_days)
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
async def seed_agent_template_presets():
    """Seed reusable agent template presets (OpenClaw, Hermes, ...)."""
    try:
        from app.services.agent_template_seed import seed_agent_templates
        await seed_agent_templates(async_session)
    except Exception as e:
        logger.warning("Failed to seed agent templates: %s", e)


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
