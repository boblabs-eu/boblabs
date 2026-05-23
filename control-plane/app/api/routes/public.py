"""Bob Manager — Public API routes (no auth required)."""

import logging
import mimetypes
import os
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.dependencies import DbSession, create_access_token
from app.config import settings
from app.repositories.access_token_repo import (
    AccessTokenRepository,
    QuoteRequestRepository,
    TrialRequestRepository,
)
from app.repositories.blog_post_repo import BlogPostRepository, BlogTokenRepository
from app.services.email_service import notify_admin_new_quote, notify_admin_new_trial

logger = logging.getLogger(__name__)

LAB_RESOURCES_ROOT = Path(os.environ.get("LAB_RESOURCES_PATH", "/data/lab_resources"))

router = APIRouter(prefix="/public", tags=["public"])


# ── Schemas ──────────────────────────────────────

class TrialRequestIn(BaseModel):
    name: str
    email: str
    enterprise: str = ""
    role: str = ""
    purpose: str = ""


class TrialRequestOut(BaseModel):
    message: str


class QuoteRequestIn(BaseModel):
    name: str
    email: str
    company: str = ""
    phone: str = ""
    plan: str = ""
    description: str = ""


class QuoteRequestOut(BaseModel):
    message: str


class TokenValidateIn(BaseModel):
    token: str


class TokenValidateOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    label: str
    expires_at: str


# ── Endpoints ────────────────────────────────────

@router.post("/trial-request", response_model=TrialRequestOut)
async def submit_trial_request(payload: TrialRequestIn, db: DbSession):
    """Submit a request for trial access."""
    if not payload.name.strip() or not payload.email.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Name and email are required.",
        )
    repo = TrialRequestRepository(db)
    await repo.create(
        name=payload.name.strip(),
        email=payload.email.strip(),
        enterprise=payload.enterprise.strip(),
        role=payload.role.strip(),
        purpose=payload.purpose.strip(),
    )
    # Notify admin by email (fire-and-forget, don't fail the request)
    try:
        await notify_admin_new_trial(
            name=payload.name.strip(),
            email=payload.email.strip(),
            enterprise=payload.enterprise.strip(),
            role=payload.role.strip(),
            purpose=payload.purpose.strip(),
        )
    except Exception:
        logger.exception("Failed to send admin notification email")
    return TrialRequestOut(
        message="Your request has been submitted. We will review it and get back to you."
    )


@router.post("/validate-token", response_model=TokenValidateOut)
async def validate_access_token(payload: TokenValidateIn, db: DbSession):
    """Validate an access token and return a JWT for platform access."""
    repo = AccessTokenRepository(db)
    record = await repo.validate(payload.token.strip())
    if not record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
        )
    jwt = create_access_token({"sub": record.email or "user", "role": "user"})
    return TokenValidateOut(
        access_token=jwt,
        label=record.label,
        expires_at=record.expires_at.isoformat(),
    )


# ── Quote Requests ───────────────────────────────

@router.post("/quote-request", response_model=QuoteRequestOut)
async def submit_quote_request(payload: QuoteRequestIn, db: DbSession):
    """Submit a request for a quote."""
    if not payload.name.strip() or not payload.email.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Name and email are required.",
        )
    repo = QuoteRequestRepository(db)
    await repo.create(
        name=payload.name.strip(),
        email=payload.email.strip(),
        company=payload.company.strip(),
        phone=payload.phone.strip(),
        plan=payload.plan.strip(),
        description=payload.description.strip(),
    )
    try:
        await notify_admin_new_quote(
            name=payload.name.strip(),
            email=payload.email.strip(),
            company=payload.company.strip(),
            phone=payload.phone.strip(),
            plan=payload.plan.strip(),
            description=payload.description.strip(),
        )
    except Exception:
        logger.exception("Failed to send admin quote notification email")
    return QuoteRequestOut(
        message="Your quote request has been submitted. We will get back to you shortly."
    )


# ── Admin login ──────────────────────────────────

class AdminLoginIn(BaseModel):
    password: str


class AdminLoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/admin-login", response_model=AdminLoginOut)
async def admin_login(payload: AdminLoginIn):
    """Authenticate the platform admin using ADMIN_SECRET."""
    if not settings.admin_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin access is not configured.",
        )
    if payload.password != settings.admin_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials.",
        )
    jwt = create_access_token({"sub": "admin", "role": "admin"})
    return AdminLoginOut(access_token=jwt)


# ── Blog (public read, authenticated write) ──────


class BlogPostOut(BaseModel):
    id: str
    slug: str
    title: str
    content: str
    summary: str
    identity: str
    tags: list[str]
    created_at: str
    updated_at: str


class BlogPostCreateIn(BaseModel):
    title: str
    content: str
    summary: str = ""
    identity: str
    tags: list[str] = []
    slug: Optional[str] = None
    token: Optional[str] = None
    admin_secret: Optional[str] = None


def _post_to_out(p) -> "BlogPostOut":
    return BlogPostOut(
        id=str(p.id),
        slug=p.slug,
        title=p.title,
        content=p.content,
        summary=p.summary,
        identity=p.identity,
        tags=p.tags or [],
        created_at=p.created_at.isoformat(),
        updated_at=p.updated_at.isoformat(),
    )


@router.get("/blog", response_model=list[BlogPostOut])
async def list_blog_posts(
    db: DbSession,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List published blog posts (public, no auth)."""
    repo = BlogPostRepository(db)
    posts = await repo.get_all(limit=limit, offset=offset)
    return [_post_to_out(p) for p in posts]


@router.get("/blog/by-slug/{slug}", response_model=BlogPostOut)
async def get_blog_post_by_slug(slug: str, db: DbSession):
    """Get a single blog post by slug (public, no auth). Primary read path."""
    repo = BlogPostRepository(db)
    post = await repo.get_by_slug(slug)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    return _post_to_out(post)


@router.get("/blog/{post_id}", response_model=BlogPostOut)
async def get_blog_post(post_id: UUID, db: DbSession):
    """Get a single blog post by ID (public, no auth). Kept for backward-compat."""
    repo = BlogPostRepository(db)
    post = await repo.get_by_id(post_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    return _post_to_out(post)


@router.post("/blog", response_model=BlogPostOut, status_code=201)
async def create_blog_post(payload: BlogPostCreateIn, response: Response, db: DbSession):
    """Create a new blog post. Requires admin_secret or a valid blog token."""
    authorized = False

    # Check admin_secret
    if payload.admin_secret and settings.admin_secret:
        if payload.admin_secret == settings.admin_secret:
            authorized = True

    # Check blog token
    if not authorized and payload.token:
        token_repo = BlogTokenRepository(db)
        record = await token_repo.validate(payload.token)
        if record:
            authorized = True

    if not authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid credentials. Provide a valid admin_secret or blog token.",
        )

    if not payload.title.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Title is required.",
        )

    repo = BlogPostRepository(db)
    post = await repo.create(
        title=payload.title.strip(),
        content=payload.content.strip(),
        summary=payload.summary.strip(),
        identity=payload.identity.strip(),
        tags=payload.tags,
        slug=payload.slug.strip() if payload.slug else None,
    )
    # Cache-Tag for Cloudflare-style CDN purge.
    response.headers["Cache-Tag"] = f"blog,blog-{post.slug}"
    return _post_to_out(post)


# ── Live Demo (public, sanitized) ────────────────

@router.get("/live/labs", response_model=list)
async def live_labs(db: DbSession):
    """List all labs with agent counts for the public live page."""
    from sqlalchemy import select, func
    from app.models.orchestrator import Lab, LabAgent

    sub = (
        select(LabAgent.lab_id, func.count().label("agent_count"))
        .where(LabAgent.is_active == True)
        .group_by(LabAgent.lab_id)
        .subquery()
    )
    # Anonymous /live only sees labs whose owner has explicitly opted in via
    # ``is_public=true``. Default is private; existing labs are hidden until
    # the owner toggles via the Share modal or an admin via the Labs tab.
    stmt = (
        select(Lab, sub.c.agent_count)
        .outerjoin(sub, Lab.id == sub.c.lab_id)
        .where(Lab.is_public == True)  # noqa: E712 — SA boolean comparison
        .order_by(Lab.updated_at.desc())
    )
    rows = await db.execute(stmt)
    return [
        {
            "id": str(lab.id),
            "name": lab.name,
            "description": lab.description or "",
            "status": lab.status or "idle",
            "loop_type": lab.loop_type or "plan_execute",
            "current_iteration": lab.current_iteration or 0,
            "max_iterations": lab.max_iterations or 10,
            "agent_count": agent_count or 0,
            "updated_at": lab.updated_at.isoformat() if lab.updated_at else None,
        }
        for lab, agent_count in rows.all()
    ]


@router.get("/live/labs/{lab_id}")
async def live_lab_detail(lab_id: UUID, db: DbSession):
    """Get a single lab with its agents for the public live page."""
    from sqlalchemy import select
    from app.models.orchestrator import Lab, LabAgent, AIModel

    lab = (await db.execute(select(Lab).where(Lab.id == lab_id))).scalars().first()
    if not lab or not lab.is_public:
        # 404 (not 403) so a private lab is indistinguishable from a deleted one
        raise HTTPException(404, "Lab not found")

    # Fetch agents with model name
    stmt = (
        select(LabAgent, AIModel.name.label("model_name"))
        .outerjoin(AIModel, LabAgent.model_id == AIModel.id)
        .where(LabAgent.lab_id == lab_id)
        .order_by(LabAgent.sort_order)
    )
    rows = (await db.execute(stmt)).all()

    # Get orchestrator model name
    orch_model_name = None
    if lab.orchestrator_model_id:
        m = (await db.execute(select(AIModel.name).where(AIModel.id == lab.orchestrator_model_id))).scalars().first()
        orch_model_name = m

    agents = []
    for agent, model_name in rows:
        agents.append({
            "id": str(agent.id),
            "name": agent.name,
            "model_id": str(agent.model_id) if agent.model_id else None,
            "model_name": model_name,
            "temperature": agent.temperature or 0.7,
            "tools_count": len(agent.tools or []),
            "is_active": agent.is_active,
        })

    return {
        "id": str(lab.id),
        "name": lab.name,
        "description": lab.description or "",
        "status": lab.status or "idle",
        "loop_type": lab.loop_type or "plan_execute",
        "current_iteration": lab.current_iteration or 0,
        "max_iterations": lab.max_iterations or 10,
        "agent_count": len(agents),
        "updated_at": lab.updated_at.isoformat() if lab.updated_at else None,
        "agents": agents,
        "orchestrator_model_id": str(lab.orchestrator_model_id) if lab.orchestrator_model_id else None,
        "orchestrator_model_name": orch_model_name,
    }


@router.get("/live/labs/{lab_id}/messages")
async def live_lab_messages(
    lab_id: UUID,
    db: DbSession,
    limit: int = Query(100, ge=1, le=500),
):
    """Return recent lab messages (sanitized — no raw tool I/O)."""
    from app.repositories.lab_repo import LabMessageRepository, LabRepository

    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab or not lab.is_public:
        raise HTTPException(404, "Lab not found")

    msgs = await LabMessageRepository(db).get_recent(lab_id, limit=limit)
    return [
        {
            "id": str(m.id),
            "iteration": m.iteration or 0,
            "sender_type": m.sender_type or "",
            "sender_name": m.sender_name or None,
            "content": (m.content or "")[:2000],
            "message_type": m.message_type or "",
            "model_used": m.model_used,
            "provider_used": m.provider_used,
            "tokens_in": m.tokens_in or 0,
            "tokens_out": m.tokens_out or 0,
            "duration_ms": m.duration_ms or 0,
            "tool_name": m.tool_name,
            "created_at": m.created_at.isoformat(),
        }
        for m in msgs
    ]


@router.get("/live/labs/{lab_id}/resources")
async def live_lab_resources(lab_id: UUID, db: DbSession):
    """Return lab resources metadata (no file content)."""
    from app.repositories.lab_repo import LabRepository, LabResourceRepository

    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab or not lab.is_public:
        raise HTTPException(404, "Lab not found")

    resources = await LabResourceRepository(db).get_by_lab(lab_id)
    return [
        {
            "id": str(r.id),
            "filename": r.filename,
            "original_name": r.original_name,
            "content_type": r.content_type or "",
            "size_bytes": r.size_bytes or 0,
            "resource_type": r.resource_type or "",
        }
        for r in resources
    ]


@router.get("/live/servers")
async def live_servers(db: DbSession):
    """Return servers with status (no agent tokens)."""
    from app.services.server_service import ServerService

    servers = await ServerService(db).list_servers()
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "host": s.host or "",
            "status": s.status or "offline",
            "gpu_info": s.gpu_info,
            "os_info": s.os_info,
            "last_heartbeat": s.last_heartbeat.isoformat() if s.last_heartbeat else None,
        }
        for s in servers
    ]


@router.get("/live/providers")
async def live_providers(db: DbSession):
    """Return AI providers (no API keys or base URLs)."""
    from sqlalchemy import select
    from app.models.orchestrator import AIProvider
    from app.models.server import Server

    stmt = (
        select(AIProvider, Server.name.label("server_name"))
        .outerjoin(Server, AIProvider.server_id == Server.id)
        .order_by(AIProvider.name)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "provider_type": p.provider_type or "",
            "is_active": p.is_active,
            "server_id": str(p.server_id) if p.server_id else None,
            "server_name": server_name,
        }
        for p, server_name in rows
    ]


@router.get("/live/models")
async def live_models(db: DbSession):
    """Return available AI models (deduplicated, only available ones)."""
    from sqlalchemy import select, func, case, Integer
    from app.models.orchestrator import AIModel, AIProvider
    from app.models.server import Server

    stmt = (
        select(
            AIModel.model_identifier,
            func.count(AIModel.id).label("total_providers"),
            func.sum(case((AIModel.is_available == True, 1), else_=0)).label("available_providers"),
            func.array_agg(func.coalesce(Server.name, AIProvider.name)).label("server_names"),
            func.max(AIModel.is_available.cast(Integer)).label("any_available"),
        )
        .join(AIProvider, AIModel.provider_id == AIProvider.id)
        .outerjoin(Server, AIProvider.server_id == Server.id)
        .group_by(AIModel.model_identifier)
        .having(func.max(AIModel.is_available.cast(Integer)) == 1)
        .order_by(AIModel.model_identifier)
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            "model_identifier": row.model_identifier,
            "available_providers": row.available_providers,
            "server_names": list(set(row.server_names)) if row.server_names else [],
        }
        for row in rows
    ]


# ══════════════════════════════════════════════════
# Public Live — File downloads (read-only, no auth)
# ══════════════════════════════════════════════════


@router.get("/live/labs/{lab_id}/resources/{resource_id}/content")
async def live_resource_content(lab_id: UUID, resource_id: UUID, db: DbSession):
    """Read content/metadata of an uploaded resource (public, no sensitive data)."""
    from app.repositories.lab_repo import LabResourceRepository

    resource = await LabResourceRepository(db).get_by_id(resource_id)
    if not resource or resource.lab_id != lab_id:
        raise HTTPException(404, "Resource not found")

    file_path = LAB_RESOURCES_ROOT / str(lab_id) / resource.filename
    if not file_path.is_file():
        raise HTTPException(404, "File not found")

    mime = resource.content_type or "application/octet-stream"
    is_text = mime.startswith("text/") or mime in (
        "application/json", "application/javascript", "application/xml",
        "application/x-yaml", "application/x-sh",
    ) or file_path.suffix in (
        ".md", ".py", ".js", ".ts", ".html", ".css", ".json", ".yml", ".yaml",
        ".sh", ".txt", ".csv", ".xml", ".toml", ".cfg", ".ini", ".log",
    )
    is_image = mime.startswith("image/")
    is_audio = mime.startswith("audio/")
    is_video = mime.startswith("video/")

    content = None
    if is_text:
        try:
            raw = file_path.read_text(errors="replace")
            if len(raw) > 512_000:
                raw = raw[:512_000] + "\n... [truncated at 512 KB]"
            content = raw
        except Exception:
            content = None

    return {
        "id": str(resource.id),
        "original_name": resource.original_name,
        "size_bytes": resource.size_bytes,
        "content_type": mime,
        "is_text": is_text,
        "is_image": is_image,
        "is_audio": is_audio,
        "is_video": is_video,
        "content": content,
    }


@router.get("/live/labs/{lab_id}/resources/{resource_id}/download")
async def live_resource_download(lab_id: UUID, resource_id: UUID, db: DbSession):
    """Download an uploaded resource (public)."""
    from app.repositories.lab_repo import LabResourceRepository

    resource = await LabResourceRepository(db).get_by_id(resource_id)
    if not resource or resource.lab_id != lab_id:
        raise HTTPException(404, "Resource not found")

    file_path = LAB_RESOURCES_ROOT / str(lab_id) / resource.filename
    if not file_path.is_file():
        raise HTTPException(404, "File not found")

    return FileResponse(
        path=str(file_path),
        filename=resource.original_name,
        media_type=resource.content_type,
    )


@router.get("/live/labs/{lab_id}/output-files/content")
async def live_output_file_content(lab_id: UUID, path: str, db: DbSession):
    """Read content of an output file (public)."""
    from app.repositories.lab_repo import LabRepository

    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab or not lab.is_public:
        raise HTTPException(404, "Lab not found")

    ws_dir = LAB_RESOURCES_ROOT / str(lab_id)
    try:
        target = (ws_dir / path).resolve()
        if not str(target).startswith(str(ws_dir.resolve())):
            raise HTTPException(400, "Path traversal denied.")
    except Exception:
        raise HTTPException(400, "Invalid path.")

    if not target.is_file():
        raise HTTPException(404, "File not found")

    mime, _ = mimetypes.guess_type(target.name)
    mime = mime or "application/octet-stream"
    stat = target.stat()

    is_text = mime.startswith("text/") or mime in (
        "application/json", "application/javascript", "application/xml",
        "application/x-yaml", "application/x-sh",
    ) or target.suffix in (
        ".md", ".py", ".js", ".ts", ".html", ".css", ".json", ".yml", ".yaml",
        ".sh", ".txt", ".csv", ".xml", ".toml", ".cfg", ".ini", ".log",
    )
    is_image = mime.startswith("image/")
    is_audio = mime.startswith("audio/")
    is_video = mime.startswith("video/")

    content = None
    if is_text:
        try:
            raw = target.read_text(errors="replace")
            if len(raw) > 512_000:
                raw = raw[:512_000] + "\n... [truncated at 512 KB]"
            content = raw
        except Exception:
            content = None

    return {
        "path": path,
        "name": target.name,
        "size_bytes": stat.st_size,
        "content_type": mime,
        "is_text": is_text,
        "is_image": is_image,
        "is_audio": is_audio,
        "is_video": is_video,
        "content": content,
    }


@router.get("/live/labs/{lab_id}/output-files/download")
async def live_output_file_download(lab_id: UUID, path: str, db: DbSession):
    """Download an output file (public)."""
    from app.repositories.lab_repo import LabRepository

    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab or not lab.is_public:
        raise HTTPException(404, "Lab not found")

    ws_dir = LAB_RESOURCES_ROOT / str(lab_id)
    try:
        target = (ws_dir / path).resolve()
        if not str(target).startswith(str(ws_dir.resolve())):
            raise HTTPException(400, "Path traversal denied.")
    except Exception:
        raise HTTPException(400, "Invalid path.")

    if not target.is_file():
        raise HTTPException(404, "File not found")

    mime, _ = mimetypes.guess_type(target.name)
    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type=mime or "application/octet-stream",
    )
