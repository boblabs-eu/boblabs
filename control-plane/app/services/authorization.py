"""Bob Manager — Centralized authorization service.

Single reusable module for RBAC checks across all data modules.
Uses JSONB ACL columns on resources for per-resource permissions.
"""

from enum import Enum

from fastapi import Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.database import get_db


class Permission(str, Enum):
    VIEW = "view"
    EDIT = "edit"
    DELETE = "delete"
    MANAGE = "manage"


def get_default_acl(user_email: str) -> dict:
    """Return default ACL for a newly created resource."""
    return {"owner": user_email, "editors": [], "viewers": []}


def check_permission(user: dict, acl: dict | None, permission: Permission) -> None:
    """Raise 403 if user lacks the required permission on a resource.

    Admin role bypasses all checks.
    """
    if user.get("role") == "admin":
        return

    if acl is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    email = user.get("sub", "")

    if acl.get("owner") == email:
        return  # owner has all permissions

    editors = acl.get("editors", [])
    viewers = acl.get("viewers", [])

    if permission == Permission.VIEW:
        if email in editors or email in viewers:
            return
    elif permission == Permission.EDIT:
        if email in editors:
            return
    # DELETE and MANAGE require owner or admin — both already handled above

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


def filter_query_by_access(query, model, user: dict):
    """Add WHERE clause to filter resources the user can see.

    Uses PostgreSQL JSONB operators for SQL-level filtering:
    - acl->>'owner' = email          (is owner)
    - acl->'editors' ? email          (in editors array)
    - acl->'viewers' ? email          (in viewers array)

    Admin role: no filter applied.
    """
    if user.get("role") == "admin":
        return query

    email = user.get("sub", "")
    return query.where(
        or_(
            model.acl["owner"].astext == email,
            model.acl["editors"].contains([email]),
            model.acl["viewers"].contains([email]),
        )
    )


async def require_infra_access(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dependency that checks if user is whitelisted for infrastructure sections.

    Infrastructure sections: servers, workflows, commands, terminal, logs.
    """
    if user.get("role") == "admin":
        return user

    from sqlalchemy import select

    from app.models.platform_settings import PlatformSettings

    result = await db.execute(
        select(PlatformSettings).where(PlatformSettings.key == "infra_access")
    )
    row = result.scalar_one_or_none()
    emails = row.value.get("emails", []) if row else []

    if user.get("sub") not in emails:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="infra_restricted",
        )
    return user
