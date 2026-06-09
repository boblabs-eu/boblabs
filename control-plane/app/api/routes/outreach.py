"""Outreach approval queue.

Drafts are physical files in any lab workspace at ``output/drafts/*.md`` with a
YAML frontmatter (to/subject/from_name/...). This module surfaces them as a
single approval queue across all labs/agent instances, lets the operator
edit/approve/reject, and uses the configured mail tool's SMTP to actually send.

Why files (not a new DB table): drafts are produced by sandbox tools that can
only write to the lab workspace. Keeping the queue file-backed means any agent
that writes the right file shape participates automatically — no schema, no
migration, no special tool.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from uuid import UUID

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.dependencies import DbSession, get_current_user
from app.api.routes.labs import LAB_RESOURCES_ROOT
from app.models.orchestrator import Lab, ToolConfig
from app.repositories.lab_repo import LabRepository
from app.services.authorization import Permission, check_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/outreach", tags=["outreach"])

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _parse_draft(path: Path) -> dict | None:
    """Parse a draft file. Returns None if invalid.

    YAML safe_load auto-parses ISO-8601 timestamps into ``datetime`` objects,
    which break the Pydantic ``str | None`` schemas in this module. Coerce
    everything that isn't a primitive string/int back to its string repr so
    the queue keeps working regardless of how the upstream agent serialized
    the frontmatter.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    for k, v in list(meta.items()):
        if v is None or isinstance(v, (str, int, float, bool)):
            continue
        meta[k] = str(v)
    body = m.group(2).strip()
    return {"meta": meta, "body": body}


def _serialize_draft(meta: dict, body: str) -> str:
    fm = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{fm}\n---\n\n{body.strip()}\n"


def _draft_status(path: Path) -> str:
    """Status from path location: pending|sent|rejected."""
    parts = path.parts
    if "sent" in parts:
        return "sent"
    if "rejected" in parts:
        return "rejected"
    return "pending"


def _draft_id(lab_id: UUID, path: Path) -> str:
    """Stable id = '<lab_uuid>/<filename>' (no path traversal possible)."""
    return f"{lab_id}/{path.name}"


def _resolve_draft_path(lab_id: UUID, filename: str) -> Path:
    """Resolve a draft filename for a lab, with strict path-traversal protection."""
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    base = LAB_RESOURCES_ROOT / str(lab_id) / "output" / "drafts"
    # The file may be in pending (root) or in sent/ or rejected/
    for candidate in (base / filename, base / "sent" / filename, base / "rejected" / filename):
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError):
            continue
        try:
            resolved.relative_to(base.resolve())
        except ValueError:
            continue
        if resolved.is_file():
            return resolved
    raise HTTPException(status_code=404, detail="Draft not found")


async def _lab_name_map(db) -> dict[str, str]:
    rows = (await db.execute(select(Lab.id, Lab.name))).all()
    return {str(r[0]): r[1] for r in rows}


async def _accessible_lab_ids(db, user: dict) -> set[str] | None:
    """Cluster O.2 — return the set of lab UUIDs (as strings) the caller
    can VIEW, or ``None`` for admin (no filtering).

    Used by ``list_drafts`` to scope the cross-lab directory iteration to
    labs whose ``Lab.acl`` grants the caller view rights. Mirrors the
    `list_workflows` pattern from cluster F.
    """
    if user.get("role") == "admin":
        return None
    labs = await LabRepository(db).get_all(user=user)
    return {str(l.id) for l in labs}


async def _require_lab_permission(
    db,
    lab_id: UUID,
    user: dict,
    permission: Permission,
) -> Lab:
    """Cluster O.2 — fetch a lab by id and assert the caller has ``permission``
    on its ACL. Returns 404 if the lab doesn't exist (don't leak existence),
    raises 403 via :func:`check_permission` on insufficient permissions.
    Returns the loaded Lab so callers can use its fields (e.g., name).
    """
    lab = await LabRepository(db).get_by_id(lab_id)
    if lab is None:
        raise HTTPException(status_code=404, detail="Lab not found")
    check_permission(user, lab.acl, permission)
    return lab


# ── Schemas ──────────────────────────────────────────────────────────────────


class DraftSummary(BaseModel):
    id: str
    lab_id: str
    lab_name: str
    filename: str
    status: str
    to: str | None = None
    subject: str | None = None
    from_name: str | None = None
    company: str | None = None
    confidence: int | None = None
    generated_at: str | None = None


