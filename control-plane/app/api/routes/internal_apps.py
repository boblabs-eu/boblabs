"""Bob Manager — Internal Apps router.

Generic HMAC-authenticated channel for consumer apps to drive bob-api:
direct ComfyUI dispatch, lab cloning, LLM completions, STT, ffmpeg.
HMAC-SHA256 over ``<timestamp>.<body>``. Caller identifies itself with
``X-App-Id``; the matching HMAC key is looked up in the
``consumer_apps`` table. Outgoing callbacks are signed with the same
key so the consumer app can verify them.

NOTE — grep-gate allow-list: this file references ``SHOWROOM_UPLOADS_PATH``
and ``SHOWROOM_LAB_TIMEOUT_SEC`` as legacy env-var aliases, kept for
backward compat with pre-Phase-1 deployments. The publish-public.sh grep
gate must allow-list these two identifiers in this file.
"""

import asyncio
import hmac
import hashlib
import json
import logging
import os
import random
import time
import uuid as uuid_mod
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.models.orchestrator import AIProvider
from app.services.comfyui_discovery import comfyui_health_check

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/apps", tags=["internal"])

# Volume root for generation artifacts. Falls back to the legacy
# SHOWROOM_UPLOADS_PATH so existing deployments keep working.
APP_UPLOADS_ROOT = Path(
    os.environ.get("APP_UPLOADS_ROOT")
    or os.environ.get("SHOWROOM_UPLOADS_PATH")
    or "/data/app_uploads"
)
REPLAY_WINDOW_SEC = 300
COMFYUI_TIMEOUT_SEC = 300
COMFYUI_MAX_WAIT_SEC = int(os.environ.get("COMFYUI_MAX_WAIT_SEC", "1800"))


def _app_upload_dir(app_id: str, generation_id) -> Path:
    """Return the per-app, per-generation directory for output artifacts."""
    return APP_UPLOADS_ROOT / app_id / str(generation_id)


def _make_template_tag(app_id: str, name: str) -> str:
    return f"app:{app_id}:template:{name}"


def _make_run_tag(app_id: str, generation_id) -> str:
    return f"app:{app_id}:run:{generation_id}"


async def _send_callback(
    *,
    app_id: str,
    callback_url: str,
    payload: dict,
    log_prefix: str,
) -> None:
    """Sign and POST a callback to a consumer app's webhook URL.

    Looks up the consumer app's HMAC secret in ``consumer_apps`` by
    ``app_id`` and signs the body with it. Sends ``X-App-Id``,
    ``X-App-Timestamp``, ``X-App-Signature``. Retries 3× with exponential
    backoff. Drops the callback (with an error log) if the app has no
    valid registered key — there is no legacy env-secret fallback.
    """
    from app.database import async_session
    from app.repositories.consumer_app_repo import ConsumerAppRepository

    body = json.dumps(payload, separators=(",", ":")).encode()

    async with async_session() as db:
        record = await ConsumerAppRepository(db).get_by_app_id(app_id)

    if not record or record.revoked_at is not None:
        logger.error(
            "%s no active consumer-app secret for app_id=%s; dropping callback",
            log_prefix, app_id,
        )
        return

    ts, sig = _sign(body, record.secret)
    headers = {
        "Content-Type": "application/json",
        "X-App-Id": app_id,
        "X-App-Timestamp": ts,
        "X-App-Signature": sig,
    }
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(callback_url, content=body, headers=headers)
                resp.raise_for_status()
                logger.info(
                    "%s callback delivered (status=%s)",
                    log_prefix, payload.get("status"),
                )
                return
        except Exception as exc:
            logger.warning(
                "%s callback attempt %d failed: %r",
                log_prefix, attempt + 1, exc,
            )
            await asyncio.sleep(2 ** attempt)
    logger.error("%s callback gave up", log_prefix)


async def _comfyui_queue_depth(base_url: str) -> int:
    """Approximate queue depth (running + pending) on a ComfyUI server.

    Returns a large sentinel on failure so the provider sorts last.
    """
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/queue")
            resp.raise_for_status()
            data = resp.json()
            return len(data.get("queue_running", [])) + len(data.get("queue_pending", []))
    except Exception:
        return 10**6


async def _pick_healthy_comfyui_provider(db) -> AIProvider:
    """Dispatcher-style ComfyUI selector: filter active providers by live health,
    then pick the least-loaded one (by /queue depth). Raises 503 if none alive.
    """
    stmt = select(AIProvider).where(
        AIProvider.provider_type == "comfyui",
        AIProvider.is_active.is_(True),
    )
    providers = list((await db.execute(stmt)).scalars().all())
    if not providers:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No active ComfyUI provider")

    healths = await asyncio.gather(
        *(comfyui_health_check(p.base_url) for p in providers),
        return_exceptions=True,
    )
    healthy = [p for p, h in zip(providers, healths) if h is True]
    if not healthy:
        names = ", ".join(f"{p.name}({p.base_url})" for p in providers)
        logger.warning("No healthy ComfyUI provider among active=[%s]", names)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"No healthy ComfyUI provider (checked: {names})",
        )

    depths = await asyncio.gather(*(_comfyui_queue_depth(p.base_url) for p in healthy))
    chosen = min(zip(healthy, depths), key=lambda pd: pd[1])[0]
    logger.info(
        "ComfyUI dispatcher picked %s (%s) — healthy=%d/%d",
        chosen.name, chosen.base_url, len(healthy), len(providers),
    )
    return chosen


async def _auth(request: Request, db) -> tuple[bytes, str]:
    """Read body, verify HMAC, return ``(body, resolved_app_id)``.

    Every request must carry ``X-App-Id``, ``X-App-Timestamp`` and
    ``X-App-Signature``. Auth is delegated to
    :func:`app.services.consumer_apps.verify_signed_request`.
    """
    from app.services.consumer_apps import verify_signed_request

    body = await request.body()
    h = request.headers
    resolved = await verify_signed_request(
        body=body,
        timestamp=h.get("X-App-Timestamp"),
        signature=h.get("X-App-Signature"),
        app_id=h.get("X-App-Id"),
        db=db,
    )
    return body, resolved


def _sign(body: bytes, secret: str) -> tuple[str, str]:
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return ts, sig


class ImportLabIn(BaseModel):
    blueprint: dict
    name_override: str | None = None
    force_refresh: bool = False  # If True, delete existing lab with same name and re-import.


class ImportLabOut(BaseModel):
    lab_id: str


class CreateRagIn(BaseModel):
    name: str  # short name; will be namespaced as app__<app_id>__<name>
    display_name: str | None = None
    description: str = ""
    embedding_model: str = "all-MiniLM-L6-v2"
    distance_metric: str = "cosine"


class RagOut(BaseModel):
    collection_id: str
    name: str  # short name (un-namespaced)
    collection_name: str  # full namespaced name (for use in blueprint rag_access)
    display_name: str
    embedding_model: str
    embedding_dim: int
    distance_metric: str


class ListRagsOut(BaseModel):
    rags: list[RagOut]


class DeleteRagOut(BaseModel):
    deleted: bool


class GrantRagAccessIn(BaseModel):
    lab_id: str
    rag_name: str  # short name (un-namespaced)
    can_read: bool = True
    can_write: bool = False


class GrantRagAccessOut(BaseModel):
    lab_id: str
    collection_id: str
    collection_name: str
    can_read: bool
    can_write: bool


class RevokeRagAccessIn(BaseModel):
    lab_id: str
    rag_name: str  # short name (un-namespaced)


class RevokeRagAccessOut(BaseModel):
    revoked: bool


class RunIn(BaseModel):
    template_lab_id: str | None = None
    generation_id: str
    inputs: dict[str, Any]
    callback_url: str


class RunOut(BaseModel):
    lab_id: str
    status: str = "started"


class ContextFileIn(BaseModel):
    path: str
    content: str


class OutputArtifactIn(BaseModel):
    src_path: str
    public_name: str


class RunLabIn(BaseModel):
    template_lab_id: str
    generation_id: str
    callback_url: str
    context_files: list[ContextFileIn] = []
    output_artifacts: list[OutputArtifactIn] = []
    name_suffix: str | None = None  # e.g. company name — appended to clone lab name


class RunLabOut(BaseModel):
    lab_id: str
    status: str = "started"


LAB_RESOURCES_ROOT = Path(os.environ.get("LAB_RESOURCES_PATH", "/data/lab_resources"))
LAB_RUN_TIMEOUT_SEC = int(os.environ.get("SHOWROOM_LAB_TIMEOUT_SEC", "1800"))


def _safe_relpath(rel: str) -> Path:
    """Validate a relative path is clean (no .., no absolute, no leading /)."""
    if not rel or rel.startswith("/") or rel.startswith("\\"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid path: {rel}")
    p = Path(rel)
    if p.is_absolute() or any(part in ("..", "") for part in p.parts):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid path: {rel}")
    return p


def _is_subpath(child: Path, parent: Path) -> bool:
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


@router.post("/import_lab", response_model=ImportLabOut)
async def import_template_lab(
    request: Request,
    db: DbSession,
):
    """Import a lab blueprint (idempotent by lab name).

    If a lab with the same name (after applying ``name_override``) already exists,
    its id is returned without creating a new one. Otherwise the blueprint is
    imported through the standard /labs/import path.
    """
    from app.api.routes.labs_blueprint import import_lab as _import_lab
    from app.repositories.lab_repo import LabRepository
    from app.schemas.orchestrator import LabBlueprint

    body, app_id = await _auth(request, db)
    payload = ImportLabIn.model_validate_json(body)

    blueprint_dict = dict(payload.blueprint)
    if payload.name_override:
        bp_lab = dict(blueprint_dict.get("lab", {}))
        bp_lab["name"] = payload.name_override
        blueprint_dict["lab"] = bp_lab

    target_name = blueprint_dict.get("lab", {}).get("name")
    if not target_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Blueprint missing lab.name")

    # Idempotency: reuse existing lab with this name if present (unless force_refresh).
    from app.models.orchestrator import Lab
    existing = (
        await db.execute(select(Lab).where(Lab.name == target_name))
    ).scalars().first()
    if existing and not payload.force_refresh:
        logger.info("[app] import_lab reusing existing lab '%s' (id=%s)", target_name, existing.id)
        return ImportLabOut(lab_id=str(existing.id))
    if existing and payload.force_refresh:
        logger.warning("[app] import_lab force_refresh: deleting existing lab '%s' (id=%s) and re-importing", target_name, existing.id)
        await db.delete(existing)
        await db.flush()

    try:
        bp = LabBlueprint.model_validate(blueprint_dict)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid blueprint: {exc}")

    # Pre-validate rag_access: every referenced collection must be owned by this app.
    # Operator-UI blueprints can reference any collection; consumer apps cannot.
    if bp.lab.rag_access:
        from app.services.rag_service import RagService
        svc = RagService(db)
        for ref in bp.lab.rag_access:
            try:
                await svc.assert_owned_by_app(ref.collection_name, app_id)
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    f"{exc} Create your own copy via /create_rag first.",
                )

    lab_resp = await _import_lab(bp, db, user={"sub": "system@boblabs.internal", "role": "admin"})
    await db.commit()
    new_lab_id = lab_resp["id"] if isinstance(lab_resp, dict) else getattr(lab_resp, "id", None)
    logger.info("[app] import_lab created lab '%s' (id=%s)", target_name, new_lab_id)
    return ImportLabOut(lab_id=str(new_lab_id))


# ─────────────────────────────────────────────────────────────────────────────
# Consumer-app RAG collections
#
# Mirror the lab-template pattern: collections are namespaced
# ``app__<app_id>__<name>`` in Postgres+Qdrant, with ``acl.tag = app:<app_id>:rag:<name>``
# so the operator UI can filter them out the same way it filters app-owned labs.
# ─────────────────────────────────────────────────────────────────────────────


