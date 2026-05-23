"""Bob Manager — RAG API routes."""

from __future__ import annotations

import json
import ipaddress
import logging
import re
import socket
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status

from app.api.dependencies import DbSession, get_current_user
from app.services.authorization import check_permission, Permission
from app.schemas.rag import (
    RagAccessCreate,
    RagAccessResponse,
    RagAccessUpdate,
    RagCollectionCreate,
    RagCollectionResponse,
    RagCollectionUpdate,
    RagBatchActionResponse,
    RagDocumentReingestRequest,
    RagDocumentResponse,
    RagSearchRequest,
    RagSearchResponse,
    RagUrlDocumentCreate,
)
from app.services.rag_ingest import sanitize_html_document
from app.services.rag_service import RAG_STAGING_ROOT, RagService, run_ingestion_task

router = APIRouter(tags=["rag"])
logger = logging.getLogger(__name__)


def _validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="Only http and https URLs are supported")

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="URL must include a hostname")

    lowered = hostname.lower()
    if lowered in {"localhost", "0.0.0.0"} or lowered.endswith(".local"):
        raise HTTPException(status_code=400, detail="Private or local URLs are not allowed")

    try:
        parsed_ip = ipaddress.ip_address(lowered)
        if parsed_ip.is_private or parsed_ip.is_loopback or parsed_ip.is_link_local or parsed_ip.is_multicast or parsed_ip.is_reserved:
            raise HTTPException(status_code=400, detail="Private or local URLs are not allowed")
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail=f"Failed to resolve hostname: {exc}")

    for info in infos:
        resolved_ip = ipaddress.ip_address(info[4][0])
        if resolved_ip.is_private or resolved_ip.is_loopback or resolved_ip.is_link_local or resolved_ip.is_multicast or resolved_ip.is_reserved:
            raise HTTPException(status_code=400, detail="Private or local URLs are not allowed")

    return url


def _slugify_filename(value: str, fallback: str = "webpage") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned[:120] or fallback


async def _fetch_webpage_text_http(url: str) -> tuple[str, str]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=True) as client:
        response = await client.get(
            url,
            headers={
                "User-Agent": "BobManagerRagFetcher/1.0",
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            },
        )
        response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if "html" in content_type:
        parsed = BeautifulSoup(response.text, "html.parser")
        title = parsed.title.get_text(strip=True) if parsed.title else urlparse(url).hostname or "webpage"
        body = sanitize_html_document(response.text)
    elif "text/" in content_type:
        title = urlparse(url).hostname or "webpage"
        body = response.text.strip()
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported content type for URL ingestion: {content_type or 'unknown'}")

    rendered = f"Title: {title}\nURL: {url}\n\n{body}".strip()
    return title, rendered


async def _fetch_webpage_text_browser(url: str) -> tuple[str, str]:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "DNT": "1",
            },
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            title = (await page.title()) or (urlparse(url).hostname or "webpage")
            html = await page.content()
        finally:
            await context.close()
            await browser.close()

    body = sanitize_html_document(html)
    rendered = f"Title: {title}\nURL: {url}\n\n{body}".strip()
    return title, rendered


async def _fetch_webpage_text(url: str, fetch_mode: str) -> tuple[str, str, str]:
    if fetch_mode == "http":
        title, rendered = await _fetch_webpage_text_http(url)
        return title, rendered, "http"

    if fetch_mode == "browser":
        try:
            title, rendered = await _fetch_webpage_text_browser(url)
            return title, rendered, "browser"
        except Exception as exc:
            logger.warning("Browser-rendered fetch failed for %s, falling back to HTTP fetch", url, exc_info=True)
            title, rendered = await _fetch_webpage_text_http(url)
            return title, rendered, "http"

    try:
        title, rendered = await _fetch_webpage_text_browser(url)
        return title, rendered, "browser"
    except Exception:
        logger.warning("Auto browser-rendered fetch failed for %s, falling back to HTTP fetch", url, exc_info=True)
        title, rendered = await _fetch_webpage_text_http(url)
        return title, rendered, "http"


def _document_to_response(document) -> RagDocumentResponse:
    return RagDocumentResponse(
        id=document.id,
        collection_id=document.collection_id,
        filename=document.filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        chunk_size=document.chunk_size,
        chunk_overlap=document.chunk_overlap,
        splitter=document.splitter,
        chunk_count=document.chunk_count,
        status=document.status,
        error_message=document.error_message,
        metadata=document.metadata_json or {},
        ingested_at=document.ingested_at,
        created_at=document.created_at,
    )


@router.get("/rag/collections", response_model=list[RagCollectionResponse])
async def list_collections(
    db: DbSession,
    user: dict = Depends(get_current_user),
    include_app_owned: bool = False,
):
    collections = await RagService(db).list_collections(user=user)
    if include_app_owned:
        return collections
    # Hide consumer-app-owned RAG collections from the operator UI by default.
    # Tag format: ``app:<app_id>:rag:<name>``. Pass ``?include_app_owned=true``
    # to surface them for debugging.
    from app.services.rag_service import is_app_owned_tag

    return [
        c for c in collections
        if not is_app_owned_tag((c.acl or {}).get("tag"))
    ]


