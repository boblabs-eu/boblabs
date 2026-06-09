"""API routes for tool configuration (SMTP, Twitter API keys, etc.).

All routes are admin-only — these store global integration secrets (SMTP
passwords, social-media OAuth tokens, Postiz keys). Lab users never see
or modify them; bob-api resolves credentials server-side at tool-call
time. See docs/ACCESS_CONTROL.md for the auth model.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.database import get_db
from app.repositories.tool_config_repo import ToolConfigRepository
from app.schemas.orchestrator import ToolConfigUpdate

router = APIRouter(prefix="/tool-configs", tags=["tool-configs"])

DbSession = Depends(get_db)

# Valid tool types and their required/optional config keys
TOOL_CONFIG_SCHEMA = {
    "mail": {
        "required": [],
        "optional": [
            "smtp_host",
            "smtp_port",
            "smtp_user",
            "smtp_password",
            "smtp_from",
            "smtp_tls",
            "imap_host",
            "imap_port",
            "imap_user",
            "imap_password",
            "imap_tls",
        ],
    },
    "twitter": {
        "required": [],
        "optional": [
            "api_key",
            "api_secret",
            "access_token",
            "access_token_secret",
            "bearer_token",
        ],
    },
    "postiz": {
        "required": ["api_url", "api_key"],
        "optional": [],
    },
    "trading": {
        "required": [],
        "optional": [
            "max_tx_usd",
            "allowed_chains",
            "confirmation_mode",
            "gas_multiplier",
            "slippage_bps",
        ],
    },
    # ── Multi-account social platforms ──
    # Each stores: {"accounts": [{account_id, label, ...platform-specific creds}, ...]}
    # Agents never see raw credentials — they reference accounts by account_id only,
    # and the media_post_* tool resolves the credentials server-side at call time.
    "social_x": {
        "required": [],
        "optional": ["accounts"],
        "multi_account": True,
        "account_fields": [
            "api_key",
            "api_secret",
            "access_token",
            "access_token_secret",
            "bearer_token",
        ],
    },
    "social_linkedin": {
        "required": [],
        "optional": ["accounts"],
        "multi_account": True,
        "account_fields": [
            "client_id",
            "client_secret",
            "access_token",
            "person_urn",
            "organization_urn",
        ],
    },
    "social_instagram": {
        "required": [],
        "optional": ["accounts"],
        "multi_account": True,
        "account_fields": [
            "access_token",
            "ig_user_id",
            "fb_page_id",
        ],
    },
    "social_facebook": {
        "required": [],
        "optional": ["accounts"],
        "multi_account": True,
        "account_fields": [
            "page_access_token",
            "page_id",
            "app_id",
            "app_secret",
        ],
    },
}

# Keys that are masked in responses
_SENSITIVE_KEYS = {
    "smtp_password",
    "imap_password",
    "api_secret",
    "access_token_secret",
    "bearer_token",
    "api_key",
    "access_token",
    "client_secret",
    "page_access_token",
    "app_secret",
}


def _mask_value(v):
    if v is None or v == "":
        return v
    s = str(v)
    return "••••••••" if len(s) > 4 else "••••"


def _mask_config(config: dict) -> dict:
    """Mask sensitive values in config for API responses, including nested account lists."""
    masked = {}
    for k, v in config.items():
        if k == "accounts" and isinstance(v, list):
            masked["accounts"] = [
                {
                    ak: (_mask_value(av) if ak in _SENSITIVE_KEYS and av else av)
                    for ak, av in acc.items()
                }
                for acc in v
                if isinstance(acc, dict)
            ]
        elif k in _SENSITIVE_KEYS and v:
            masked[k] = _mask_value(v)
        else:
            masked[k] = v
    return masked


def _merge_preserving_masked_secrets(new_config: dict, existing_config: dict) -> dict:
    """If incoming config carries masked sensitive values, restore them from existing."""
    merged = dict(new_config)
    if "accounts" in merged and isinstance(merged["accounts"], list):
        existing_by_id = {
            a.get("account_id"): a
            for a in (existing_config.get("accounts") or [])
            if isinstance(a, dict)
        }
        new_accounts = []
        for acc in merged["accounts"]:
            if not isinstance(acc, dict):
                continue
            existing_acc = existing_by_id.get(acc.get("account_id"), {})
            for key in _SENSITIVE_KEYS:
                if key in acc and isinstance(acc[key], str) and acc[key].startswith("••"):
                    acc[key] = existing_acc.get(key, "")
            new_accounts.append(acc)
        merged["accounts"] = new_accounts
    else:
        for key in _SENSITIVE_KEYS:
            if key in merged and isinstance(merged[key], str) and merged[key].startswith("••"):
                merged[key] = existing_config.get(key, "")
    return merged


@router.get("")
async def list_tool_configs(db: AsyncSession = DbSession, _user: dict = Depends(require_admin)):
    repo = ToolConfigRepository(db)
    configs = await repo.list_all()
    result = []
    for tc in configs:
        result.append(
            {
                "id": str(tc.id),
                "tool_type": tc.tool_type,
                "config": _mask_config(tc.config),
                "created_at": tc.created_at.isoformat() if tc.created_at else None,
                "updated_at": tc.updated_at.isoformat() if tc.updated_at else None,
            }
        )
    return result


@router.get("/schema")
async def get_tool_config_schema(_user: dict = Depends(require_admin)):
    """Return the expected config schema for each tool type."""
    return TOOL_CONFIG_SCHEMA


@router.get("/{tool_type}")
async def get_tool_config(
    tool_type: str, db: AsyncSession = DbSession, _user: dict = Depends(require_admin)
):
    repo = ToolConfigRepository(db)
    tc = await repo.get_by_tool_type(tool_type)
    if not tc:
        return {"tool_type": tool_type, "config": {}, "configured": False}
    return {
        "id": str(tc.id),
        "tool_type": tc.tool_type,
        "config": _mask_config(tc.config),
        "configured": True,
        "created_at": tc.created_at.isoformat() if tc.created_at else None,
        "updated_at": tc.updated_at.isoformat() if tc.updated_at else None,
    }


@router.put("/{tool_type}")
async def upsert_tool_config(
    tool_type: str,
    body: ToolConfigUpdate,
    db: AsyncSession = DbSession,
    _user: dict = Depends(require_admin),
):
    if tool_type not in TOOL_CONFIG_SCHEMA:
        raise HTTPException(
            400, f"Unknown tool type: {tool_type}. Valid: {', '.join(TOOL_CONFIG_SCHEMA)}"
        )

    # If a masked value is sent back, preserve the existing value
    repo = ToolConfigRepository(db)
    existing = await repo.get_by_tool_type(tool_type)
    config = _merge_preserving_masked_secrets(
        dict(body.config), existing.config if existing else {}
    )

    tc = await repo.upsert(tool_type, config)
    await db.commit()
    return {
        "id": str(tc.id),
        "tool_type": tc.tool_type,
        "config": _mask_config(tc.config),
        "configured": True,
    }


@router.get("/{tool_type}/accounts")
async def list_tool_config_accounts(
    tool_type: str, db: AsyncSession = DbSession, _user: dict = Depends(require_admin)
):
    """Return account_id + label for multi-account tool types (no credentials).

    Used by the lab editor to populate per-agent account pickers when the
    agent is granted a media_post_* tool.
    """
    if tool_type not in TOOL_CONFIG_SCHEMA or not TOOL_CONFIG_SCHEMA[tool_type].get(
        "multi_account"
    ):
        raise HTTPException(400, f"Tool type '{tool_type}' is not multi-account.")
    repo = ToolConfigRepository(db)
    tc = await repo.get_by_tool_type(tool_type)
    if not tc:
        return []
    accounts = tc.config.get("accounts") or []
    return [
        {"account_id": a.get("account_id"), "label": a.get("label") or a.get("account_id")}
        for a in accounts
        if isinstance(a, dict) and a.get("account_id")
    ]


@router.delete("/{tool_type}")
async def delete_tool_config(
    tool_type: str, db: AsyncSession = DbSession, _user: dict = Depends(require_admin)
):
    repo = ToolConfigRepository(db)
    deleted = await repo.delete(tool_type)
    if not deleted:
        raise HTTPException(404, f"No config for tool type: {tool_type}")
    await db.commit()
    return {"deleted": True}
