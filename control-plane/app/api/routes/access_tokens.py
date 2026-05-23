"""Bob Manager — Access Token management routes (admin-only)."""

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import DbSession, get_current_user
from app.repositories.access_token_repo import (
    AccessTokenRepository,
    QuoteRequestRepository,
    TrialRequestRepository,
)
from app.repositories.blog_post_repo import BlogPostRepository, BlogTokenRepository
from app.services.authorization import check_permission, Permission
from app.services.email_service import send_token_to_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/access-tokens", tags=["access-tokens"])


# ── Schemas ──────────────────────────────────────

class CreateTokenIn(BaseModel):
    label: str = ""
    email: str = ""
    expires_at: datetime
    send_email: bool = True


class TokenOut(BaseModel):
    id: str
    token: str
    label: str
    email: str
    expires_at: str
    revoked: bool
    created_at: str


class TrialRequestOut(BaseModel):
    id: str
    name: str
    email: str
    enterprise: str
    role: str
    purpose: str
    status: str
    created_at: str


class UpdateTrialStatusIn(BaseModel):
    status: str


class QuoteRequestAdminOut(BaseModel):
    id: str
    name: str
    email: str
    company: str
    phone: str
    plan: str
    description: str
    status: str
    created_at: str


class UpdateQuoteStatusIn(BaseModel):
    status: str


# ── Token Endpoints ──────────────────────────────

@router.get("", response_model=list[TokenOut])
async def list_tokens(db: DbSession, _user: dict = Depends(get_current_user)):
    """List all access tokens."""
    repo = AccessTokenRepository(db)
    tokens = await repo.get_all()
    return [
        TokenOut(
            id=str(t.id),
            token=t.token,
            label=t.label,
            email=t.email,
            expires_at=t.expires_at.isoformat(),
            revoked=t.revoked,
            created_at=t.created_at.isoformat(),
        )
        for t in tokens
    ]


@router.post("", response_model=TokenOut, status_code=201)
async def create_token(
    payload: CreateTokenIn,
    db: DbSession,
    _user: dict = Depends(get_current_user),
):
    """Generate a new time-limited access token."""
    repo = AccessTokenRepository(db)
    token = await repo.create(
        label=payload.label.strip(),
        email=payload.email.strip(),
        expires_at=payload.expires_at,
    )
    # Send token to user by email if requested and email is provided
    if payload.send_email and token.email:
        try:
            await send_token_to_user(
                email=token.email,
                token=token.token,
                label=token.label,
                expires_at=token.expires_at.isoformat(),
            )
        except Exception:
            logger.exception("Failed to send token email to %s", token.email)
    return TokenOut(
        id=str(token.id),
        token=token.token,
        label=token.label,
        email=token.email,
        expires_at=token.expires_at.isoformat(),
        revoked=token.revoked,
        created_at=token.created_at.isoformat(),
    )


@router.delete("/{token_id}")
async def revoke_token(
    token_id: UUID,
    db: DbSession,
    _user: dict = Depends(get_current_user),
):
    """Revoke an access token."""
    repo = AccessTokenRepository(db)
    revoked = await repo.revoke(token_id)
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found.")
    return {"message": "Token revoked."}


# ── Trial Request Endpoints ──────────────────────

@router.get("/trial-requests", response_model=list[TrialRequestOut])
async def list_trial_requests(db: DbSession, _user: dict = Depends(get_current_user)):
    """List all trial requests."""
    repo = TrialRequestRepository(db)
    requests = await repo.get_all()
    return [
        TrialRequestOut(
            id=str(r.id),
            name=r.name,
            email=r.email,
            enterprise=r.enterprise,
            role=r.role,
            purpose=r.purpose,
            status=r.status,
            created_at=r.created_at.isoformat(),
        )
        for r in requests
    ]


