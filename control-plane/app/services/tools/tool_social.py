"""Unified social-media posting tool.

Single ``media_post`` tool that dispatches to a per-platform handler via its
``platform`` argument (x, linkedin, instagram, facebook). Credentials are
NEVER held by agents — they are resolved server-side from the matching
``social_<platform>`` tool config using the ``account_id`` argument.

Until real API keys are wired by the operator, every platform adapter runs
in ``dry_run`` mode and returns a synthetic post id without touching the
network.

Sub-tool selection (e.g. ``media_post:x``) is enforced by the same
expandable-tool pattern used for ``trading``, ``mail``, ``twitter``, etc.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.social_publishers import publish

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)


_PLATFORMS = ("x", "linkedin", "instagram", "facebook")


TOOLS = {
    "media_post": {
        "description": (
            "Publish a post to a configured social-media account. "
            "Supports X (Twitter), LinkedIn, Instagram, Facebook. "
            "Credentials are resolved server-side from the matching "
            "`social_<platform>` tool config; the agent only references an "
            "account by `account_id`. The lab admin selects which platforms "
            "the agent is allowed to post to via sub-tool checkboxes "
            "(e.g. media_post:x). Use `action=list_accounts` to discover "
            "configured accounts before posting."
        ),
        "sensitive": True,
        "sensitive_reason": (
            "Publishes content to a real public social-media account. "
            "Posts are visible to a public audience and may be hard to retract."
        ),
        "parameters": {
            "platform": {
                "type": "string",
                "description": (
                    f"Target platform. One of: {', '.join(_PLATFORMS)}. "
                    "Must be allowed by sub-tool selection (e.g. media_post:x)."
                ),
                "required": True,
            },
            "account_id": {
                "type": "string",
                "description": (
                    "The configured account to post from. Run with "
                    "`action=list_accounts` and the same `platform` to list "
                    "available account ids."
                ),
                "required": False,
            },
            "content": {
                "type": "string",
                "description": "The post body text (required when action='post').",
                "required": False,
            },
            "media_urls": {
                "type": "string",
                "description": "Optional comma-separated media URLs to attach.",
                "required": False,
            },
            "action": {
                "type": "string",
                "description": "'post' (default) or 'list_accounts'.",
                "required": False,
            },
        },
    },
}


# ── Helpers ───────────────────────────────────────

async def _load_accounts(executor: "ToolExecutor", platform: str) -> list[dict]:
    from sqlalchemy import select
    from app.models.orchestrator import ToolConfig

    tool_type = f"social_{platform}"
    result = await executor.db.execute(
        select(ToolConfig).where(ToolConfig.tool_type == tool_type)
    )
    tc = result.scalar_one_or_none()
    if not tc or not tc.config:
        return []
    accounts = tc.config.get("accounts") or []
    return [a for a in accounts if isinstance(a, dict) and a.get("account_id")]


def _summarize_accounts(accounts: list[dict]) -> str:
    if not accounts:
        return "(no accounts configured)"
    return ", ".join(
        f"{a['account_id']}{' — ' + a['label'] if a.get('label') else ''}"
        for a in accounts
    )


def _platform_allowed(executor: "ToolExecutor", platform: str) -> bool:
    """Check that the agent's tool grant includes this platform.

    Acceptable forms:
      - bare ``media_post`` (legacy / all-platforms)
      - ``media_post:<platform>`` (preferred, explicit sub-tool grant)
    """
    granted = getattr(executor, "granted_tools", None)
    if not granted:
        return True
    needle = f"media_post:{platform}"
    return needle in granted or "media_post" in granted


# ── Handler ───────────────────────────────────────

async def media_post(executor: "ToolExecutor", args: dict) -> dict:
    platform = (args.get("platform") or "").strip().lower()
    if platform not in _PLATFORMS:
        return {
            "success": False,
            "output": (
                f"Missing or invalid 'platform'. Must be one of: {', '.join(_PLATFORMS)}."
            ),
        }

    if not _platform_allowed(executor, platform):
        return {
            "success": False,
            "output": (
                f"Platform '{platform}' is not allowed for this agent. "
                f"Ask the lab admin to enable media_post:{platform} in the agent's tool grants."
            ),
        }

    action = (args.get("action") or "post").strip().lower()
    accounts = await _load_accounts(executor, platform)

    if action == "list_accounts":
        return {
            "success": True,
            "output": f"Configured {platform} accounts: {_summarize_accounts(accounts)}",
            "accounts": [
                {"account_id": a["account_id"], "label": a.get("label", "")}
                for a in accounts
            ],
        }

    account_id = (args.get("account_id") or "").strip()
    if not account_id:
        return {"success": False, "output": "Missing required 'account_id'."}

    account = next((a for a in accounts if a.get("account_id") == account_id), None)
    if account is None:
        return {
            "success": False,
            "output": (
                f"No {platform} account configured with account_id='{account_id}'. "
                f"Available: {_summarize_accounts(accounts)}"
            ),
        }

    content = (args.get("content") or "").strip()
    if not content:
        return {"success": False, "output": "Missing required 'content'."}

    media_raw = args.get("media_urls") or ""
    media_urls = [u.strip() for u in media_raw.split(",") if u.strip()] if media_raw else []

    result = await publish(
        platform=platform,
        account=account,
        content=content,
        media_urls=media_urls,
    )
    posted_id = result.get("posted_id", "")
    dry_run = result.get("dry_run", False)
    msg = (
        f"[{platform.upper()}] {'DRY-RUN' if dry_run else 'POSTED'} as account "
        f"'{account_id}' — id={posted_id or 'n/a'}."
    )
    if not result.get("success", True):
        return {"success": False, "output": msg + f" Error: {result.get('error', 'unknown')}"}
    return {"success": True, "output": msg, **result}


HANDLERS = {
    "media_post": media_post,
}