class DraftDetail(DraftSummary):
    body: str
    evidence_url: str | None = None


class DraftUpdate(BaseModel):
    to: str | None = None
    subject: str | None = None
    body: str | None = None


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("/drafts", response_model=list[DraftSummary])
async def list_drafts(
    db: DbSession,
    user: dict = Depends(get_current_user),
    status_filter: str = "pending",
):
    """List all outreach drafts across all lab workspaces.

    status_filter: 'pending' (default), 'sent', 'rejected', or 'all'.
    """
    if not LAB_RESOURCES_ROOT.exists():
        return []

    # Cluster O.2 — non-admin callers only see drafts for labs whose ACL
    # grants them VIEW. Admin sees everything (allowed_lab_ids is None).
    allowed_lab_ids = await _accessible_lab_ids(db, user)
    name_map = await _lab_name_map(db)
    out: list[DraftSummary] = []

    for lab_dir in LAB_RESOURCES_ROOT.iterdir():
        if not lab_dir.is_dir():
            continue
        lab_id = lab_dir.name
        if allowed_lab_ids is not None and lab_id not in allowed_lab_ids:
            continue
        lab_name = name_map.get(lab_id, lab_id)
        drafts_dir = lab_dir / "output" / "drafts"
        if not drafts_dir.is_dir():
            continue

        for sub in (drafts_dir, drafts_dir / "sent", drafts_dir / "rejected"):
            if not sub.is_dir():
                continue
            st = _draft_status(sub)
            if status_filter != "all" and st != status_filter:
                continue
            for path in sub.glob("*.md"):
                parsed = _parse_draft(path)
                if not parsed:
                    continue
                meta = parsed["meta"]
                out.append(
                    DraftSummary(
                        id=_draft_id(UUID(lab_id), path),
                        lab_id=lab_id,
                        lab_name=lab_name,
                        filename=path.name,
                        status=st,
                        to=meta.get("to"),
                        subject=meta.get("subject"),
                        from_name=meta.get("from_name"),
                        company=meta.get("company"),
                        confidence=meta.get("confidence"),
                        generated_at=meta.get("generated_at"),
                    )
                )

    out.sort(key=lambda d: (d.status != "pending", d.generated_at or ""), reverse=False)
    return out


@router.get("/drafts/{lab_id}/{filename}", response_model=DraftDetail)
async def get_draft(
    lab_id: UUID,
    filename: str,
    db: DbSession,
    user: dict = Depends(get_current_user),
):
    # Cluster O.2 — VIEW permission on the parent lab required.
    await _require_lab_permission(db, lab_id, user, Permission.VIEW)
    path = _resolve_draft_path(lab_id, filename)
    parsed = _parse_draft(path)
    if not parsed:
        raise HTTPException(status_code=400, detail="Draft is not parseable")
    meta = parsed["meta"]
    name_map = await _lab_name_map(db)
    return DraftDetail(
        id=_draft_id(lab_id, path),
        lab_id=str(lab_id),
        lab_name=name_map.get(str(lab_id), str(lab_id)),
        filename=path.name,
        status=_draft_status(path),
        to=meta.get("to"),
        subject=meta.get("subject"),
        from_name=meta.get("from_name"),
        company=meta.get("company"),
        confidence=meta.get("confidence"),
        generated_at=meta.get("generated_at"),
        evidence_url=meta.get("evidence_url"),
        body=parsed["body"],
    )


@router.patch("/drafts/{lab_id}/{filename}", response_model=DraftDetail)
async def edit_draft(
    lab_id: UUID,
    filename: str,
    data: DraftUpdate,
    db: DbSession,
    user: dict = Depends(get_current_user),
):
    """Edit a pending draft. Sent/rejected drafts are immutable."""
    # Cluster O.2 — EDIT permission on the parent lab required.
    await _require_lab_permission(db, lab_id, user, Permission.EDIT)
    path = _resolve_draft_path(lab_id, filename)
    if _draft_status(path) != "pending":
        raise HTTPException(status_code=409, detail="Only pending drafts are editable")
    parsed = _parse_draft(path)
    if not parsed:
        raise HTTPException(status_code=400, detail="Draft is not parseable")
    meta = parsed["meta"]
    body = parsed["body"]
    if data.to is not None:
        meta["to"] = data.to.strip()
    if data.subject is not None:
        meta["subject"] = data.subject.strip()
    if data.body is not None:
        body = data.body
    path.write_text(_serialize_draft(meta, body), encoding="utf-8")
    return await get_draft(lab_id, filename, db, user)  # type: ignore[arg-type]