def _collection_to_rag_out(collection, app_id: str) -> RagOut:
    """Strip the namespace prefix and project the model to RagOut."""
    full = collection.name
    short = full
    expected_prefix = f"app__{app_id}__"
    if full.startswith(expected_prefix):
        short = full[len(expected_prefix):]
    return RagOut(
        collection_id=str(collection.id),
        name=short,
        collection_name=full,
        display_name=collection.display_name,
        embedding_model=collection.embedding_model,
        embedding_dim=collection.embedding_dim,
        distance_metric=collection.distance_metric,
    )


@router.post("/create_rag", response_model=RagOut, status_code=status.HTTP_201_CREATED)
async def create_app_rag(request: Request, db: DbSession):
    """Create an app-owned RAG collection.

    The collection is namespaced as ``app__<app_id>__<name>`` so it cannot
    collide with operator-UI or other-app collections, and stamped with
    ``acl.tag = app:<app_id>:rag:<name>`` so the operator UI hides it.

    Idempotent on ``(app_id, name)``: a second call with the same args
    returns the existing collection rather than erroring.
    """
    from app.services.rag_service import RagService

    body, app_id = await _auth(request, db)
    payload = CreateRagIn.model_validate_json(body)

    try:
        collection = await RagService(db).create_app_collection(
            app_id=app_id,
            name=payload.name,
            display_name=payload.display_name,
            description=payload.description,
            embedding_model=payload.embedding_model,
            distance_metric=payload.distance_metric,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    await db.commit()
    logger.info("[app:%s] created RAG '%s' (id=%s)", app_id, collection.name, collection.id)
    return _collection_to_rag_out(collection, app_id)


@router.post("/list_rags", response_model=ListRagsOut)
async def list_app_rags(request: Request, db: DbSession):
    """List RAG collections owned by the calling app."""
    from app.services.rag_service import RagService

    _body, app_id = await _auth(request, db)
    collections = await RagService(db).list_app_collections(app_id)
    return ListRagsOut(rags=[_collection_to_rag_out(c, app_id) for c in collections])


@router.post("/delete_rag", response_model=DeleteRagOut)
async def delete_app_rag(request: Request, db: DbSession):
    """Hard-delete an app-owned RAG collection (Postgres + Qdrant).

    Rejects collections not owned by the calling app.
    Body: ``{"name": "<short_name>"}``.
    """
    from app.services.rag_service import RagService

    body, app_id = await _auth(request, db)
    parsed = json.loads(body) if body else {}
    name = parsed.get("name")
    if not name or not isinstance(name, str):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing 'name'")

    svc = RagService(db)
    collection = await svc.get_app_collection_by_name(app_id, name)
    if not collection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"RAG '{name}' not found for app '{app_id}'.")

    await svc.delete_collection(collection.id)
    await db.commit()
    logger.info("[app:%s] deleted RAG '%s' (id=%s)", app_id, collection.name, collection.id)
    return DeleteRagOut(deleted=True)


async def _resolve_owned_lab_and_rag(
    db, app_id: str, lab_id_str: str, rag_name: str
):
    """Look up a lab + RAG; both must be owned by ``app_id``. Returns tuple."""
    from app.models.orchestrator import Lab
    from app.services.rag_service import RagService

    try:
        lab_uuid = UUID(lab_id_str)
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid lab_id (not a UUID)")

    lab = (await db.execute(select(Lab).where(Lab.id == lab_uuid))).scalars().first()
    if not lab:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lab not found.")

    svc = RagService(db)
    collection = await svc.get_app_collection_by_name(app_id, rag_name)
    if not collection:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"RAG '{rag_name}' not found for app '{app_id}'.",
        )
    return lab, collection


@router.post("/grant_rag_access", response_model=GrantRagAccessOut)
async def grant_rag_access(request: Request, db: DbSession):
    """Grant a lab read/write access to an app-owned RAG collection.

    Both the lab and the RAG must be owned by the calling app. The lab can be
    one this app imported via /import_lab or any lab with no app tag (e.g.
    operator-created and re-tagged); ownership of the RAG is the binding check.
    """
    from app.services.rag_service import RagService

    body, app_id = await _auth(request, db)
    payload = GrantRagAccessIn.model_validate_json(body)

    lab, collection = await _resolve_owned_lab_and_rag(
        db, app_id, payload.lab_id, payload.rag_name,
    )

    svc = RagService(db)
    try:
        entry = await svc.grant_lab_access(
            lab_id=lab.id,
            collection_id=collection.id,
            can_read=payload.can_read,
            can_write=payload.can_write,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    logger.info(
        "[app:%s] granted RAG '%s' to lab '%s' (read=%s write=%s)",
        app_id, collection.name, lab.id, payload.can_read, payload.can_write,
    )
    return GrantRagAccessOut(
        lab_id=str(lab.id),
        collection_id=str(collection.id),
        collection_name=collection.name,
        can_read=entry["can_read"],
        can_write=entry["can_write"],
    )


@router.post("/revoke_rag_access", response_model=RevokeRagAccessOut)
async def revoke_rag_access(request: Request, db: DbSession):
    """Revoke a lab's access to an app-owned RAG collection."""
    from app.services.rag_service import RagService

    body, app_id = await _auth(request, db)
    payload = RevokeRagAccessIn.model_validate_json(body)

    lab, collection = await _resolve_owned_lab_and_rag(
        db, app_id, payload.lab_id, payload.rag_name,
    )

    removed = await RagService(db).revoke_lab_access(lab.id, collection.id)
    logger.info(
        "[app:%s] revoked RAG '%s' from lab '%s' (removed=%s)",
        app_id, collection.name, lab.id, removed,
    )
    return RevokeRagAccessOut(revoked=bool(removed))


# ─────────────────────────────────────────────────────────────────────────────
# Consumer-app RAG document lifecycle
#
# Phase 1 only exposed collection-level CRUD. To keep app-owned KBs healthy
# without operator intervention, an app needs to:
#   * update collection metadata (display name, description) → /update_rag
#   * push fresh content under a stable filename without storage bloat
#     → /ingest_rag_document with replace_if_exists=true (default)
#   * list + delete individual documents to clean stale entries
#     → /list_rag_documents + /delete_rag_document
# ─────────────────────────────────────────────────────────────────────────────


class UpdateRagIn(BaseModel):
    name: str  # short
    display_name: str | None = None
    description: str | None = None
    lightrag_search_mode: str | None = None  # local | global | hybrid


class IngestRagDocumentIn(BaseModel):
    name: str  # short rag name
    filename: str  # source label; used for upsert key when replace_if_exists=true
    content: str  # raw text body
    content_type: str = "text/plain"
    metadata: dict[str, Any] = {}
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    splitter: str | None = None
    replace_if_exists: bool = True


class IngestRagDocumentOut(BaseModel):
    document_id: str
    filename: str
    status: str
    chunk_count: int
    replaced_previous: bool


class ListRagDocumentsIn(BaseModel):
    name: str  # short rag name


class RagDocumentSummary(BaseModel):
    document_id: str
    filename: str
    status: str
    chunk_count: int
    size_bytes: int
    content_type: str
    created_at: str
    ingested_at: str | None = None


class ListRagDocumentsOut(BaseModel):
    documents: list[RagDocumentSummary]


class DeleteRagDocumentIn(BaseModel):
    name: str  # short rag name
    document_id: str | None = None
    filename: str | None = None  # alternative — deletes ALL docs matching this filename


class DeleteRagDocumentOut(BaseModel):
    deleted: int  # number of documents actually removed


@router.post("/update_rag", response_model=RagOut)
async def update_app_rag(request: Request, db: DbSession):
    """Update mutable metadata on an app-owned RAG collection.

    Embedding model + dimension + distance metric are immutable (changing
    them invalidates the existing vector index). Only ``display_name``,
    ``description``, and ``lightrag_search_mode`` (LightRAG-only) can be
    edited via this endpoint. Use ``/delete_rag`` + ``/create_rag`` if you
    need to change the embedding config.
    """
    from app.schemas.rag import RagCollectionUpdate
    from app.services.rag_service import RagService

    body, app_id = await _auth(request, db)
    payload = UpdateRagIn.model_validate_json(body)

    svc = RagService(db)
    collection = await svc.get_app_collection_by_name(app_id, payload.name)
    if not collection:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"RAG '{payload.name}' not found for app '{app_id}'.",
        )

    updates_raw: dict[str, Any] = {}
    if payload.display_name is not None:
        updates_raw["display_name"] = payload.display_name
    if payload.description is not None:
        updates_raw["description"] = payload.description
    if payload.lightrag_search_mode is not None:
        if collection.rag_mode != "lightrag":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "lightrag_search_mode is only valid on LightRAG collections.",
            )
        updates_raw["lightrag_search_mode"] = payload.lightrag_search_mode

    if not updates_raw:
        return _collection_to_rag_out(collection, app_id)

    try:
        update_obj = RagCollectionUpdate(**updates_raw)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    updated = await svc.update_collection(collection.id, update_obj)
    await db.commit()
    logger.info("[app:%s] updated RAG '%s' (id=%s)", app_id, updated.name, updated.id)
    return _collection_to_rag_out(updated, app_id)


@router.post("/list_rag_documents", response_model=ListRagDocumentsOut)
async def list_app_rag_documents(request: Request, db: DbSession):
    """List documents in an app-owned RAG collection."""
    from app.services.rag_service import RagService

    body, app_id = await _auth(request, db)
    payload = ListRagDocumentsIn.model_validate_json(body)

    svc = RagService(db)
    collection = await svc.get_app_collection_by_name(app_id, payload.name)
    if not collection:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"RAG '{payload.name}' not found for app '{app_id}'.",
        )

    documents = await svc.list_documents(collection.id)
    return ListRagDocumentsOut(documents=[
        RagDocumentSummary(
            document_id=str(d.id),
            filename=d.filename,
            status=d.status,
            chunk_count=d.chunk_count or 0,
            size_bytes=d.size_bytes or 0,
            content_type=d.content_type or "",
            created_at=d.created_at.isoformat() if d.created_at else "",
            ingested_at=d.ingested_at.isoformat() if d.ingested_at else None,
        )
        for d in documents
    ])


@router.post("/ingest_rag_document", response_model=IngestRagDocumentOut, status_code=status.HTTP_201_CREATED)
async def ingest_app_rag_document(request: Request, db: DbSession):
    """Ingest a text document into an app-owned RAG collection.

    By default (``replace_if_exists=true``), any existing document with the
    same ``filename`` in this collection is deleted first — fixes the
    storage-bloats-on-reingest gotcha where multiple versions otherwise
    cohabit and search top-K becomes the only working filter.

    For binary uploads (PDFs, etc.), use the operator-UI document upload
    endpoint. This route is text-only by design — it sees use mostly for
    refreshing structured KBs (extracted page text, JSON-derived prose).
    """
    from app.services.rag_service import RagService

    body, app_id = await _auth(request, db)
    payload = IngestRagDocumentIn.model_validate_json(body)

    if not payload.filename or "/" in payload.filename or "\\" in payload.filename:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "filename must be a flat name (no path separators).",
        )

    svc = RagService(db)
    collection = await svc.get_app_collection_by_name(app_id, payload.name)
    if not collection:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"RAG '{payload.name}' not found for app '{app_id}'.",
        )

    # Pre-count matches so we can report whether we replaced anything.
    existing = [
        d for d in await svc.list_documents(collection.id)
        if d.filename == payload.filename
    ]
    replaced = bool(existing) and payload.replace_if_exists

    try:
        document = await svc.ingest_text(
            collection_id=collection.id,
            filename=payload.filename,
            content=payload.content,
            content_type=payload.content_type,
            metadata=payload.metadata,
            chunk_size=payload.chunk_size,
            chunk_overlap=payload.chunk_overlap,
            splitter=payload.splitter,
            replace_if_exists=payload.replace_if_exists,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    logger.info(
        "[app:%s] ingested doc '%s' into RAG '%s' (status=%s replaced=%s)",
        app_id, payload.filename, collection.name, document.status, replaced,
    )
    return IngestRagDocumentOut(
        document_id=str(document.id),
        filename=document.filename,
        status=document.status,
        chunk_count=document.chunk_count or 0,
        replaced_previous=replaced,
    )


@router.post("/delete_rag_document", response_model=DeleteRagDocumentOut)
async def delete_app_rag_document(request: Request, db: DbSession):
    """Delete a specific document from an app-owned RAG collection.

    Either ``document_id`` or ``filename`` may be specified. When ``filename``
    is given, every document in the collection with that filename is
    removed (useful for cleaning up duplicate versions accumulated before
    ``replace_if_exists`` was wired in).
    """
    from app.services.rag_service import RagService

    body, app_id = await _auth(request, db)
    payload = DeleteRagDocumentIn.model_validate_json(body)

    if not payload.document_id and not payload.filename:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Specify either document_id or filename.",
        )

    svc = RagService(db)
    collection = await svc.get_app_collection_by_name(app_id, payload.name)
    if not collection:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"RAG '{payload.name}' not found for app '{app_id}'.",
        )

    deleted = 0
    if payload.document_id:
        try:
            doc_uuid = UUID(payload.document_id)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "document_id is not a UUID")
        if await svc.delete_document(collection.id, doc_uuid):
            deleted += 1
    else:
        documents = await svc.list_documents(collection.id)
        targets = [d for d in documents if d.filename == payload.filename]
        for d in targets:
            if await svc.delete_document(collection.id, d.id):
                deleted += 1

    if deleted == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No matching document(s) found.")
    logger.info(
        "[app:%s] deleted %d doc(s) from RAG '%s' (key=%s)",
        app_id, deleted, collection.name,
        payload.document_id or payload.filename,
    )
    return DeleteRagDocumentOut(deleted=deleted)