@router.post("/rag/collections", response_model=RagCollectionResponse, status_code=status.HTTP_201_CREATED)
async def create_collection(data: RagCollectionCreate, db: DbSession, user: dict = Depends(get_current_user)):
    svc = RagService(db)
    try:
        collection = await svc.create_collection(data, user=user)
        await db.commit()
        return collection
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/rag/collections/{collection_id}", response_model=RagCollectionResponse)
async def get_collection(collection_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    collection = await RagService(db).get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    check_permission(user, collection.acl, Permission.VIEW)
    return collection


@router.patch("/rag/collections/{collection_id}", response_model=RagCollectionResponse)
async def update_collection(collection_id: UUID, data: RagCollectionUpdate, db: DbSession, user: dict = Depends(get_current_user)):
    svc = RagService(db)
    collection = await svc.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    check_permission(user, collection.acl, Permission.EDIT)
    updated = await svc.update_collection(collection_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Collection not found")
    await db.commit()
    return updated


@router.delete("/rag/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(collection_id: UUID, db: DbSession, user: dict = Depends(get_current_user)):
    svc = RagService(db)
    collection = await svc.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    check_permission(user, collection.acl, Permission.DELETE)
    await svc.delete_collection(collection_id)
    await db.commit()


@router.get("/rag/collections/{collection_id}/documents", response_model=list[RagDocumentResponse])
async def list_documents(collection_id: UUID, db: DbSession):
    svc = RagService(db)
    collection = await svc.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    documents = await svc.list_documents(collection_id)
    return [_document_to_response(doc) for doc in documents]


@router.post("/rag/collections/{collection_id}/documents", response_model=RagDocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    collection_id: UUID,
    background_tasks: BackgroundTasks,
    db: DbSession,
    file: UploadFile = File(...),
    chunk_size: int | None = Form(default=None),
    chunk_overlap: int | None = Form(default=None),
    splitter: str | None = Form(default=None),
    metadata: str | None = Form(default=None),
):
    svc = RagService(db)
    collection = await svc.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    try:
        parsed_metadata = json.loads(metadata) if metadata else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="metadata must be valid JSON")

    chunk_size = chunk_size or collection.default_chunk_size
    chunk_overlap = chunk_overlap if chunk_overlap is not None else collection.default_chunk_overlap
    splitter = splitter or collection.default_splitter
    if chunk_size < 64 or chunk_size > 4096:
        raise HTTPException(status_code=400, detail="chunk_size must be between 64 and 4096")
    if chunk_overlap < 0 or chunk_overlap > 512:
        raise HTTPException(status_code=400, detail="chunk_overlap must be between 0 and 512")
    if chunk_overlap > chunk_size:
        raise HTTPException(status_code=400, detail="chunk_overlap cannot exceed chunk_size")

    staging_dir = RAG_STAGING_ROOT / str(collection_id)
    staging_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}_{Path(file.filename or 'upload').name}"
    staged_path = staging_dir / stored_name
    content = await file.read()
    staged_path.write_bytes(content)

    document = await svc.create_document(
        collection_id=collection_id,
        filename=file.filename or stored_name,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        splitter=splitter,
        metadata=parsed_metadata,
    )
    await db.commit()

    background_tasks.add_task(run_ingestion_task, document.id, str(staged_path))
    return _document_to_response(document)


@router.post("/rag/collections/{collection_id}/documents/from-url", response_model=RagDocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document_from_url(
    collection_id: UUID,
    data: RagUrlDocumentCreate,
    background_tasks: BackgroundTasks,
    db: DbSession,
):
    svc = RagService(db)
    collection = await svc.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    url = _validate_public_url(data.url.strip())
    chunk_size = data.chunk_size or collection.default_chunk_size
    chunk_overlap = data.chunk_overlap if data.chunk_overlap is not None else collection.default_chunk_overlap
    splitter = data.splitter or collection.default_splitter
    if chunk_overlap > chunk_size:
        raise HTTPException(status_code=400, detail="chunk_overlap cannot exceed chunk_size")

    try:
        title, rendered_text, fetch_mode_used = await _fetch_webpage_text(url, data.fetch_mode)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to render URL content: {exc}")

    staging_dir = RAG_STAGING_ROOT / str(collection_id)
    staging_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_slugify_filename(title)}.txt"
    stored_name = f"{uuid4().hex}_{filename}"
    staged_path = staging_dir / stored_name
    staged_path.write_text(rendered_text, encoding="utf-8")

    metadata = {
        **data.metadata,
        "source_url": url,
        "source_type": "webpage",
        "page_title": title,
        "fetch_mode": fetch_mode_used,
    }
    document = await svc.create_document(
        collection_id=collection_id,
        filename=filename,
        content_type="text/plain",
        size_bytes=len(rendered_text.encode("utf-8")),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        splitter=splitter,
        metadata=metadata,
    )
    await db.commit()

    background_tasks.add_task(run_ingestion_task, document.id, str(staged_path))
    return _document_to_response(document)


@router.delete("/rag/collections/{collection_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(collection_id: UUID, document_id: UUID, db: DbSession):
    deleted = await RagService(db).delete_document(collection_id, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")


@router.post("/rag/collections/{collection_id}/documents/{document_id}/reingest", response_model=RagDocumentResponse)
async def reingest_document(
    collection_id: UUID,
    document_id: UUID,
    background_tasks: BackgroundTasks,
    db: DbSession,
    data: RagDocumentReingestRequest | None = None,
):
    svc = RagService(db)
    collection = await svc.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    documents = await svc.list_documents(collection_id)
    target = next((doc for doc in documents if doc.id == document_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Document not found")

    staging_dir = RAG_STAGING_ROOT / str(collection_id)
    candidates = sorted(staging_dir.glob(f"*_{target.filename}"))
    if not candidates:
        raise HTTPException(status_code=404, detail="No staged source file found for reingest")

    request = data or RagDocumentReingestRequest()
    chunk_size = request.chunk_size if request.chunk_size is not None else collection.default_chunk_size
    chunk_overlap = request.chunk_overlap if request.chunk_overlap is not None else collection.default_chunk_overlap
    splitter = request.splitter or collection.default_splitter

    if chunk_overlap > chunk_size:
        raise HTTPException(status_code=400, detail="chunk_overlap cannot exceed chunk_size")

    target = await svc.prepare_reingest(
        collection_id,
        document_id,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        splitter=splitter,
    )
    if not target:
        raise HTTPException(status_code=404, detail="Document not found")

    background_tasks.add_task(run_ingestion_task, target.id, str(candidates[-1]))
    return _document_to_response(target)


@router.post("/rag/collections/{collection_id}/documents/reingest-all", response_model=RagBatchActionResponse)
async def reingest_all_documents(
    collection_id: UUID,
    background_tasks: BackgroundTasks,
    db: DbSession,
    data: RagDocumentReingestRequest | None = None,
):
    svc = RagService(db)
    collection = await svc.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    request = data or RagDocumentReingestRequest()
    chunk_size = request.chunk_size if request.chunk_size is not None else collection.default_chunk_size
    chunk_overlap = request.chunk_overlap if request.chunk_overlap is not None else collection.default_chunk_overlap
    splitter = request.splitter or collection.default_splitter
    if chunk_overlap > chunk_size:
        raise HTTPException(status_code=400, detail="chunk_overlap cannot exceed chunk_size")

    documents = await svc.list_documents(collection_id)
    queued = 0
    staging_dir = RAG_STAGING_ROOT / str(collection_id)
    for document in documents:
        candidates = sorted(staging_dir.glob(f"*_{document.filename}"))
        if not candidates:
            continue
        target = await svc.prepare_reingest(
            collection_id,
            document.id,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            splitter=splitter,
        )
        if not target:
            continue
        background_tasks.add_task(run_ingestion_task, target.id, str(candidates[-1]))
        queued += 1

    return RagBatchActionResponse(queued=queued)


@router.get("/labs/{lab_id}/rag-access", response_model=list[RagAccessResponse])
async def list_lab_rag_access(lab_id: UUID, db: DbSession):
    return await RagService(db).list_lab_access(lab_id)


@router.post("/labs/{lab_id}/rag-access", response_model=RagAccessResponse, status_code=status.HTTP_201_CREATED)
async def grant_lab_rag_access(lab_id: UUID, data: RagAccessCreate, db: DbSession):
    try:
        return await RagService(db).grant_lab_access(
            lab_id=lab_id,
            collection_id=data.collection_id,
            can_read=data.can_read,
            can_write=data.can_write,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/labs/{lab_id}/rag-access/{collection_id}", response_model=RagAccessResponse)
async def update_lab_rag_access(
    lab_id: UUID,
    collection_id: UUID,
    data: RagAccessUpdate,
    db: DbSession,
):
    try:
        updated = await RagService(db).update_lab_access(
            lab_id=lab_id,
            collection_id=collection_id,
            can_read=data.can_read,
            can_write=data.can_write,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not updated:
        raise HTTPException(status_code=404, detail="Access entry not found")
    return updated


@router.delete("/labs/{lab_id}/rag-access/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_lab_rag_access(lab_id: UUID, collection_id: UUID, db: DbSession):
    deleted = await RagService(db).revoke_lab_access(lab_id, collection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Access entry not found")


@router.post("/rag/search", response_model=RagSearchResponse)
async def search_rag(data: RagSearchRequest, db: DbSession):
    try:
        results = await RagService(db).search(
            collection_name=data.collection,
            query=data.query,
            top_k=data.top_k,
            score_threshold=data.score_threshold,
            metadata_filter=data.filter,
            mode=data.mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return RagSearchResponse(collection=data.collection, results=results)