@router.patch("/trial-requests/{request_id}", response_model=TrialRequestOut)
async def update_trial_request_status(
    request_id: UUID,
    payload: UpdateTrialStatusIn,
    db: DbSession,
    _user: dict = Depends(get_current_user),
):
    """Update the status of a trial request."""
    repo = TrialRequestRepository(db)
    updated = await repo.update_status(request_id, payload.status.strip())
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trial request not found.")
    return TrialRequestOut(
        id=str(updated.id),
        name=updated.name,
        email=updated.email,
        enterprise=updated.enterprise,
        role=updated.role,
        purpose=updated.purpose,
        status=updated.status,
        created_at=updated.created_at.isoformat(),
    )


# ── Quote Request Endpoints ──────────────────────

@router.get("/quote-requests", response_model=list[QuoteRequestAdminOut])
async def list_quote_requests(db: DbSession, _user: dict = Depends(get_current_user)):
    """List all quote requests."""
    repo = QuoteRequestRepository(db)
    requests = await repo.get_all()
    return [
        QuoteRequestAdminOut(
            id=str(r.id),
            name=r.name,
            email=r.email,
            company=r.company,
            phone=r.phone,
            plan=r.plan,
            description=r.description,
            status=r.status,
            created_at=r.created_at.isoformat(),
        )
        for r in requests
    ]


@router.patch("/quote-requests/{request_id}", response_model=QuoteRequestAdminOut)
async def update_quote_request_status(
    request_id: UUID,
    payload: UpdateQuoteStatusIn,
    db: DbSession,
    _user: dict = Depends(get_current_user),
):
    """Update the status of a quote request."""
    repo = QuoteRequestRepository(db)
    updated = await repo.update_status(request_id, payload.status.strip())
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote request not found.")
    return QuoteRequestAdminOut(
        id=str(updated.id),
        name=updated.name,
        email=updated.email,
        company=updated.company,
        phone=updated.phone,
        plan=updated.plan,
        description=updated.description,
        status=updated.status,
        created_at=updated.created_at.isoformat(),
    )


# ── ACL Management ───────────────────────────────

# Map of resource type → (model class, table name)
_ACL_MODELS = {
    "lab": "app.models.orchestrator:Lab",
    "project": "app.models.project:Project",
    "resource": "app.models.resource:Resource",
    "rag_collection": "app.models.rag:RagCollection",
    "wallet": "app.models.wallet:Wallet",
}


def _get_model(resource_type: str):
    """Dynamically import the model class for a resource type."""
    ref = _ACL_MODELS.get(resource_type)
    if not ref:
        raise HTTPException(400, f"Unknown resource type: {resource_type}")
    module_path, class_name = ref.split(":")
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


class AclUpdateIn(BaseModel):
    resource_type: str  # lab, project, resource, rag_collection, wallet
    resource_id: UUID
    acl: dict  # {"owner": "...", "editors": [...], "viewers": [...]}
    # Optional: for resource types that carry an ``is_public`` flag (labs today),
    # the same MANAGE-permitted PATCH can flip the public-on-/live visibility in
    # the same round-trip. Ignored when the target resource doesn't have the
    # column. ``None`` means "leave unchanged".
    is_public: bool | None = None