# ─────────────────────────────────────────────────────────────────────────────
# Consumer-app standalone agents
#
# A consumer app can register a ``LibraryAgent`` under its own namespace
# (``app__<app_id>__<name>``), then invoke it via ``/run_agent`` (async with
# callback, mirrors ``/run_lab``) or have it fired on cron (the scheduler
# spawns ephemeral labs tagged ``app:<app_id>:agent_run:<short>:cron:<ts>``
# and the app polls them via ``/list_agent_runs``).
#
# Cross-app isolation is enforced via the ``app__<app_id>__`` name prefix,
# which is unique by virtue of ``library_agents.name`` being UNIQUE.
# ─────────────────────────────────────────────────────────────────────────────


AGENT_RUN_TIMEOUT_SEC = int(os.environ.get("APP_AGENT_RUN_TIMEOUT_SEC", "600"))


class CreateAgentIn(BaseModel):
    name: str  # short name; namespaced as app__<app_id>__<name>
    role: str = ""
    system_prompt: str = ""
    description: str = ""
    model: str  # model_identifier (e.g. "qwen3.6:35b")
    temperature: float = 0.7
    max_tokens: int = 4096
    tools: list[str] = []
    tool_sets: list[str] = []  # tool_set names; resolved to ids at create time
    share_memory: bool = False
    callable_agents: list[str] = []
    cron_expression: str | None = None
    cron_instruction: str = ""
    anti_loop_enabled: bool = False


class AgentOut(BaseModel):
    agent_id: str
    name: str  # short (un-namespaced)
    library_agent_name: str  # full namespaced
    role: str
    system_prompt: str
    model: str | None
    temperature: float
    max_tokens: int
    tools: list[str]
    tool_sets: list[str]
    cron_expression: str | None
    cron_instruction: str
    share_memory: bool
    anti_loop_enabled: bool


class ListAgentsOut(BaseModel):
    agents: list[AgentOut]


class ImportAgentIn(BaseModel):
    blueprint: dict
    name_override: str | None = None
    force_refresh: bool = False


class DeleteAgentIn(BaseModel):
    name: str


class DeleteAgentOut(BaseModel):
    deleted: bool


class RunAgentIn(BaseModel):
    name: str  # short
    generation_id: str
    callback_url: str
    user_message: str
    context_files: list[ContextFileIn] = []


class RunAgentOut(BaseModel):
    lab_id: str
    status: str = "started"


class ListAgentRunsIn(BaseModel):
    name: str  # short; if empty, lists across all agents for this app
    limit: int = 20


class AgentRunSummary(BaseModel):
    lab_id: str
    agent_name: str  # short name
    triggered_by: str  # "run_agent" | "cron"
    generation_id: str | None = None  # set for /run_agent triggers
    cron_tick: str | None = None  # ISO ts of the cron firing
    status: str
    final_output: str | None = None  # last assistant content, truncated to 4000 chars
    created_at: str
    completed_at: str | None = None


class ListAgentRunsOut(BaseModel):
    runs: list[AgentRunSummary]


def _make_app_agent_run_tag(app_id: str, short_name: str, generation_id: str) -> str:
    return f"app:{app_id}:agent_run:{short_name}:{generation_id}"


def _make_app_agent_cron_tag(app_id: str, short_name: str, tick_iso: str) -> str:
    return f"app:{app_id}:agent_run:{short_name}:cron:{tick_iso}"


def _make_app_agent_run_tag_prefix(app_id: str, short_name: str | None = None) -> str:
    if short_name:
        return f"app:{app_id}:agent_run:{short_name}:"
    return f"app:{app_id}:agent_run:"


async def _resolve_tool_set_ids(db, tool_set_names: list[str]) -> list[str]:
    """Resolve tool_set names → ids (UUID strings). Unknown names are dropped."""
    if not tool_set_names:
        return []
    from app.repositories.lab_repo import ToolSetRepository

    repo = ToolSetRepository(db)
    all_ts = await repo.get_all()
    name_to_id = {ts.name: str(ts.id) for ts in all_ts}
    return [name_to_id[n] for n in tool_set_names if n in name_to_id]


async def _resolve_model_id(db, model_identifier: str | None):
    if not model_identifier:
        return None
    from app.repositories.orchestrator_repo import AIModelRepository

    for m in await AIModelRepository(db).get_all():
        if m.model_identifier == model_identifier:
            return m.id
    return None


def _agent_to_out(agent, app_id: str, model_identifier: str | None = None) -> AgentOut:
    """Project a LibraryAgent row to the HMAC AgentOut shape, stripping the namespace."""
    from app.services.library_agent_service import short_name_for_app

    short = short_name_for_app(agent.name, app_id) or agent.name
    return AgentOut(
        agent_id=str(agent.id),
        name=short,
        library_agent_name=agent.name,
        role=agent.role or "",
        system_prompt=agent.system_prompt or "",
        model=model_identifier,
        temperature=float(agent.temperature or 0.7),
        max_tokens=int(agent.max_tokens or 4096),
        tools=list(agent.tools or []),
        tool_sets=[],  # tool_sets list (names) is recomputed on read if needed
        cron_expression=agent.cron_expression,
        cron_instruction=agent.cron_instruction or "",
        share_memory=bool(agent.share_memory),
        anti_loop_enabled=bool(agent.anti_loop_enabled),
    )


async def _hydrate_agent_out(db, agent, app_id: str) -> AgentOut:
    """Like ``_agent_to_out`` but resolves model_id → model_identifier."""
    model_identifier = None
    if agent.model_id:
        from app.repositories.orchestrator_repo import AIModelRepository

        m = await AIModelRepository(db).get_by_id(agent.model_id)
        if m:
            model_identifier = m.model_identifier
    return _agent_to_out(agent, app_id, model_identifier)


@router.post("/create_agent", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_app_agent(request: Request, db: DbSession):
    """Create a consumer-app-owned library agent.

    The agent is namespaced as ``app__<app_id>__<name>`` so the operator UI
    can filter it out by default and cross-app collisions raise. Idempotent
    on ``(app_id, name)`` — a second call with the same args returns the
    existing agent.
    """
    from app.repositories.lab_repo import LibraryAgentRepository
    from app.services.library_agent_service import (
        get_app_owned_agent_by_short_name,
        make_app_agent_name,
    )

    body, app_id = await _auth(request, db)
    payload = CreateAgentIn.model_validate_json(body)

    name_ok = bool(payload.name) and all(
        c.isalnum() or c in "_-" for c in payload.name
    )
    if not name_ok:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "name may only contain letters, numbers, underscores, and hyphens.",
        )

    existing = await get_app_owned_agent_by_short_name(db, app_id, payload.name)
    if existing:
        return await _hydrate_agent_out(db, existing, app_id)

    model_id = await _resolve_model_id(db, payload.model)
    if payload.model and not model_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown model '{payload.model}'. Call /list_models for the available catalog.",
        )

    tool_set_ids = await _resolve_tool_set_ids(db, payload.tool_sets)
    full_name = make_app_agent_name(app_id, payload.name)

    repo = LibraryAgentRepository(db)
    agent = await repo.create(
        name=full_name,
        role=payload.role,
        system_prompt=payload.system_prompt,
        model_id=model_id,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        tools=list(payload.tools or []),
        tool_set_ids=tool_set_ids,
        share_memory=payload.share_memory,
        callable_agents=list(payload.callable_agents or []),
        cron_expression=payload.cron_expression,
        cron_instruction=payload.cron_instruction,
        anti_loop_enabled=payload.anti_loop_enabled,
    )
    await db.commit()
    logger.info("[app:%s] created agent '%s' (id=%s)", app_id, full_name, agent.id)
    return await _hydrate_agent_out(db, agent, app_id)


@router.post("/list_agents", response_model=ListAgentsOut)
async def list_app_agents(request: Request, db: DbSession):
    """List agents owned by the calling app."""
    from app.services.library_agent_service import list_app_owned_agents

    _body, app_id = await _auth(request, db)
    rows = await list_app_owned_agents(db, app_id)
    out = [await _hydrate_agent_out(db, a, app_id) for a in rows]
    return ListAgentsOut(agents=out)


@router.post("/import_agent", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def import_app_agent(request: Request, db: DbSession):
    """Import an ``AgentBlueprint`` and create a namespaced consumer-app agent.

    Body: ``{"blueprint": {...}, "name_override": "...", "force_refresh": false}``.
    Idempotent by short name unless ``force_refresh=true`` (deletes the
    existing agent first). The blueprint's ``rag_access`` is validated for
    app ownership and persisted as part of the ephemeral lab when the agent
    is invoked (we record it in the agent's ``callable_agents`` JSONB under
    a sentinel key — see ``_load_app_agent_rag_access``).
    """
    from app.repositories.lab_repo import LibraryAgentRepository
    from app.schemas.orchestrator import AgentBlueprint
    from app.services.library_agent_service import (
        get_app_owned_agent_by_short_name,
        make_app_agent_name,
    )

    body, app_id = await _auth(request, db)
    payload = ImportAgentIn.model_validate_json(body)

    blueprint_dict = dict(payload.blueprint)
    if payload.name_override:
        bp_agent = dict(blueprint_dict.get("agent", {}))
        bp_agent["name"] = payload.name_override
        blueprint_dict["agent"] = bp_agent

    short_name = blueprint_dict.get("agent", {}).get("name")
    if not short_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Blueprint missing agent.name")

    name_ok = all(c.isalnum() or c in "_-" for c in short_name)
    if not name_ok:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "agent.name may only contain letters, numbers, underscores, and hyphens.",
        )

    existing = await get_app_owned_agent_by_short_name(db, app_id, short_name)
    if existing and not payload.force_refresh:
        logger.info("[app:%s] import_agent reusing '%s' (id=%s)", app_id, short_name, existing.id)
        return await _hydrate_agent_out(db, existing, app_id)
    if existing and payload.force_refresh:
        await LibraryAgentRepository(db).delete(existing.id)
        await db.flush()

    try:
        bp = AgentBlueprint.model_validate(blueprint_dict)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid blueprint: {exc}")

    # Validate rag_access ownership before persisting anything.
    if bp.agent.rag_access:
        from app.services.rag_service import RagService

        svc = RagService(db)
        for ref in bp.agent.rag_access:
            try:
                await svc.assert_owned_by_app(ref.collection_name, app_id)
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    f"{exc} Create your own copy via /create_rag first.",
                )

    model_id = await _resolve_model_id(db, bp.agent.model)
    if bp.agent.model and not model_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown model '{bp.agent.model}'. Call /list_models.",
        )

    tool_set_ids = await _resolve_tool_set_ids(db, bp.agent.tool_sets)
    full_name = make_app_agent_name(app_id, short_name)

    # Stash rag_access in callable_agents JSONB under a sentinel pseudo-entry
    # because library_agents has no acl/JSONB extension column. The runtime
    # strips this entry before resolving real callable_agents.
    callable_agents = list(bp.agent.callable_agents or [])
    if bp.agent.rag_access:
        callable_agents.append({
            "__app_meta__": {
                "rag_access": [r.model_dump() for r in bp.agent.rag_access],
            },
        })

    repo = LibraryAgentRepository(db)
    agent = await repo.create(
        name=full_name,
        role=bp.agent.role,
        system_prompt=bp.agent.system_prompt,
        model_id=model_id,
        temperature=bp.agent.temperature,
        max_tokens=bp.agent.max_tokens,
        tools=list(bp.agent.tools or []),
        tool_set_ids=tool_set_ids,
        share_memory=bp.agent.share_memory,
        callable_agents=callable_agents,
        cron_expression=bp.agent.cron_expression,
        cron_instruction=bp.agent.cron_instruction,
        anti_loop_enabled=bp.agent.anti_loop_enabled,
    )
    await db.commit()
    logger.info("[app:%s] imported agent '%s' (id=%s)", app_id, full_name, agent.id)
    return await _hydrate_agent_out(db, agent, app_id)


