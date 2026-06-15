"""Lab Files — resources, output files, messages & memories routes."""

import mimetypes
import os
import re as _re
import uuid as uuid_mod
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.dependencies import DbSession, get_current_user
from app.api.routes.labs import LAB_RESOURCES_ROOT
from app.repositories.lab_repo import (
    LabMemoryRepository,
    LabMessageRepository,
    LabRepository,
    LabResourceRepository,
)
from app.schemas.orchestrator import (
    LabMemoryResponse,
    LabMessageResponse,
    LabResourceResponse,
)
from app.services.authorization import Permission, check_permission

router = APIRouter(tags=["labs"])

# Largest text payload we preview/edit inline. Reads beyond this are
# truncated (and editing is blocked) so the browser never round-trips a
# partial file back over a save and silently drops the tail.
_INLINE_TEXT_MAX_BYTES = 512_000

_TEXT_MIME = {
    "application/json",
    "application/javascript",
    "application/xml",
    "application/x-yaml",
    "application/x-sh",
}
_TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".json",
    ".yml",
    ".yaml",
    ".sh",
    ".txt",
    ".csv",
    ".xml",
    ".toml",
    ".cfg",
    ".ini",
    ".log",
}


def _detect_text(target: Path) -> tuple[bool, str]:
    """Return (is_text, mime) using the same allowlist the viewer trusts.

    Editable set == viewable set: anything the inline previewer treats as
    text can be edited, nothing else.
    """
    mime, _ = mimetypes.guess_type(target.name)
    mime = mime or "application/octet-stream"
    is_text = mime.startswith("text/") or mime in _TEXT_MIME or target.suffix in _TEXT_SUFFIXES
    return is_text, mime


class SaveFileContentBody(BaseModel):
    content: str


# ══════════════════════════════════════════════════
# Lab Messages & Memories
# ══════════════════════════════════════════════════


@router.get("/{lab_id}/messages", response_model=list[LabMessageResponse])
async def list_lab_messages(
    lab_id: UUID,
    db: DbSession,
    user: dict = Depends(get_current_user),
    limit: int = 500,
    iteration: int | None = None,
    sender_agent_id: UUID | None = None,
    include_targeting: bool = True,
):
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.VIEW)
    return await LabMessageRepository(db).get_by_lab(
        lab_id,
        limit=limit,
        iteration=iteration,
        sender_agent_id=sender_agent_id,
        include_targeting=include_targeting,
    )


@router.get("/{lab_id}/memories", response_model=list[LabMemoryResponse])
async def list_lab_memories(
    lab_id: UUID,
    db: DbSession,
    user: dict = Depends(get_current_user),
    scope: str | None = None,
    limit: int = 50,
    agent_id: UUID | None = None,
):
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.VIEW)
    return await LabMemoryRepository(db).get_by_lab(
        lab_id, scope=scope, limit=limit, agent_id=agent_id
    )


@router.patch("/{lab_id}/memories/{memory_id}", response_model=LabMemoryResponse)
async def toggle_memory_visibility(
    lab_id: UUID,
    memory_id: UUID,
    db: DbSession,
    body: dict,
):
    """Toggle is_hidden on a lab memory."""
    from sqlalchemy import select
    from sqlalchemy import update as sql_update

    from app.models.orchestrator import LabMemory

    is_hidden = bool(body.get("is_hidden", False))
    await db.execute(
        sql_update(LabMemory)
        .where(LabMemory.id == memory_id, LabMemory.lab_id == lab_id)
        .values(is_hidden=is_hidden)
    )
    await db.commit()
    result = await db.execute(select(LabMemory).where(LabMemory.id == memory_id))
    mem = result.scalar_one_or_none()
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    return mem


# ══════════════════════════════════════════════════
# Lab Resources (file uploads)
# ══════════════════════════════════════════════════

