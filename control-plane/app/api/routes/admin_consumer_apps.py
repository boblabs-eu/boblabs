"""Bob Manager — Consumer App admin routes.

CRUD over the ``consumer_apps`` table that backs the internal HMAC channel.
The freshly minted secret is returned **once** at creation time and never
again — the same UX as ``access_tokens``. Admins must copy it into the
consumer app's ``.env`` immediately.
"""

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.dependencies import DbSession, require_admin
from app.repositories.consumer_app_repo import ConsumerAppRepository
from app.services.consumer_apps import generate_secret

router = APIRouter(prefix="/admin/consumer-apps", tags=["admin", "consumer-apps"])

_APP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$")


class ConsumerAppOut(BaseModel):
    id: str
    app_id: str
    name: str
    notes: str
    revoked_at: str | None
    last_used_at: str | None
    created_at: str


class ConsumerAppWithSecretOut(ConsumerAppOut):
    """Returned **only** at creation time. The plain secret never appears
    again after this response."""

    secret: str = Field(
        description=(
            "One-time HMAC secret. Copy it into the consumer app's .env as "
            "BOB_APP_SECRET. Bob-api stores this same value in the DB so it "
            "can verify HMAC signatures; it is not retrievable again via the "
            "API."
        ),
    )


class CreateConsumerAppIn(BaseModel):
    app_id: str
    name: str = ""
    notes: str = ""


def _to_out(app) -> ConsumerAppOut:
    return ConsumerAppOut(
        id=str(app.id),
        app_id=app.app_id,
        name=app.name,
        notes=app.notes,
        revoked_at=app.revoked_at.isoformat() if app.revoked_at else None,
        last_used_at=app.last_used_at.isoformat() if app.last_used_at else None,
        created_at=app.created_at.isoformat(),
    )


@router.get("", response_model=list[ConsumerAppOut])
async def list_consumer_apps(
    db: DbSession,
    _user: dict = Depends(require_admin),
):
    """List all registered consumer apps (without secrets)."""
    repo = ConsumerAppRepository(db)
    return [_to_out(a) for a in await repo.get_all()]


@router.post("", response_model=ConsumerAppWithSecretOut, status_code=201)
async def create_consumer_app(
    payload: CreateConsumerAppIn,
    db: DbSession,
    _user: dict = Depends(require_admin),
):
    """Register a new consumer app and return its one-time HMAC secret."""
    app_id = payload.app_id.strip().lower()
    if not _APP_ID_RE.match(app_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "app_id must be lowercase alphanumeric with optional - or _, "
            "2–64 chars, start and end with [a-z0-9].",
        )

    repo = ConsumerAppRepository(db)
    existing = await repo.get_by_app_id(app_id)
    if existing is not None:
        if existing.revoked_at is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"app_id '{app_id}' is already registered (revoke it first to recreate).",
            )
        # Same slug previously revoked — hard-delete the old row to free
        # the UNIQUE(app_id) slot and let the operator recreate cleanly.
        await repo.delete(existing.id)

    secret = generate_secret()
    record = await repo.create(
        app_id=app_id,
        name=payload.name.strip(),
        secret=secret,
        notes=payload.notes.strip(),
    )
    base = _to_out(record)
    return ConsumerAppWithSecretOut(**base.model_dump(), secret=secret)


@router.delete("/{app_uuid}")
async def revoke_consumer_app(
    app_uuid: UUID,
    db: DbSession,
    _user: dict = Depends(require_admin),
):
    """Revoke a consumer app. Future requests with its secret return 401."""
    repo = ConsumerAppRepository(db)
    revoked = await repo.revoke(app_uuid)
    if not revoked:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Consumer app not found or already revoked.",
        )
    return {"message": "Consumer app revoked."}


@router.delete("/{app_uuid}/permanent")
async def delete_consumer_app(
    app_uuid: UUID,
    db: DbSession,
    _user: dict = Depends(require_admin),
):
    """Hard-delete a consumer app row. Frees the app_id slug for reuse and is
    irreversible. Any deployment still holding the old secret will get 401s."""
    repo = ConsumerAppRepository(db)
    deleted = await repo.delete(app_uuid)
    if not deleted:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Consumer app not found.",
        )
    return {"message": "Consumer app deleted."}