def _load_app_agent_rag_access(agent) -> list:
    """Pull the ``rag_access`` list stashed in ``callable_agents`` by import_agent."""
    from app.schemas.orchestrator import RagAccessRef

    for entry in (agent.callable_agents or []):
        if isinstance(entry, dict) and "__app_meta__" in entry:
            raw = entry["__app_meta__"].get("rag_access") or []
            return [RagAccessRef(**r) for r in raw]
    return []


def _strip_app_meta_callables(callable_agents: list) -> list:
    """Return ``callable_agents`` with the ``__app_meta__`` sentinel filtered out."""
    return [
        e for e in (callable_agents or [])
        if not (isinstance(e, dict) and "__app_meta__" in e)
    ]


@router.post("/delete_agent", response_model=DeleteAgentOut)
async def delete_app_agent(request: Request, db: DbSession):
    """Hard-delete an app-owned agent. Rejects agents not owned by the calling app."""
    from app.repositories.lab_repo import LibraryAgentRepository
    from app.services.library_agent_service import get_app_owned_agent_by_short_name

    body, app_id = await _auth(request, db)
    payload = DeleteAgentIn.model_validate_json(body)

    agent = await get_app_owned_agent_by_short_name(db, app_id, payload.name)
    if not agent:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Agent '{payload.name}' not found for app '{app_id}'.",
        )

    await LibraryAgentRepository(db).delete(agent.id)
    await db.commit()
    logger.info("[app:%s] deleted agent '%s' (id=%s)", app_id, agent.name, agent.id)
    return DeleteAgentOut(deleted=True)