ALLOWED_EXTENSIONS = {
    ".txt",
    ".md",
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".ini",
    ".csv",
    ".xml",
    ".html",
    ".css",
    ".sql",
    ".sh",
    ".bash",
    ".rs",
    ".go",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".r",
    ".lua",
    ".dockerfile",
    ".makefile",
    ".gitignore",
    ".env",
    ".log",
    ".conf",
    # Images
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
    # Documents
    ".pdf",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def _classify_resource(ext: str, content_type: str) -> str:
    """Determine resource_type from extension."""
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext == ".pdf":
        return "pdf"
    return (
        "code"
        if ext
        in {
            ".py",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".rs",
            ".go",
            ".java",
            ".c",
            ".cpp",
            ".h",
            ".hpp",
            ".rb",
            ".php",
            ".swift",
            ".kt",
            ".scala",
        }
        else "file"
    )


@router.get("/{lab_id}/resources", response_model=list[LabResourceResponse])
async def list_lab_resources(lab_id: UUID, db: DbSession):
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    return await LabResourceRepository(db).get_by_lab(lab_id)


@router.post(
    "/{lab_id}/resources",
    response_model=LabResourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_lab_resource(lab_id: UUID, file: UploadFile = File(...), db: DbSession = None):
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")

    # Validate extension
    original = file.filename or "upload"
    ext = os.path.splitext(original)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400, f"File type '{ext}' not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Read file (with size limit)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"File too large. Max {MAX_FILE_SIZE // (1024 * 1024)} MB.")

    # Store on disk
    lab_dir = LAB_RESOURCES_ROOT / str(lab_id)
    lab_dir.mkdir(parents=True, exist_ok=True)

    # Unique filename to avoid collisions
    safe_name = f"{uuid_mod.uuid4().hex[:8]}_{original}"
    file_path = lab_dir / safe_name
    file_path.write_bytes(content)

    # Create symlink from original name so agents can import/execute by name
    symlink_path = lab_dir / original
    if not symlink_path.exists():
        try:
            symlink_path.symlink_to(file_path.name)
        except OSError:
            pass

    resource_type = _classify_resource(ext, file.content_type or "")

    # Store metadata in DB
    repo = LabResourceRepository(db)
    resource = await repo.create(
        lab_id=lab_id,
        filename=safe_name,
        original_name=original,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        resource_type=resource_type,
    )
    await db.commit()
    return resource


@router.get("/{lab_id}/resources/{resource_id}/download")
async def download_lab_resource(lab_id: UUID, resource_id: UUID, db: DbSession):
    resource = await LabResourceRepository(db).get_by_id(resource_id)
    if not resource or resource.lab_id != lab_id:
        raise HTTPException(404, "Resource not found")

    file_path = LAB_RESOURCES_ROOT / str(lab_id) / resource.filename
    if not file_path.is_file():
        raise HTTPException(404, "File not found on disk")

    return FileResponse(
        path=str(file_path),
        filename=resource.original_name,
        media_type=resource.content_type,
    )


@router.delete("/{lab_id}/resources/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lab_resource(lab_id: UUID, resource_id: UUID, db: DbSession):
    repo = LabResourceRepository(db)
    resource = await repo.get_by_id(resource_id)
    if not resource or resource.lab_id != lab_id:
        raise HTTPException(404, "Resource not found")

    # Delete file from disk
    file_path = LAB_RESOURCES_ROOT / str(lab_id) / resource.filename
    if file_path.is_file():
        file_path.unlink()

    await repo.delete(resource_id)
    await db.commit()


@router.get("/{lab_id}/resources/{resource_id}/content")
async def read_resource_content(lab_id: UUID, resource_id: UUID, db: DbSession):
    """Read the text content of an uploaded resource (for inline preview)."""
    resource = await LabResourceRepository(db).get_by_id(resource_id)
    if not resource or resource.lab_id != lab_id:
        raise HTTPException(404, "Resource not found")

    file_path = LAB_RESOURCES_ROOT / str(lab_id) / resource.filename
    if not file_path.is_file():
        raise HTTPException(404, "File not found on disk")

    mime = resource.content_type or "application/octet-stream"
    is_text = (
        mime.startswith("text/")
        or mime
        in (
            "application/json",
            "application/javascript",
            "application/xml",
            "application/x-yaml",
            "application/x-sh",
        )
        or file_path.suffix
        in (
            ".md",
            ".py",
            ".js",
            ".ts",
            ".html",
            ".css",
            ".json",
            ".yml",
            ".yaml",
            ".sh",
            ".txt",
            ".csv",
            ".xml",
            ".toml",
            ".cfg",
            ".ini",
            ".log",
        )
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
        "download_url": f"/api/v1/labs/{lab_id}/resources/{resource_id}/download",
    }


# ══════════════════════════════════════════════════
# Output Files (agent-generated)
# ══════════════════════════════════════════════════


@router.get("/{lab_id}/output-files")
async def list_output_files(lab_id: UUID, db: DbSession):
    """List all files in the lab workspace."""
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")

    ws_dir = LAB_RESOURCES_ROOT / str(lab_id)
    if not ws_dir.is_dir():
        return []

    files = []
    for fp in sorted(ws_dir.rglob("*")):
        if not fp.is_file():
            continue
        # Skip temp exec files and internal symlinks
        if fp.name.startswith("_exec_tmp"):
            continue
        rel = fp.relative_to(ws_dir)
        mime, _ = mimetypes.guess_type(fp.name)
        stat = fp.stat()
        files.append(
            {
                "path": str(rel),
                "name": fp.name,
                "size_bytes": stat.st_size,
                "modified_at": stat.st_mtime * 1000,
                "content_type": mime or "application/octet-stream",
            }
        )
    return files


@router.get("/{lab_id}/output-files/download")
async def download_output_file(lab_id: UUID, path: str, db: DbSession):
    """Download a file from the lab workspace."""
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")

    ws_dir = LAB_RESOURCES_ROOT / str(lab_id)

    # Security: prevent path traversal
    try:
        target = (ws_dir / path).resolve()
        if not target.is_relative_to(ws_dir.resolve()):
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


@router.get("/{lab_id}/output-files/content")
async def read_output_file_content(lab_id: UUID, path: str, db: DbSession):
    """Read the text content of a workspace file (for inline preview)."""
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")

    ws_dir = LAB_RESOURCES_ROOT / str(lab_id)
    try:
        target = (ws_dir / path).resolve()
        if not target.is_relative_to(ws_dir.resolve()):
            raise HTTPException(400, "Path traversal denied.")
    except Exception:
        raise HTTPException(400, "Invalid path.")

    if not target.is_file():
        raise HTTPException(404, "File not found")

    is_text, mime = _detect_text(target)
    stat = target.stat()
    is_image = mime.startswith("image/")
    is_audio = mime.startswith("audio/")
    is_video = mime.startswith("video/")

    content = None
    truncated = False
    if is_text:
        try:
            raw = target.read_text(errors="replace")
            if len(raw) > _INLINE_TEXT_MAX_BYTES:
                raw = raw[:_INLINE_TEXT_MAX_BYTES] + "\n... [truncated at 512 KB]"
                truncated = True
            content = raw
        except Exception:
            content = None

    return {
        "path": path,
        "name": target.name,
        "size_bytes": stat.st_size,
        "modified_at": stat.st_mtime * 1000,
        "content_type": mime,
        "is_text": is_text,
        "is_image": is_image,
        "is_audio": is_audio,
        "is_video": is_video,
        # truncated=True means `content` is incomplete; the editor blocks
        # saving so the dropped tail can't be clobbered.
        "truncated": truncated,
        "content": content,
    }


@router.put("/{lab_id}/output-files/content")
async def save_output_file_content(
    lab_id: UUID,
    path: str,
    body: SaveFileContentBody,
    db: DbSession,
    user: dict = Depends(get_current_user),
):
    """Overwrite the text content of an existing workspace file.

    Editing only — the file must already exist; this never creates files
    or directories. Scoped to text files (same allowlist as the inline
    viewer) and gated by EDIT permission on the lab.
    """
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")
    check_permission(user, lab.acl, Permission.EDIT)

    ws_dir = LAB_RESOURCES_ROOT / str(lab_id)
    try:
        target = (ws_dir / path).resolve()
        if not target.is_relative_to(ws_dir.resolve()):
            raise HTTPException(400, "Path traversal denied.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "Invalid path.")

    if not target.is_file():
        raise HTTPException(404, "File not found")
    if target.name.startswith("_exec_tmp"):
        raise HTTPException(400, "Cannot edit internal temp files.")

    is_text, _ = _detect_text(target)
    if not is_text:
        raise HTTPException(415, "Only text files can be edited.")

    if len(body.content.encode("utf-8")) > _INLINE_TEXT_MAX_BYTES:
        raise HTTPException(413, "File too large to save from the editor (max 512 KB).")

    try:
        target.write_text(body.content)
    except Exception as e:
        raise HTTPException(500, f"Failed to write file: {e}")

    stat = target.stat()

    # Record the edit in the file-history feed, mirroring agent file_events
    # so the viewer's History panel shows manual edits too. Best-effort.
    norm_path = path if path.startswith("output/") else f"output/{path}"
    try:
        await LabMessageRepository(db).create(
            lab_id=lab_id,
            iteration=lab.current_iteration,
            sender_type="user",
            sender_name=(user.get("email") or user.get("sub") or "user"),
            content=f"File edited: **{norm_path}** ({stat.st_size} bytes)",
            message_type="file_event",
            extra={"file_path": norm_path, "file_action": "edited"},
        )
    except Exception:
        pass

    return {
        "path": path,
        "name": target.name,
        "size_bytes": stat.st_size,
        "modified_at": stat.st_mtime * 1000,
    }


@router.get("/{lab_id}/output-files/history")
async def get_output_file_history(lab_id: UUID, path: str, db: DbSession):
    """Get creation/modification history for an output file from lab messages."""
    lab = await LabRepository(db).get_by_id(lab_id)
    if not lab:
        raise HTTPException(404, "Lab not found")

    from sqlalchemy import select

    from app.models.orchestrator import LabMessage

    # Query all file_event messages for this lab
    stmt = (
        select(LabMessage)
        .where(LabMessage.lab_id == lab_id, LabMessage.message_type == "file_event")
        .order_by(LabMessage.created_at)
    )
    result = await db.execute(stmt)
    all_events = result.scalars().all()

    # Normalise the requested path: ensure it starts with "output/"
    norm_path = path if path.startswith("output/") else f"output/{path}"

    history = []
    for msg in all_events:
        # Try structured extra first, then parse content string
        extra = msg.extra or {}
        file_path = extra.get("file_path", "")
        file_action = extra.get("file_action", "")

        if not file_path:
            # Parse from content: "File created: **output/report.md** (1234 bytes)"
            m = _re.search(r"File (\w+): \*\*(.+?)\*\*", msg.content or "")
            if m:
                file_action = m.group(1)
                file_path = m.group(2)

        if not file_path:
            continue

        norm_event_path = file_path if file_path.startswith("output/") else f"output/{file_path}"
        if norm_event_path != norm_path:
            continue

        history.append(
            {
                "action": file_action,
                "agent_name": msg.sender_name or msg.sender_type,
                "timestamp": msg.created_at.isoformat() if msg.created_at else None,
                "iteration": msg.iteration,
            }
        )

    return history