@router.post("/drafts/{lab_id}/{filename}/reject")
async def reject_draft(
    lab_id: UUID,
    filename: str,
    db: DbSession,
    user: dict = Depends(get_current_user),
):
    """Move a pending draft to the rejected folder. Append the recipient to
    suppression.txt so the Lab won't redraft them."""
    # Cluster O.2 — EDIT permission on the parent lab required (reject
    # mutates the lab's suppression list, a write).
    await _require_lab_permission(db, lab_id, user, Permission.EDIT)
    path = _resolve_draft_path(lab_id, filename)
    if _draft_status(path) != "pending":
        raise HTTPException(status_code=409, detail="Only pending drafts can be rejected")

    parsed = _parse_draft(path)
    rejected_dir = path.parent / "rejected"
    rejected_dir.mkdir(exist_ok=True)
    new_path = rejected_dir / path.name
    path.rename(new_path)

    # Suppression list
    if parsed and parsed["meta"].get("to"):
        sup = path.parent.parent / "suppression.txt"
        with sup.open("a", encoding="utf-8") as fh:
            fh.write(parsed["meta"]["to"].strip().lower() + "\n")

    return {"success": True, "status": "rejected", "filename": path.name}


@router.post("/drafts/{lab_id}/{filename}/send")
async def send_draft(
    lab_id: UUID,
    filename: str,
    db: DbSession,
    user: dict = Depends(get_current_user),
):
    """Send the draft via the configured mail tool's SMTP, then move it to sent/."""
    # Cluster O.2 — EDIT permission on the parent lab required (sending
    # the email is a write that touches the lab's outreach history).
    await _require_lab_permission(db, lab_id, user, Permission.EDIT)
    path = _resolve_draft_path(lab_id, filename)
    if _draft_status(path) != "pending":
        raise HTTPException(status_code=409, detail="Only pending drafts can be sent")
    parsed = _parse_draft(path)
    if not parsed:
        raise HTTPException(status_code=400, detail="Draft is not parseable")

    meta = parsed["meta"]
    body = parsed["body"]
    to_addr = (meta.get("to") or "").strip()
    subject = (meta.get("subject") or "").strip()
    if not to_addr or not subject or not body:
        raise HTTPException(status_code=400, detail="Draft missing to/subject/body")

    # Load SMTP config from the mail tool config
    tc = (
        await db.execute(select(ToolConfig).where(ToolConfig.tool_type == "mail"))
    ).scalar_one_or_none()
    if not tc or not tc.config:
        raise HTTPException(
            status_code=412,
            detail="Mail tool not configured. Settings → Tool Configs → Mail.",
        )
    cfg = tc.config
    smtp_host = cfg.get("smtp_host", "")
    smtp_port = int(cfg.get("smtp_port", 587))
    smtp_user = cfg.get("smtp_user", "")
    smtp_password = cfg.get("smtp_password", "")
    smtp_from = cfg.get("smtp_from", "") or smtp_user
    smtp_tls = cfg.get("smtp_tls", True)
    if not smtp_host or not smtp_user:
        raise HTTPException(status_code=412, detail="SMTP host/user not set in Mail config")

    from_name = (meta.get("from_name") or "").strip()
    from_header = f"{from_name} <{smtp_from}>" if from_name else smtp_from

    msg = MIMEMultipart("alternative")
    msg["From"] = from_header
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    import aiosmtplib

    try:
        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_password,
            use_tls=smtp_tls and smtp_port == 465,
            start_tls=smtp_tls and smtp_port != 465,
        )
    except Exception as e:
        logger.warning("outreach: SMTP send failed for %s: %s", to_addr, e)
        raise HTTPException(status_code=502, detail=f"SMTP error: {e}") from e

    # Mark as sent in frontmatter and move to sent/
    meta["status"] = "sent"
    meta["sent_at"] = datetime.now(timezone.utc).isoformat()
    meta["sent_by"] = user.get("sub") or user.get("email") or "unknown"
    path.write_text(_serialize_draft(meta, body), encoding="utf-8")
    sent_dir = path.parent / "sent"
    sent_dir.mkdir(exist_ok=True)
    new_path = sent_dir / path.name
    path.rename(new_path)

    return {"success": True, "status": "sent", "to": to_addr, "filename": path.name}