@router.post("/run_agent", response_model=RunAgentOut)
async def run_app_agent(request: Request, db: DbSession):
    """Spawn an ephemeral single-agent lab from an app-owned library agent.

    Flow:
      1. HMAC auth + payload validation.
      2. Look up the agent by short name (ownership-checked).
      3. Instantiate the agent as a single-agent lab tagged
         ``app:<app_id>:agent_run:<short>:<gid>``. Materialize any
         ``rag_access`` entries that were attached at import time.
      4. Inject ``user_message`` as a user-inject LabMessage so the runner
         picks it up on first iteration.
      5. Spawn ``_drive_app_agent`` as a background task: run, capture the
         final agent message, deliver a signed callback to ``callback_url``.
    """
    from app.services.library_agent_service import (
        create_agent_instance,
        get_app_owned_agent_by_short_name,
    )

    body, app_id = await _auth(request, db)
    payload = RunAgentIn.model_validate_json(body)

    try:
        generation_uuid = UUID(payload.generation_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "generation_id is not a UUID")

    for cf in payload.context_files:
        _safe_relpath(cf.path)

    agent = await get_app_owned_agent_by_short_name(db, app_id, payload.name)
    if not agent:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Agent '{payload.name}' not found for app '{app_id}'.",
        )

    rag_access = _load_app_agent_rag_access(agent)
    gen_slug = str(generation_uuid)[:8]
    instance_name = f"app:{app_id}:agent:{payload.name}:{gen_slug}"
    acl = {
        "owner": f"app:{app_id}",
        "editors": [],
        "viewers": [],
        "tag": _make_app_agent_run_tag(app_id, payload.name, str(generation_uuid)),
        "library_agent_id": str(agent.id),
        "app_id": app_id,
        "short_name": payload.name,
        "generation_id": str(generation_uuid),
        "triggered_by": "run_agent",
    }

    try:
        lab = await create_agent_instance(
            db,
            library_agent_id=agent.id,
            instance_name=instance_name,
            acl=acl,
            rag_access=rag_access,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    # Patch the cloned LabAgent so the runtime sees the real callable_agents
    # without the __app_meta__ sentinel.
    from app.models.orchestrator import LabAgent
    from app.repositories.lab_repo import LabAgentRepository

    rows = (
        await db.execute(select(LabAgent).where(LabAgent.lab_id == lab.id))
    ).scalars().all()
    if rows:
        await LabAgentRepository(db).update(
            rows[0].id,
            callable_agents=_strip_app_meta_callables(rows[0].callable_agents),
        )

    # Merge context_files into the lab JSONB + write to workspace.
    if payload.context_files:
        merged = [{"name": cf.path, "content": cf.content} for cf in payload.context_files]
        from app.repositories.lab_repo import LabRepository as _LR

        await _LR(db).update(lab.id, context_files=merged)

    # Inject the user message so the runner picks it up.
    from app.repositories.lab_repo import LabMessageRepository

    await LabMessageRepository(db).create(
        lab_id=lab.id,
        iteration=0,
        sender_type="user",
        content=payload.user_message,
        message_type="user_inject",
    )
    await db.commit()

    # Write context files to the sandboxed workspace too (agents can file_read them).
    lab_dir = LAB_RESOURCES_ROOT / str(lab.id)
    lab_dir.mkdir(parents=True, exist_ok=True)
    for cf in payload.context_files:
        target = lab_dir / _safe_relpath(cf.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(cf.content)

    task = asyncio.create_task(
        _drive_app_agent(
            app_id=app_id,
            lab_id=lab.id,
            short_name=payload.name,
            generation_id=str(generation_uuid),
            callback_url=payload.callback_url,
        )
    )

    def _surface(t: asyncio.Task) -> None:
        if t.cancelled():
            logger.warning("[app-agent %s] task cancelled", generation_uuid)
            return
        exc = t.exception()
        if exc is not None:
            logger.error("[app-agent %s] task crashed: %r", generation_uuid, exc, exc_info=exc)

    task.add_done_callback(_surface)
    logger.info("[app:%s] run_agent dispatched lab=%s agent=%s", app_id, lab.id, payload.name)
    return RunAgentOut(lab_id=str(lab.id), status="started")


async def _drive_app_agent(
    *,
    app_id: str,
    lab_id: UUID,
    short_name: str,
    generation_id: str,
    callback_url: str,
) -> None:
    """Run a single-agent ephemeral lab to completion + deliver callback.

    The callback body shape is intentionally richer than ``/run_lab``: the
    expected output of an agent is structured (final assistant text + tool
    calls) rather than an artifact file, so we return it inline.
    """
    from app.database import async_session
    from app.models.orchestrator import LabMessage
    from app.repositories.lab_repo import LabRepository
    from app.services.container_manager import ensure_sandbox
    from app.services.lab_runner import LabRunner
    from sqlalchemy import desc

    final_status = "failed"
    error_msg: str | None = None
    output: dict[str, Any] | None = None

    try:
        async with async_session() as db:
            lab = await LabRepository(db).get_by_id(lab_id)
            if not lab:
                raise RuntimeError("Agent lab disappeared before run")
            if not lab.orchestrator_model_id:
                raise RuntimeError("Agent has no model configured")

        await ensure_sandbox(lab_id)

        runner = LabRunner(lab_id, async_session)
        try:
            await asyncio.wait_for(runner.run(), timeout=AGENT_RUN_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            logger.warning(
                "[app-agent %s] timed out after %ds; stopping",
                generation_id, AGENT_RUN_TIMEOUT_SEC,
            )
            await runner.stop()
            raise RuntimeError(f"Agent run exceeded {AGENT_RUN_TIMEOUT_SEC}s timeout")

        async with async_session() as db:
            lab = await LabRepository(db).get_by_id(lab_id)
            lab_status = lab.status if lab else "unknown"
            failure_reason = getattr(lab, "failure_reason", None) if lab else None

            # Pull the most recent assistant/agent message — that's the
            # agent's final output for the callback.
            rows = (
                await db.execute(
                    select(LabMessage)
                    .where(LabMessage.lab_id == lab_id)
                    .order_by(desc(LabMessage.created_at))
                    .limit(20)
                )
            ).scalars().all()

        if lab_status == "failed":
            raise RuntimeError(failure_reason or "Agent run failed")
        if lab_status not in ("completed", "stopped"):
            raise RuntimeError(f"Agent run ended in unexpected status: {lab_status}")

        # Find the last assistant message with substantive content.
        final_msg: LabMessage | None = None
        for m in rows:
            sender = (m.sender_type or "").lower()
            if sender in ("assistant", "agent", "orchestrator") and (m.content or "").strip():
                final_msg = m
                break

        if final_msg is None:
            output = {
                "content": "",
                "tool_calls": [],
                "tokens_in": 0,
                "tokens_out": 0,
                "model": None,
                "provider": None,
            }
        else:
            tool_calls = []
            if final_msg.tool_name and final_msg.tool_input is not None:
                tool_calls.append({
                    "name": final_msg.tool_name,
                    "arguments": final_msg.tool_input,
                })
            output = {
                "content": final_msg.content,
                "tool_calls": tool_calls,
                "tokens_in": final_msg.tokens_in or 0,
                "tokens_out": final_msg.tokens_out or 0,
                "duration_ms": final_msg.duration_ms or 0,
                "model": final_msg.model_used,
                "provider": final_msg.provider_used,
            }
        final_status = "completed"
        logger.info(
            "[app-agent %s] DONE lab=%s content_len=%d",
            generation_id, lab_id, len(output.get("content") or ""),
        )
    except Exception as exc:
        logger.exception("[app-agent %s] failed", generation_id)
        error_msg = str(exc)[:500]

    cb_payload: dict[str, Any] = {
        "generation_id": generation_id,
        "agent_name": short_name,
        "status": final_status,
    }
    if output:
        cb_payload["output"] = output
    if error_msg:
        cb_payload["error"] = error_msg

    await _send_callback(
        app_id=app_id,
        callback_url=callback_url,
        payload=cb_payload,
        log_prefix=f"[app-agent {generation_id}]",
    )


@router.post("/list_agent_runs", response_model=ListAgentRunsOut)
async def list_app_agent_runs(request: Request, db: DbSession):
    """List recent ephemeral-lab runs of an app-owned agent.

    Returns the most-recent ``limit`` agent runs (HMAC-triggered or cron),
    along with the agent's final output for each. Pass ``name=""`` to list
    across every agent owned by this app.
    """
    from app.models.orchestrator import Lab, LabMessage
    from sqlalchemy import desc

    body, app_id = await _auth(request, db)
    payload = ListAgentRunsIn.model_validate_json(body) if body else ListAgentRunsIn(name="")
    prefix = _make_app_agent_run_tag_prefix(app_id, payload.name or None)

    # JSONB tag query: filter labs whose acl->>'tag' starts with prefix.
    from sqlalchemy import text as sql_text

    stmt = (
        select(Lab)
        .where(sql_text("acl->>'tag' LIKE :p"))
        .params(p=f"{prefix}%")
        .order_by(desc(Lab.created_at))
        .limit(max(1, min(payload.limit, 100)))
    )
    labs = (await db.execute(stmt)).scalars().all()

    runs: list[AgentRunSummary] = []
    for lab in labs:
        acl = lab.acl if isinstance(lab.acl, dict) else {}
        triggered_by = acl.get("triggered_by") or (
            "cron" if ":cron:" in (acl.get("tag") or "") else "run_agent"
        )
        # Pull the agent's last substantive message for the summary.
        rows = (
            await db.execute(
                select(LabMessage)
                .where(LabMessage.lab_id == lab.id)
                .order_by(desc(LabMessage.created_at))
                .limit(15)
            )
        ).scalars().all()
        final_output: str | None = None
        for m in rows:
            sender = (m.sender_type or "").lower()
            if sender in ("assistant", "agent", "orchestrator") and (m.content or "").strip():
                final_output = (m.content or "")[:4000]
                break

        runs.append(AgentRunSummary(
            lab_id=str(lab.id),
            agent_name=acl.get("short_name") or "",
            triggered_by=triggered_by,
            generation_id=acl.get("generation_id"),
            cron_tick=acl.get("cron_tick"),
            status=lab.status,
            final_output=final_output,
            created_at=lab.created_at.isoformat() if lab.created_at else "",
            completed_at=lab.completed_at.isoformat() if lab.completed_at else None,
        ))

    return ListAgentRunsOut(runs=runs)


# ─────────────────────────────────────────────────────────────────────────────
# Direct ComfyUI dispatch (legacy)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/run", response_model=RunOut)
async def run_comfyui_dispatch(
    request: Request,
    db: DbSession,
):
    body, app_id = await _auth(request, db)
    payload = RunIn.model_validate_json(body)

    generation_id = UUID(payload.generation_id)
    wall_path = Path(payload.inputs.get("wall_path", ""))
    texture_path = Path(payload.inputs.get("texture_path", ""))
    workflow_json = payload.inputs.get("workflow_json")
    if workflow_json is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing workflow_json")
    if isinstance(workflow_json, str):
        try:
            workflow_json = json.loads(workflow_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"workflow_json not JSON: {exc}")

    for p in (wall_path, texture_path):
        if not _is_subpath(p, APP_UPLOADS_ROOT):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Path out of scope: {p}")
        if not p.is_file():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Input file missing: {p.name}")

    provider = await _pick_healthy_comfyui_provider(db)
    base_url = provider.base_url.rstrip("/")

    task = asyncio.create_task(
        _run_comfyui(
            app_id=app_id,
            generation_id=generation_id,
            wall_path=wall_path,
            texture_path=texture_path,
            workflow_json=workflow_json,
            base_url=base_url,
            callback_url=payload.callback_url,
        )
    )

    def _surface(t: asyncio.Task) -> None:
        if t.cancelled():
            logger.warning("[app%s] task cancelled", generation_id)
            return
        exc = t.exception()
        if exc is not None:
            logger.error("[app%s] task crashed: %r", generation_id, exc, exc_info=exc)

    task.add_done_callback(_surface)
    logger.info("[app%s] DIRECT dispatch base=%s callback=%s", generation_id, base_url, payload.callback_url)
    return RunOut(lab_id=str(generation_id), status="started")


async def _run_comfyui(
    *,
    app_id: str,
    generation_id: UUID,
    wall_path: Path,
    texture_path: Path,
    workflow_json: dict,
    base_url: str,
    callback_url: str,
) -> None:
    final_status = "failed"
    output_path: str | None = None
    error_msg: str | None = None
    try:
        logger.info("[app%s] uploading inputs to %s", generation_id, base_url)
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            wall_name = await _upload_image(
                client,
                base_url,
                wall_path,
                remote_name=f"{generation_id}_wall{wall_path.suffix.lower() or '.png'}",
            )
            tex_name = await _upload_image(
                client,
                base_url,
                texture_path,
                remote_name=f"{generation_id}_texture{texture_path.suffix.lower() or '.png'}",
            )
        logger.info("[app%s] uploaded wall=%s tex=%s", generation_id, wall_name, tex_name)

        wf = json.loads(json.dumps(workflow_json))
        try:
            wf["41"]["inputs"]["image"] = wall_name
            wf["83"]["inputs"]["image"] = tex_name
        except KeyError as exc:
            raise RuntimeError(f"Workflow missing expected node {exc}")
        if "170:169" in wf and "inputs" in wf["170:169"]:
            wf["170:169"]["inputs"]["seed"] = random.randint(1, 2**31 - 1)

        prompt_id = await _queue_workflow(base_url, wf)
        logger.info("[app%s] queued prompt_id=%s", generation_id, prompt_id)
        history = await _wait_for_history(base_url, prompt_id, COMFYUI_TIMEOUT_SEC)
        logger.info("[app%s] history status=%s", generation_id, history.get("status", {}).get("status_str"))

        status_info = history.get("status", {})
        if status_info.get("status_str") == "error":
            messages = status_info.get("messages", [])
            err_msgs = [m for m in messages if m and m[0] == "execution_error"]
            detail = json.dumps(err_msgs[0][1]) if err_msgs and len(err_msgs[0]) > 1 else str(messages)
            raise RuntimeError(f"ComfyUI execution error: {detail[:400]}")

        outputs = history.get("outputs", {})
        first = None
        for _node_id, node_out in outputs.items():
            for key in ("images", "gifs"):
                for item in node_out.get(key, []):
                    if item.get("filename"):
                        first = item
                        break
                if first:
                    break
            if first:
                break
        if not first:
            raise RuntimeError("ComfyUI returned no output image")

        params = {"filename": first["filename"], "type": first.get("type", "output")}
        if first.get("subfolder"):
            params["subfolder"] = first["subfolder"]
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            dl = await client.get(f"{base_url}/view", params=params)
            dl.raise_for_status()
            data = dl.content

        out_dir = _app_upload_dir(app_id, generation_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        result_path = out_dir / "result.png"
        result_path.write_bytes(data)
        output_path = str(result_path)
        final_status = "completed"
        logger.info("[app%s] DONE -> %s (%d bytes)", generation_id, output_path, len(data))
    except Exception as exc:
        logger.exception("[app%s] direct ComfyUI run failed", generation_id)
        error_msg = str(exc)[:500]

    cb_payload: dict[str, Any] = {"generation_id": str(generation_id), "status": final_status}
    if output_path:
        cb_payload["output_path"] = output_path
    if error_msg:
        cb_payload["error"] = error_msg

    await _send_callback(
        app_id=app_id,
        callback_url=callback_url,
        payload=cb_payload,
        log_prefix=f"[app {generation_id}]",
    )


async def _upload_image(
    client: httpx.AsyncClient,
    base_url: str,
    path: Path,
    *,
    remote_name: str,
) -> str:
    file_bytes = path.read_bytes()
    resp = await client.post(
        f"{base_url}/upload/image",
        files={"image": (os.path.basename(remote_name), file_bytes, "image/png")},
        data={"type": "input", "overwrite": "true"},
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"ComfyUI upload failed ({resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    return data.get("name") or os.path.basename(remote_name)


async def _queue_workflow(base_url: str, workflow: dict) -> str:
    client_id = uuid_mod.uuid4().hex
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.post(
            f"{base_url}/prompt",
            json={"prompt": workflow, "client_id": client_id},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"ComfyUI queue rejected ({resp.status_code}): {resp.text[:400]}")
    data = resp.json()
    if "error" in data:
        node_errors = data.get("node_errors", {})
        raise RuntimeError(f"ComfyUI workflow validation error: {json.dumps(node_errors)[:400] or data['error']}")
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return prompt_id: {data}")
    return prompt_id


async def _wait_for_history(base_url: str, prompt_id: str, timeout_sec: int) -> dict:
    deadline = time.monotonic() + max(timeout_sec, COMFYUI_MAX_WAIT_SEC)
    running_deadline: float | None = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        while time.monotonic() < deadline:
            await asyncio.sleep(2)
            queue_state: str | None = None
            try:
                history = await _get_history_entry(client, base_url, prompt_id)
                if history is not None:
                    return history

                queue_state = await _get_queue_state(client, base_url, prompt_id)
            except (httpx.HTTPError, ValueError):
                pass

            now = time.monotonic()
            if queue_state == "running":
                if running_deadline is None:
                    running_deadline = now + timeout_sec
                if now > running_deadline:
                    raise RuntimeError(f"ComfyUI workflow exceeded running timeout after {timeout_sec}s")
                continue

            if queue_state == "pending":
                running_deadline = None
                continue

            if running_deadline is not None and now <= running_deadline:
                continue
    raise RuntimeError(
        f"ComfyUI workflow timed out after waiting {max(timeout_sec, COMFYUI_MAX_WAIT_SEC)}s"
    )


async def _get_history_entry(
    client: httpx.AsyncClient,
    base_url: str,
    prompt_id: str,
) -> dict | None:
    resp = await client.get(f"{base_url}/history/{prompt_id}")
    if resp.status_code != 200:
        return None
    data = resp.json()
    return data.get(prompt_id)


async def _get_queue_state(
    client: httpx.AsyncClient,
    base_url: str,
    prompt_id: str,
) -> str | None:
    resp = await client.get(f"{base_url}/queue")
    if resp.status_code != 200:
        return None
    data = resp.json()
    for queue_key, state in (("queue_running", "running"), ("queue_pending", "pending")):
        for item in data.get(queue_key, []):
            if _queue_item_prompt_id(item) == prompt_id:
                return state
    return None


def _queue_item_prompt_id(item: Any) -> str | None:
    if isinstance(item, list) and len(item) > 1 and isinstance(item[1], str):
        return item[1]
    if isinstance(item, dict):
        prompt_id = item.get("prompt_id")
        if isinstance(prompt_id, str):
            return prompt_id
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Lab-driven consumer-app runner (generic)
# ─────────────────────────────────────────────────────────────────────────────


class RunFluxText2ImgIn(BaseModel):
    """Direct ComfyUI Flux.1-Dev text-to-image driver, no agent involved."""
    generation_id: str  # ID used purely for logging / callback bookkeeping
    prompt: str
    workflow_json: dict[str, Any]
    output_path: str  # absolute path inside APP_UPLOADS_ROOT to write the PNG to
    callback_url: str


@router.post("/run_flux_text2img", response_model=RunOut)
async def run_flux_text2img(
    request: Request,
    db: DbSession,
):
    """Direct ComfyUI Flux.1-Dev text-to-image driver.

    Bypasses the agent: consumer-app passes a ready prompt + workflow template,
    we modify the prompt + seed nodes, queue the workflow, wait for output,
    write the PNG to ``output_path`` and POST a signed callback.
    """
    body, app_id = await _auth(request, db)
    payload = RunFluxText2ImgIn.model_validate_json(body)

    out_path = Path(payload.output_path)
    if not _is_subpath(out_path, APP_UPLOADS_ROOT):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "output_path out of scope")

    provider = await _pick_healthy_comfyui_provider(db)
    base_url = provider.base_url.rstrip("/")

    task = asyncio.create_task(
        _run_flux_text2img(
            app_id=app_id,
            generation_id=payload.generation_id,
            prompt_text=payload.prompt,
            workflow_json=payload.workflow_json,
            output_path=out_path,
            base_url=base_url,
            callback_url=payload.callback_url,
        )
    )

    def _surface(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("[flux2img %s] task crashed: %r", payload.generation_id, exc, exc_info=exc)

    task.add_done_callback(_surface)
    logger.info("[flux2img %s] dispatch base=%s out=%s", payload.generation_id, base_url, out_path)
    return RunOut(lab_id=payload.generation_id, status="started")


async def _run_flux_text2img(
    *,
    app_id: str,
    generation_id: str,
    prompt_text: str,
    workflow_json: dict,
    output_path: Path,
    base_url: str,
    callback_url: str,
) -> None:
    final_status = "failed"
    out_str: str | None = None
    error_msg: str | None = None
    try:
        wf = json.loads(json.dumps(workflow_json))
        # Flux.1-Dev txt2img workflow nodes (see workflows/flux_dev_checkpoint_txt_to_img.json)
        try:
            wf["56:51"]["inputs"]["text"] = prompt_text
            wf["56:52"]["inputs"]["seed"] = random.randint(1, 2**31 - 1)
        except KeyError as exc:
            raise RuntimeError(f"Flux workflow missing expected node {exc}")

        prompt_id = await _queue_workflow(base_url, wf)
        logger.info("[flux2img %s] queued prompt_id=%s", generation_id, prompt_id)
        history = await _wait_for_history(base_url, prompt_id, COMFYUI_TIMEOUT_SEC)

        status_info = history.get("status", {})
        if status_info.get("status_str") == "error":
            messages = status_info.get("messages", [])
            err_msgs = [m for m in messages if m and m[0] == "execution_error"]
            detail = json.dumps(err_msgs[0][1]) if err_msgs and len(err_msgs[0]) > 1 else str(messages)
            raise RuntimeError(f"ComfyUI execution error: {detail[:400]}")

        outputs = history.get("outputs", {})
        first = None
        for _node_id, node_out in outputs.items():
            for item in node_out.get("images", []):
                if item.get("filename"):
                    first = item
                    break
            if first:
                break
        if not first:
            raise RuntimeError("ComfyUI returned no output image")

        params = {"filename": first["filename"], "type": first.get("type", "output")}
        if first.get("subfolder"):
            params["subfolder"] = first["subfolder"]
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            dl = await client.get(f"{base_url}/view", params=params)
            dl.raise_for_status()
            data = dl.content

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
        out_str = str(output_path)
        final_status = "completed"
        logger.info("[flux2img %s] DONE -> %s (%d bytes)", generation_id, out_str, len(data))
    except Exception as exc:
        logger.exception("[flux2img %s] failed", generation_id)
        error_msg = str(exc)[:500]

    cb_payload: dict[str, Any] = {"generation_id": generation_id, "status": final_status}
    if out_str:
        cb_payload["output_path"] = out_str
    if error_msg:
        cb_payload["error"] = error_msg

    await _send_callback(
        app_id=app_id,
        callback_url=callback_url,
        payload=cb_payload,
        log_prefix=f"[flux2img {generation_id}]",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Lab-driven consumer-app runner (generic)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/run_lab", response_model=RunLabOut)
async def run_lab(
    request: Request,
    db: DbSession,
):
    """Clone a template lab, seed context files, run it, and copy outputs.

    Flow:
      1. Validate HMAC + payload.
      2. Clone the template lab (full copy of agents + config) under a fresh
         name ``app:{template-name}:{suffix-or-genid}``.
      3. Write each ``context_files`` entry into the cloned lab workspace.
      4. Start the lab and await completion (with a hard timeout).
      5. Copy each declared ``output_artifacts.src_path`` from the lab workspace
         into ``${APP_UPLOADS_ROOT}/{app_id}/{generation_id}/{public_name}``.
      6. POST a signed callback to ``callback_url`` reporting status + the first
         artifact's path as ``output_path``.
    """
    from app.repositories.lab_repo import LabAgentRepository, LabRepository

    body, app_id = await _auth(request, db)
    payload = RunLabIn.model_validate_json(body)

    try:
        template_uuid = UUID(payload.template_lab_id)
        generation_uuid = UUID(payload.generation_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bad UUID")

    # Validate paths up front so we fail-fast before spinning up a runner.
    for cf in payload.context_files:
        _safe_relpath(cf.path)
    for art in payload.output_artifacts:
        _safe_relpath(art.src_path)
        _safe_relpath(art.public_name)

    template = await LabRepository(db).get_by_id(template_uuid)
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template lab not found")

    # Always include a short generation-id slug to guarantee uniqueness even
    # when two users request the exact same company / suffix concurrently.
    gen_slug = str(generation_uuid)[:8]
    raw_suffix = (payload.name_suffix or "").strip()[:60]
    suffix = f"{raw_suffix} [{gen_slug}]" if raw_suffix else gen_slug
    new_name = f"app:{template.name}:{suffix}"

    new_lab = await _clone_lab(db, template, new_name)

    # Merge run-time context files into the cloned lab's JSONB so the
    # orchestrator + agents see them inline in their system prompt
    # (lab_runner / loop_strategies inject ``lab.context_files`` under
    # the <context_files> block). Map path -> name to match that schema.
    if payload.context_files:
        merged = list(new_lab.context_files or [])
        existing_names = {item.get("name") for item in merged if isinstance(item, dict)}
        for cf in payload.context_files:
            if cf.path in existing_names:
                # override an existing template entry with the runtime value
                merged = [
                    {"name": cf.path, "content": cf.content}
                    if isinstance(item, dict) and item.get("name") == cf.path
                    else item
                    for item in merged
                ]
            else:
                merged.append({"name": cf.path, "content": cf.content})
        new_lab.context_files = merged
        await db.flush()

    await db.commit()

    # Also write context files into the cloned lab workspace so agents
    # can ``file_read`` them as actual files in their sandbox.
    lab_dir = LAB_RESOURCES_ROOT / str(new_lab.id)
    lab_dir.mkdir(parents=True, exist_ok=True)
    for cf in payload.context_files:
        target = lab_dir / _safe_relpath(cf.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(cf.content)

    # Spawn background task that runs the lab to completion + copies artifacts + callbacks.
    task = asyncio.create_task(
        _drive_app_lab(
            app_id=app_id,
            lab_id=new_lab.id,
            generation_id=generation_uuid,
            output_artifacts=payload.output_artifacts,
            callback_url=payload.callback_url,
        )
    )

    def _surface(t: asyncio.Task) -> None:
        if t.cancelled():
            logger.warning("[app-lab%s] task cancelled", generation_uuid)
            return
        exc = t.exception()
        if exc is not None:
            logger.error("[app-lab%s] task crashed: %r", generation_uuid, exc, exc_info=exc)

    task.add_done_callback(_surface)
    logger.info(
        "[app-lab%s] dispatched lab=%s template=%s",
        generation_uuid, new_lab.id, template_uuid,
    )
    return RunLabOut(lab_id=str(new_lab.id), status="started")


async def _clone_lab(db, template, new_name: str):
    """Full duplicate of a template lab (mirrors duplicate_lab in labs.py).

    Skips ACL/permission checks: this is an internal consumer-app op authenticated
    by HMAC. The clone is owned by the system (acl=None → admin-only access).
    """
    from app.repositories.lab_repo import (
        LabAgentRepository,
        LabRepository,
        LabResourceRepository,
        LabToolRepository,
    )

    lab_repo = LabRepository(db)
    new_lab = await lab_repo.create(
        name=new_name,
        description=template.description,
        loop_type=template.loop_type,
        loop_config=template.loop_config,
        strategy_prompt_override=template.strategy_prompt_override,
        orchestrator_model_id=template.orchestrator_model_id,
        orchestrator_prompt=template.orchestrator_prompt,
        orchestrator_temperature=template.orchestrator_temperature,
        orchestrator_max_tokens=template.orchestrator_max_tokens,
        orchestrator_tools=template.orchestrator_tools,
        orchestrator_tool_set_id=template.orchestrator_tool_set_id,
        orchestrator_tool_set_ids=template.orchestrator_tool_set_ids,
        max_iterations=template.max_iterations,
        max_duration_sec=template.max_duration_sec,
        context_files=template.context_files,
        share_memory_override=template.share_memory_override,
        auto_sweep_memory=template.auto_sweep_memory,
        tool_max_calls=template.tool_max_calls,
        tool_timeout_sec=template.tool_timeout_sec,
        tool_max_output_kb=template.tool_max_output_kb,
        tool_container_memory_mb=template.tool_container_memory_mb,
    )

    agent_repo = LabAgentRepository(db)
    for agent in await agent_repo.get_by_lab(template.id):
        await agent_repo.create(
            lab_id=new_lab.id,
            name=agent.name,
            role=agent.role,
            system_prompt=agent.system_prompt,
            model_id=agent.model_id,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
            tools=agent.tools,
            tool_set_id=agent.tool_set_id,
            tool_set_ids=agent.tool_set_ids,
            is_active=agent.is_active,
            sort_order=agent.sort_order,
            share_memory=agent.share_memory,
            callable_agents=agent.callable_agents,
        )

    tool_repo = LabToolRepository(db)
    for tool in await tool_repo.get_by_lab(template.id):
        await tool_repo.create(
            lab_id=new_lab.id,
            name=tool.name,
            description=tool.description,
            tool_type=tool.tool_type,
            config=tool.config,
            execution_side=tool.execution_side,
            is_enabled=tool.is_enabled,
        )

    return new_lab


async def _synthesize_fallback_artifacts(
    *,
    lab_id: UUID,
    out_dir: Path,
    expected: list[OutputArtifactIn],
) -> list[Path]:
    """Best-effort fallback: synthesize minimal artifacts from lab message history.

    Used when the lab finished without producing any of the declared output files.
    Builds a markdown summary from the orchestrator's last messages and the most
    recent agent outputs, then wraps it as HTML/text per the expected file extensions.
    Returns the list of synthesized artifact paths (may be empty if nothing usable).
    """
    from sqlalchemy import desc, select as _select
    from app.database import async_session
    from app.models.orchestrator import LabMessage

    try:
        async with async_session() as db:
            rows = (
                await db.execute(
                    _select(LabMessage)
                    .where(LabMessage.lab_id == lab_id)
                    .order_by(desc(LabMessage.created_at))
                    .limit(40)
                )
            ).scalars().all()
    except Exception:
        logger.exception("[app-lab%s] fallback: cannot query lab messages", lab_id)
        return []

    if not rows:
        return []

    # Reverse to chronological for assembly.
    rows = list(reversed(rows))

    lines: list[str] = []
    lines.append("# Partial summary (fallback)\n")
    lines.append(
        "_The lab finished but did not produce the declared output files. "
        "This summary was reconstructed from the orchestrator and agent message log._\n"
    )

    # Orchestrator's most-recent assistant content.
    orch_msgs = [m for m in rows if (m.sender_type or "").lower() in ("orchestrator", "assistant")]
    if orch_msgs:
        lines.append("## Orchestrator final notes\n")
        for m in orch_msgs[-3:]:
            content = (m.content or "").strip()
            if content:
                lines.append(content[:4000])
                lines.append("")

    # Per-agent latest contributions.
    agent_msgs: dict[str, str] = {}
    for m in rows:
        sender = (m.sender_name or m.sender_type or "").strip()
        if not sender or (m.sender_type or "").lower() in ("orchestrator", "system"):
            continue
        content = (m.content or "").strip()
        if content:
            agent_msgs[sender] = content
    if agent_msgs:
        lines.append("## Agent contributions\n")
        for name, content in agent_msgs.items():
            lines.append(f"### {name}\n")
            lines.append(content[:3000])
            lines.append("")

    md_text = "\n".join(lines).strip() + "\n"

    synthesized: list[Path] = []
    for art in expected:
        try:
            dst = out_dir / _safe_relpath(art.public_name)
            dst.parent.mkdir(parents=True, exist_ok=True)
            ext = dst.suffix.lower()
            if ext in (".md", ".markdown", ".txt", ""):
                dst.write_text(md_text, encoding="utf-8")
            elif ext in (".html", ".htm"):
                # Naive markdown→HTML wrapper (escape, then preserve paragraph breaks).
                from html import escape as _escape
                escaped = _escape(md_text).replace("\n\n", "</p><p>").replace("\n", "<br>")
                dst.write_text(
                    "<!doctype html><html><head><meta charset=\"utf-8\">"
                    "<title>Partial summary (fallback)</title>"
                    "<style>body{font:14px/1.5 system-ui,sans-serif;max-width:780px;"
                    "margin:2em auto;padding:0 1em;color:#222}h1,h2,h3{color:#111}"
                    ".note{background:#fff7e6;border-left:4px solid #f0a500;"
                    "padding:0.6em 0.9em;margin:1em 0;border-radius:4px;font-size:13px}</style>"
                    "</head><body><div class=\"note\">"
                    "Fallback summary &mdash; the lab did not produce the expected files."
                    "</div><p>" + escaped + "</p></body></html>",
                    encoding="utf-8",
                )
            elif ext == ".json":
                import json as _json
                dst.write_text(
                    _json.dumps({"fallback": True, "summary": md_text}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            else:
                # Skip binary-looking targets; we cannot synthesize images/audio.
                continue
            synthesized.append(dst)
        except Exception:
            logger.exception("[app-lab%s] fallback: failed to write %s", lab_id, art.public_name)
    return synthesized


async def _drive_app_lab(
    *,
    app_id: str,
    lab_id: UUID,
    generation_id: UUID,
    output_artifacts: list[OutputArtifactIn],
    callback_url: str,
) -> None:
    """Run a cloned consumer-app lab to completion, copy artifacts, deliver callback."""
    from app.api.routes.labs_execution import run_lab as _run_lab_route
    from app.database import async_session
    from app.repositories.lab_repo import LabRepository
    from app.services.lab_runner import LabRunner, get_runner

    final_status = "failed"
    output_path: str | None = None
    error_msg: str | None = None
    warnings_list: list[str] = []

    try:
        # Resolve / fall back to a default model if the cloned lab has none.
        async with async_session() as db:
            lab_repo = LabRepository(db)
            lab = await lab_repo.get_by_id(lab_id)
            if not lab:
                raise RuntimeError("Cloned lab disappeared before run")
            if not lab.orchestrator_model_id:
                from app.repositories.orchestrator_repo import (
                    AIModelRepository,
                    OrchestratorSettingsRepository,
                )
                settings_obj = await OrchestratorSettingsRepository(db).get()
                if settings_obj and settings_obj.orchestrator_model:
                    for m in await AIModelRepository(db).get_all():
                        if m.model_identifier == settings_obj.orchestrator_model:
                            await lab_repo.update(lab_id, orchestrator_model_id=m.id)
                            break
                    await db.commit()

        # Pre-warm sandbox.
        from app.services.container_manager import ensure_sandbox
        await ensure_sandbox(lab_id)

        runner = LabRunner(lab_id, async_session)
        try:
            await asyncio.wait_for(runner.run(), timeout=LAB_RUN_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            logger.warning("[app-lab%s] timed out after %ds; stopping", lab_id, LAB_RUN_TIMEOUT_SEC)
            await runner.stop()
            raise RuntimeError(f"Lab run exceeded {LAB_RUN_TIMEOUT_SEC}s timeout")

        # Inspect terminal status from DB.
        async with async_session() as db:
            lab = await LabRepository(db).get_by_id(lab_id)
            lab_status = lab.status if lab else "unknown"
            failure_reason = getattr(lab, "failure_reason", None) if lab else None

        if lab_status == "failed":
            raise RuntimeError(failure_reason or "Lab failed")
        if lab_status not in ("completed", "stopped"):
            raise RuntimeError(f"Lab ended in unexpected status: {lab_status}")

        # Copy declared artifacts.
        lab_dir = LAB_RESOURCES_ROOT / str(lab_id)
        out_dir = _app_upload_dir(app_id, generation_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        copied: list[Path] = []
        missing: list[OutputArtifactIn] = []
        for art in output_artifacts:
            src = lab_dir / _safe_relpath(art.src_path)
            if not src.is_file():
                logger.warning("[app-lab%s] artifact missing: %s", lab_id, art.src_path)
                missing.append(art)
                continue
            dst = out_dir / _safe_relpath(art.public_name)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            copied.append(dst)
        if not copied:
            # Fallback synthesizer: build a minimal text artifact from the lab
            # orchestrator's last messages so the user always gets *something*.
            synthesized = await _synthesize_fallback_artifacts(
                lab_id=lab_id,
                out_dir=out_dir,
                expected=output_artifacts,
            )
            if synthesized:
                copied = synthesized
                warnings_list.append(
                    "Lab finished without producing the expected files; "
                    "a fallback summary was synthesized from the orchestrator's notes."
                )
                logger.warning(
                    "[app-lab%s] synthesized fallback artifacts: %s",
                    lab_id, [str(p) for p in synthesized],
                )
            else:
                raise RuntimeError("Lab finished but produced none of the expected artifacts")
        elif missing:
            warnings_list.append(
                f"{len(missing)} of {len(output_artifacts)} expected artifact(s) were missing."
            )

        output_path = str(copied[0])
        final_status = "completed"
        logger.info("[app-lab%s] DONE artifacts=%d primary=%s warnings=%d", lab_id, len(copied), output_path, len(warnings_list))
    except Exception as exc:
        logger.exception("[app-lab%s] failed", lab_id)
        error_msg = str(exc)[:500]

    # Deliver signed callback.
    cb_payload: dict[str, Any] = {"generation_id": str(generation_id), "status": final_status}
    if output_path:
        cb_payload["output_path"] = output_path
    if error_msg:
        cb_payload["error"] = error_msg
    if warnings_list:
        cb_payload["warnings"] = warnings_list

    await _send_callback(
        app_id=app_id,
        callback_url=callback_url,
        payload=cb_payload,
        log_prefix=f"[app-lab {lab_id}]",
    )


# ── Transcribe (STT dispatcher proxy) ─────────────────────────────────────────
# Lets consumer-app (or any internal client) run audio bytes through the same
# STT dispatcher used by media_pipeline:stt — least-loaded provider + per-host
# semaphore queue. No lab needed; deterministic and cheap.

class TranscribeIn(BaseModel):
    audio_b64: str
    filename: str = "audio.mp3"
    language: str | None = None
    task: str | None = None  # "transcribe" (default) or "translate"
    # Optional whisper model override. Either the user-facing model_identifier
    # ("whisper-large-v3-turbo") as listed by /list_models, or the raw
    # faster-whisper name ("large-v3-turbo"). Must be in the stt-api's
    # STT_AVAILABLE_MODELS allowlist. Omit to use the provider default.
    model: str | None = None


class TranscribeOut(BaseModel):
    text: str
    language: str
    duration: float
    segments_count: int
    provider: str
    model: str | None = None


@router.post("/transcribe", response_model=TranscribeOut)
async def transcribe_audio(
    request: Request,
    db: DbSession,
):
    """Run audio through the STT dispatcher (least-loaded provider, queued)."""
    import base64
    from app.services.pipelines import get_pipeline
    from app.services.tools.tool_media import _acquire_gpu_slot, _gpu_slots, _host_from_url

    body, app_id = await _auth(request, db)
    payload = TranscribeIn.model_validate_json(body)

    try:
        audio_bytes = base64.b64decode(payload.audio_b64)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "audio_b64 is not valid base64")
    if not audio_bytes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "audio_b64 is empty")

    providers = (
        await db.execute(
            select(AIProvider).where(
                AIProvider.provider_type == "stt",
                AIProvider.is_active == True,  # noqa: E712
            )
        )
    ).scalars().all()
    if not providers:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "No active STT provider configured")

    # Sort by queue depth (free hosts first).
    def _depth(p):
        sem = _gpu_slots.get(_host_from_url(p.base_url))
        return 0 if sem is None or sem._value > 0 else 1
    providers.sort(key=_depth)

    extra: dict[str, Any] = {
        "_audio_bytes": audio_bytes,
        "_filename": payload.filename,
    }
    if payload.language:
        extra["language"] = payload.language
    if payload.task:
        extra["task"] = payload.task
    if payload.model:
        extra["model"] = payload.model

    last_error = ""
    for provider in providers:
        host = _host_from_url(provider.base_url)
        pipeline = get_pipeline("stt", provider.base_url)
        params = pipeline.build_tool_params("transcribe", extra)
        try:
            clean_params = pipeline.validate_params(params)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid STT params: {exc}")

        logger.info("[apptranscribe] queuing on %s (host=%s, %d bytes)", provider.name, host, len(audio_bytes))
        sem = await _acquire_gpu_slot(host)
        try:
            result = await pipeline.generate(clean_params)
            if result.success:
                raw = result.raw or {}
                return TranscribeOut(
                    text=raw.get("text", ""),
                    language=raw.get("language", "unknown"),
                    duration=float(result.duration_s or 0.0),
                    segments_count=len(raw.get("segments") or []),
                    provider=provider.name,
                    model=raw.get("model"),
                )
            last_error = result.error or "unknown error"
            logger.warning("[apptranscribe] %s failed: %s — trying next", provider.name, last_error)
        except Exception as exc:
            last_error = str(exc)
            logger.warning("[apptranscribe] %s exception: %s — trying next", provider.name, last_error)
        finally:
            sem.release()

    raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"All STT providers failed: {last_error}")


# ── LLM Complete (chat completion via LabDispatcher load balancer) ────────────
# Lets consumer-app run a one-shot LLM call through the same model dispatcher
# used by labs (caller affinity, queue depth balancing, retry on next provider).
# No lab needed — pure stateless completion.

class LLMMessage(BaseModel):
    role: str
    content: str
    # Optional list of base64-encoded images for vision models (qwen3.5, llava, etc.).
    # Each entry may be raw base64 or a "data:image/png;base64,..." URL.
    # The dispatcher converts to provider-native format (Ollama `images` field
    # or OpenAI multimodal content parts).
    images: list[str] | None = None


class LLMCompleteIn(BaseModel):
    model: str  # model_identifier (e.g. "qwen3.6:35b")
    messages: list[LLMMessage]
    temperature: float = 0.2
    max_tokens: int = 4096
    caller_name: str = "app"
    # OpenAI-style tool definitions ({type:"function", function:{name, description, parameters}}).
    # Forwarded to Ollama (native `tools` field) and OpenAI-compat providers (vLLM, HF TGI).
    # Providers that don't support tools transparently retry without them.
    tools: list[dict] | None = None
    # Ollama-only: pass false to disable native chain-of-thought on reasoning
    # models (qwen3, etc.), true to force it, or "low"/"medium"/"high" for
    # gpt-oss style models. Ignored by non-Ollama providers.
    think: bool | str | None = None


class LLMCompleteOut(BaseModel):
    content: str
    model: str
    provider: str
    tokens_in: int
    tokens_out: int
    duration_ms: int
    # Populated when the model emitted native tool calls. Normalized shape:
    # [{id: "call_0", name: "fn_name", arguments: {...parsed dict...}}, ...].
    # arguments is a dict (already JSON-parsed); if the model returned malformed
    # JSON, arguments is {"raw_arguments": "<original string>"}.
    tool_calls: list[dict] | None = None


@router.post("/llm_complete", response_model=LLMCompleteOut)
async def llm_complete(
    request: Request,
    db: DbSession,
):
    """One-shot LLM completion via the lab dispatcher (load-balanced + queued)."""
    from app.services.lab_dispatcher import LabDispatcher

    body, app_id = await _auth(request, db)
    payload = LLMCompleteIn.model_validate_json(body)

    dispatcher = LabDispatcher(db)
    try:
        result = await dispatcher._call_with_loadbalance(
            model_identifier=payload.model,
            messages=[
                {
                    "role": m.role,
                    "content": m.content,
                    **({"images": m.images} if m.images else {}),
                }
                for m in payload.messages
            ],
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            caller_name=payload.caller_name,
            caller_type=f"app:{app_id}",
            lab_id=None,
            tools=payload.tools,
            think=payload.think,
        )
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))

    return LLMCompleteOut(
        content=result.get("content", ""),
        model=result.get("model", payload.model),
        provider=result.get("provider", "unknown"),
        tokens_in=result.get("tokens_in", 0),
        tokens_out=result.get("tokens_out", 0),
        duration_ms=result.get("duration_ms", 0),
        tool_calls=result.get("tool_calls"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Model catalog — lets a consumer app discover which model_identifiers it can
# pass to /llm_complete. Operator-internal IDs (provider UUIDs, server names)
# are intentionally not exposed.
# ─────────────────────────────────────────────────────────────────────────────


class ListModelsIn(BaseModel):
    available_only: bool = True


class ListModelsEntry(BaseModel):
    model_identifier: str
    available: bool
    provider_types: list[str]
    capabilities: dict[str, Any] = {}


class ListModelsOut(BaseModel):
    models: list[ListModelsEntry]


@router.post("/list_models", response_model=ListModelsOut)
async def list_models(
    request: Request,
    db: DbSession,
):
    """Return the deduplicated catalog of model identifiers the dispatcher can route to.

    Body: ``{"available_only": true}`` (default). Set false to include models
    the dispatcher knows about but that are currently offline.
    """
    from sqlalchemy import func, Integer
    from app.models.orchestrator import AIModel

    body, _app_id = await _auth(request, db)
    payload = ListModelsIn.model_validate_json(body) if body else ListModelsIn()

    stmt = (
        select(
            AIModel.model_identifier,
            func.max(AIModel.is_available.cast(Integer)).label("any_available"),
            func.array_agg(AIProvider.provider_type).label("provider_types"),
            func.array_agg(AIModel.capabilities).label("capabilities_list"),
        )
        .join(AIProvider, AIModel.provider_id == AIProvider.id)
        .where(AIProvider.is_active == True)
        .group_by(AIModel.model_identifier)
        .order_by(AIModel.model_identifier)
    )
    rows = (await db.execute(stmt)).all()

    out: list[ListModelsEntry] = []
    for row in rows:
        is_available = bool(row.any_available)
        if payload.available_only and not is_available:
            continue
        capabilities = next((c for c in (row.capabilities_list or []) if c), {})
        out.append(ListModelsEntry(
            model_identifier=row.model_identifier,
            available=is_available,
            provider_types=sorted({pt for pt in (row.provider_types or []) if pt}),
            capabilities=capabilities,
        ))
    return ListModelsOut(models=out)


# ─────────────────────────────────────────────────────────────────────────────
# Direct ComfyUI LTX-2.3 image-to-video driver (no agent), used by Cinematic Creator
# ─────────────────────────────────────────────────────────────────────────────


class RunLtxImg2VidIn(BaseModel):
    """Direct ComfyUI LTX-2.3 image-to-video driver."""
    generation_id: str
    prompt: str
    negative_prompt: str | None = None
    input_image_path: str  # absolute path inside APP_UPLOADS_ROOT
    workflow_json: dict[str, Any]
    output_path: str  # absolute path inside APP_UPLOADS_ROOT to write the mp4 to
    callback_url: str


@router.post("/run_ltx_image2video", response_model=RunOut)
async def run_ltx_image2video(
    request: Request,
    db: DbSession,
):
    """Direct ComfyUI LTX-2.3 image-to-video driver.

    Uploads the input image into ComfyUI's input dir, mutates the workflow's
    LoadImage + prompt + seed nodes, queues, polls history, downloads the
    output mp4 from the SaveVideo node, writes it to ``output_path``, and
    POSTs a signed callback to ``callback_url``.
    """
    body, app_id = await _auth(request, db)
    payload = RunLtxImg2VidIn.model_validate_json(body)

    in_path = Path(payload.input_image_path)
    out_path = Path(payload.output_path)
    if not _is_subpath(in_path, APP_UPLOADS_ROOT):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "input_image_path out of scope")
    if not _is_subpath(out_path, APP_UPLOADS_ROOT):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "output_path out of scope")
    if not in_path.is_file():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Input image missing: {in_path.name}")

    provider = await _pick_healthy_comfyui_provider(db)
    base_url = provider.base_url.rstrip("/")

    task = asyncio.create_task(
        _run_ltx_image2video(
            app_id=app_id,
            generation_id=payload.generation_id,
            prompt_text=payload.prompt,
            negative_prompt=payload.negative_prompt,
            input_image_path=in_path,
            workflow_json=payload.workflow_json,
            output_path=out_path,
            base_url=base_url,
            callback_url=payload.callback_url,
        )
    )

    def _surface(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("[ltx2vid %s] task crashed: %r", payload.generation_id, exc, exc_info=exc)

    task.add_done_callback(_surface)
    logger.info("[ltx2vid %s] dispatch base=%s in=%s out=%s",
                payload.generation_id, base_url, in_path, out_path)
    return RunOut(lab_id=payload.generation_id, status="started")


async def _run_ltx_image2video(
    *,
    app_id: str,
    generation_id: str,
    prompt_text: str,
    negative_prompt: str | None,
    input_image_path: Path,
    workflow_json: dict,
    output_path: Path,
    base_url: str,
    callback_url: str,
) -> None:
    final_status = "failed"
    out_str: str | None = None
    error_msg: str | None = None
    try:
        # Upload the input image into ComfyUI's input dir.
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            remote_name = await _upload_image(
                client,
                base_url,
                input_image_path,
                remote_name=f"{generation_id}_in{input_image_path.suffix.lower() or '.png'}",
            )
        logger.info("[ltx2vid %s] uploaded input=%s", generation_id, remote_name)

        wf = json.loads(json.dumps(workflow_json))
        # LTX-2.3 image-to-video workflow nodes (see templates/comfyui/ltx2_3_image_prompt_to_video.json):
        #   "269"      LoadImage              -> inputs.image
        #   "320:319"  PrimitiveStringMultiline (positive prompt) -> inputs.value
        #   "320:313"  CLIPTextEncode (negative prompt)           -> inputs.text
        #   "320:276", "320:277"  RandomNoise -> inputs.noise_seed
        try:
            wf["269"]["inputs"]["image"] = remote_name
            wf["320:319"]["inputs"]["value"] = prompt_text
            if negative_prompt is not None and "320:313" in wf:
                wf["320:313"]["inputs"]["text"] = negative_prompt
            wf["320:276"]["inputs"]["noise_seed"] = random.randint(1, 2**31 - 1)
            wf["320:277"]["inputs"]["noise_seed"] = random.randint(1, 2**31 - 1)
        except KeyError as exc:
            raise RuntimeError(f"LTX workflow missing expected node {exc}")

        prompt_id = await _queue_workflow(base_url, wf)
        logger.info("[ltx2vid %s] queued prompt_id=%s", generation_id, prompt_id)
        history = await _wait_for_history(base_url, prompt_id, COMFYUI_TIMEOUT_SEC)

        status_info = history.get("status", {})
        if status_info.get("status_str") == "error":
            messages = status_info.get("messages", [])
            err_msgs = [m for m in messages if m and m[0] == "execution_error"]
            detail = json.dumps(err_msgs[0][1]) if err_msgs and len(err_msgs[0]) > 1 else str(messages)
            raise RuntimeError(f"ComfyUI execution error: {detail[:400]}")

        # LTX SaveVideo (node "75") surfaces under "videos" (or sometimes "gifs").
        outputs = history.get("outputs", {})
        first = None
        for _node_id, node_out in outputs.items():
            for key in ("videos", "gifs", "images"):
                for item in node_out.get(key, []):
                    if item.get("filename"):
                        first = item
                        break
                if first:
                    break
            if first:
                break
        if not first:
            raise RuntimeError("ComfyUI returned no output video")

        params = {"filename": first["filename"], "type": first.get("type", "output")}
        if first.get("subfolder"):
            params["subfolder"] = first["subfolder"]
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            dl = await client.get(f"{base_url}/view", params=params)
            dl.raise_for_status()
            data = dl.content

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
        out_str = str(output_path)
        final_status = "completed"
        logger.info("[ltx2vid %s] DONE -> %s (%d bytes)", generation_id, out_str, len(data))
    except Exception as exc:
        logger.exception("[ltx2vid %s] failed", generation_id)
        error_msg = str(exc)[:500]

    cb_payload: dict[str, Any] = {"generation_id": generation_id, "status": final_status}
    if out_str:
        cb_payload["output_path"] = out_str
    if error_msg:
        cb_payload["error"] = error_msg

    await _send_callback(
        app_id=app_id,
        callback_url=callback_url,
        payload=cb_payload,
        log_prefix=f"[ltx2vid {generation_id}]",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Direct ffmpeg op driver (no agent), used by Cinematic Creator
# ─────────────────────────────────────────────────────────────────────────────


class RunFfmpegOpIn(BaseModel):
    """Local ffmpeg subprocess driver. Two ops: extract_last_frame and concat."""
    generation_id: str
    op: str  # "extract_last_frame" | "concat"
    inputs: list[str]  # one path for extract, N paths for concat (in order)
    output_path: str
    callback_url: str


@router.post("/run_ffmpeg_op", response_model=RunOut)
async def run_ffmpeg_op(
    request: Request,
    db: DbSession,
):
    """Run a small ffmpeg job locally and POST a signed callback when done."""
    body, app_id = await _auth(request, db)
    payload = RunFfmpegOpIn.model_validate_json(body)

    if payload.op not in ("extract_last_frame", "concat"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown op: {payload.op}")
    if not payload.inputs:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "inputs cannot be empty")

    out_path = Path(payload.output_path)
    if not _is_subpath(out_path, APP_UPLOADS_ROOT):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "output_path out of scope")
    in_paths: list[Path] = []
    for raw in payload.inputs:
        p = Path(raw)
        if not _is_subpath(p, APP_UPLOADS_ROOT):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"input out of scope: {raw}")
        if not p.is_file():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"input missing: {raw}")
        in_paths.append(p)

    task = asyncio.create_task(
        _run_ffmpeg_op(
            app_id=app_id,
            generation_id=payload.generation_id,
            op=payload.op,
            input_paths=in_paths,
            output_path=out_path,
            callback_url=payload.callback_url,
        )
    )

    def _surface(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("[ffmpeg %s] task crashed: %r", payload.generation_id, exc, exc_info=exc)

    task.add_done_callback(_surface)
    logger.info("[ffmpeg %s] dispatch op=%s inputs=%d out=%s",
                payload.generation_id, payload.op, len(in_paths), out_path)
    return RunOut(lab_id=payload.generation_id, status="started")


async def _run_ffmpeg_op(
    *,
    app_id: str,
    generation_id: str,
    op: str,
    input_paths: list[Path],
    output_path: Path,
    callback_url: str,
) -> None:
    final_status = "failed"
    out_str: str | None = None
    error_msg: str | None = None
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if op == "extract_last_frame":
            cmd = [
                "ffmpeg", "-y",
                "-sseof", "-0.5",
                "-i", str(input_paths[0]),
                "-vframes", "1",
                "-q:v", "2",
                str(output_path),
            ]
        elif op == "concat":
            # Build a temporary concat list file inside the same directory as the output.
            list_path = output_path.parent / f".concat_{generation_id}.txt"
            list_path.write_text(
                "".join(f"file '{p.as_posix()}'\n" for p in input_paths),
                encoding="utf-8",
            )
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_path),
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "20",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                str(output_path),
            ]
        else:
            raise RuntimeError(f"Unknown op: {op}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"ffmpeg timed out after 600s (op={op})")

        if proc.returncode != 0:
            tail = (stderr or b"").decode(errors="replace")[-500:]
            raise RuntimeError(f"ffmpeg exit {proc.returncode}: {tail}")

        if op == "concat":
            try:
                list_path.unlink()
            except Exception:
                pass

        out_str = str(output_path)
        final_status = "completed"
        logger.info("[ffmpeg %s] DONE op=%s -> %s", generation_id, op, out_str)
    except Exception as exc:
        logger.exception("[ffmpeg %s] failed (op=%s)", generation_id, op)
        error_msg = str(exc)[:500]

    cb_payload: dict[str, Any] = {"generation_id": generation_id, "status": final_status}
    if out_str:
        cb_payload["output_path"] = out_str
    if error_msg:
        cb_payload["error"] = error_msg

    await _send_callback(
        app_id=app_id,
        callback_url=callback_url,
        payload=cb_payload,
        log_prefix=f"[ffmpeg {generation_id}]",
    )