@router.patch("/acl")
async def update_acl(
    payload: AclUpdateIn,
    db: DbSession,
    user: dict = Depends(get_current_user),
):
    """Update ACL on any resource. Requires MANAGE permission (owner or admin)."""
    model = _get_model(payload.resource_type)
    result = await db.execute(select(model).where(model.id == payload.resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(404, "Resource not found")
    check_permission(user, resource.acl, Permission.MANAGE)

    # Validate ACL structure
    acl = payload.acl
    if not isinstance(acl.get("owner"), str) or not acl.get("owner"):
        raise HTTPException(400, "ACL must have a non-empty 'owner' string")
    if not isinstance(acl.get("editors", []), list):
        raise HTTPException(400, "'editors' must be a list")
    if not isinstance(acl.get("viewers", []), list):
        raise HTTPException(400, "'viewers' must be a list")

    values: dict = {"acl": acl}
    if payload.is_public is not None and hasattr(model, "is_public"):
        values["is_public"] = bool(payload.is_public)

    await db.execute(
        sa_update(model).where(model.id == payload.resource_id).values(**values)
    )
    await db.flush()
    return {"status": "updated", "acl": acl, "is_public": values.get("is_public")}


# ── Platform Settings (Infra Whitelist) ──────────

class InfraWhitelistIn(BaseModel):
    emails: list[str]


@router.get("/platform/infra-access")
async def get_infra_whitelist(
    db: DbSession,
    _user: dict = Depends(get_current_user),
):
    """Get the infra access whitelist."""
    from app.models.platform_settings import PlatformSettings
    result = await db.execute(
        select(PlatformSettings).where(PlatformSettings.key == "infra_access")
    )
    row = result.scalar_one_or_none()
    return row.value if row else {"emails": []}


@router.put("/platform/infra-access")
async def update_infra_whitelist(
    payload: InfraWhitelistIn,
    db: DbSession,
    _user: dict = Depends(get_current_user),
):
    """Update the infra access whitelist. Admin only."""
    from app.models.platform_settings import PlatformSettings
    result = await db.execute(
        select(PlatformSettings).where(PlatformSettings.key == "infra_access")
    )
    row = result.scalar_one_or_none()
    value = {"emails": payload.emails}
    if row:
        row.value = value
    else:
        db.add(PlatformSettings(key="infra_access", value=value))
    await db.flush()
    return value


# ── Blog Token Management (admin) ────────────────


class BlogTokenOut(BaseModel):
    id: str
    token: str
    label: str
    revoked: bool
    created_at: str


class CreateBlogTokenIn(BaseModel):
    label: str = ""


class BlogPostAdminOut(BaseModel):
    id: str
    title: str
    identity: str
    tags: list[str]
    created_at: str


@router.get("/blog-tokens", response_model=list[BlogTokenOut])
async def list_blog_tokens(db: DbSession, _user: dict = Depends(get_current_user)):
    """List all blog tokens."""
    repo = BlogTokenRepository(db)
    tokens = await repo.get_all()
    return [
        BlogTokenOut(
            id=str(t.id),
            token=t.token,
            label=t.label,
            revoked=t.revoked,
            created_at=t.created_at.isoformat(),
        )
        for t in tokens
    ]


@router.post("/blog-tokens", response_model=BlogTokenOut, status_code=201)
async def create_blog_token(
    payload: CreateBlogTokenIn,
    db: DbSession,
    _user: dict = Depends(get_current_user),
):
    """Create a new blog token for agent posting."""
    repo = BlogTokenRepository(db)
    token = await repo.create(label=payload.label.strip())
    return BlogTokenOut(
        id=str(token.id),
        token=token.token,
        label=token.label,
        revoked=token.revoked,
        created_at=token.created_at.isoformat(),
    )


@router.delete("/blog-tokens/{token_id}")
async def revoke_blog_token(
    token_id: UUID,
    db: DbSession,
    _user: dict = Depends(get_current_user),
):
    """Revoke a blog token."""
    repo = BlogTokenRepository(db)
    revoked = await repo.revoke(token_id)
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blog token not found.")
    return {"message": "Blog token revoked."}


@router.get("/blog-posts", response_model=list[BlogPostAdminOut])
async def list_blog_posts_admin(db: DbSession, _user: dict = Depends(get_current_user)):
    """List all blog posts (admin view)."""
    repo = BlogPostRepository(db)
    posts = await repo.get_all(limit=200)
    return [
        BlogPostAdminOut(
            id=str(p.id),
            title=p.title,
            identity=p.identity,
            tags=p.tags or [],
            created_at=p.created_at.isoformat(),
        )
        for p in posts
    ]


@router.delete("/blog-posts/{post_id}")
async def delete_blog_post(
    post_id: UUID,
    response: Response,
    db: DbSession,
    _user: dict = Depends(get_current_user),
):
    """Delete a blog post."""
    repo = BlogPostRepository(db)
    # Capture slug before delete for cache invalidation.
    existing = await repo.get_by_id(post_id)
    deleted = await repo.delete(post_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blog post not found.")
    if existing and getattr(existing, "slug", None):
        response.headers["Cache-Tag"] = f"blog,blog-{existing.slug}"
    else:
        response.headers["Cache-Tag"] = "blog"
    return {"message": "Blog post deleted."}
