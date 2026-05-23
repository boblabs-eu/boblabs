"""Postiz integration tool: schedule and manage social media posts via Postiz Public API."""

from __future__ import annotations

import json
import logging
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

TOOLS = {
    "postiz": {
        "description": (
            "Social media scheduling and management via Postiz. "
            "Actions: list_integrations (show connected social accounts), "
            "get_settings (get platform limits/fields for an integration), "
            "trigger_tool (fetch dynamic data like Reddit flairs, YouTube playlists, etc.), "
            "create_post (schedule a post to one or more platforms), "
            "list_posts (list scheduled/draft posts), "
            "delete_post (delete a post by ID), "
            "change_status (switch post between draft and schedule), "
            "upload_media (upload a file from workspace — required before posting media), "
            "get_analytics (platform-level analytics), "
            "get_post_analytics (single post analytics)."
        ),
        "parameters": {
            "action": {
                "type": "string",
                "description": (
                    "Action to perform: list_integrations, get_settings, trigger_tool, "
                    "create_post, list_posts, delete_post, change_status, "
                    "upload_media, get_analytics, get_post_analytics"
                ),
                "required": True,
            },
            "integration_ids": {
                "type": "string",
                "description": "Comma-separated integration IDs (for create_post, get_settings, trigger_tool, get_analytics)",
                "required": False,
            },
            "content": {
                "type": "string",
                "description": "Post content text (for create_post). Use JSON array of strings for threads/comments.",
                "required": False,
            },
            "date": {
                "type": "string",
                "description": "Schedule date in ISO 8601 format, e.g. 2024-12-31T12:00:00Z (for create_post, required)",
                "required": False,
            },
            "post_type": {
                "type": "string",
                "description": "Post type: schedule or draft (default: schedule, for create_post)",
                "required": False,
            },
            "media_urls": {
                "type": "string",
                "description": "Comma-separated media URLs (from upload_media) to attach (for create_post)",
                "required": False,
            },
            "settings": {
                "type": "string",
                "description": "Platform-specific settings as JSON string (for create_post — e.g. subreddit, title, privacy)",
                "required": False,
            },
            "post_id": {
                "type": "string",
                "description": "Post ID (for delete_post, change_status, get_post_analytics)",
                "required": False,
            },
            "status": {
                "type": "string",
                "description": "New status: draft or schedule (for change_status)",
                "required": False,
            },
            "file_path": {
                "type": "string",
                "description": "Workspace-relative file path to upload (for upload_media)",
                "required": False,
            },
            "method_name": {
                "type": "string",
                "description": "Integration tool method to trigger (for trigger_tool — e.g. getFlairs, getPlaylists, getChannels)",
                "required": False,
            },
            "method_data": {
                "type": "string",
                "description": "JSON data to pass to the triggered method (for trigger_tool)",
                "required": False,
            },
            "days": {
                "type": "integer",
                "description": "Number of days to look back for analytics (default: 7)",
                "required": False,
            },
            "start_date": {
                "type": "string",
                "description": "Start date filter for list_posts (ISO 8601)",
                "required": False,
            },
            "end_date": {
                "type": "string",
                "description": "End date filter for list_posts (ISO 8601)",
                "required": False,
            },
        },
    },
}


# ── Helpers ───────────────────────────────────

async def _get_postiz_config(executor: ToolExecutor) -> dict | None:
    """Load Postiz API config from ToolConfig table."""
    from sqlalchemy import select
    from app.models.orchestrator import ToolConfig

    result = await executor.db.execute(
        select(ToolConfig).where(ToolConfig.tool_type == "postiz")
    )
    tc = result.scalar_one_or_none()
    if not tc or not tc.config:
        return None
    return tc.config


def _postiz_headers(api_key: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": api_key,
    }


def _fail(msg: str) -> dict:
    return {"success": False, "output": msg}


def _ok(msg: str) -> dict:
    return {"success": True, "output": msg}


async def _postiz_request(
    method: str,
    url: str,
    api_key: str,
    *,
    json_body: dict | None = None,
    timeout: float = 30.0,
) -> tuple[bool, dict | str]:
    """Make an HTTP request to Postiz API. Returns (ok, data_or_error)."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            kwargs: dict = {"headers": _postiz_headers(api_key)}
            if json_body is not None:
                kwargs["json"] = json_body

            resp = await client.request(method, url, **kwargs)

            if not resp.is_success:
                try:
                    err = resp.json()
                except Exception:
                    err = resp.text
                return False, f"Postiz API error ({resp.status_code}): {err}"

            return True, resp.json()
    except httpx.TimeoutException:
        return False, "Postiz API request timed out."
    except Exception as e:
        return False, f"Postiz API request failed: {e}"


# ── Main dispatcher ──────────────────────────

async def postiz(executor: ToolExecutor, args: dict) -> dict:
    """Postiz tool: social media scheduling via Postiz Public API."""
    action = (args.get("action") or "").strip().lower()
    if not action:
        return _fail(
            "postiz requires 'action'. Available: list_integrations, get_settings, "
            "trigger_tool, create_post, list_posts, delete_post, change_status, "
            "upload_media, get_analytics, get_post_analytics"
        )

    allowed = executor._subtool_permissions.get("postiz", [])
    if allowed and action not in allowed:
        return _fail(f"Action '{action}' not permitted. Allowed: {', '.join(allowed)}")

    cfg = await _get_postiz_config(executor)
    if not cfg:
        return _fail("Postiz not configured. Ask the admin to set up API URL and key in Settings → Tool Configs → Postiz.")

    api_url = (cfg.get("api_url") or "").rstrip("/")
    api_key = cfg.get("api_key") or ""

    if not api_url or not api_key:
        return _fail("Postiz config incomplete — need api_url and api_key in Settings → Tool Configs → Postiz.")

    base = f"{api_url}/public/v1"

    dispatch = {
        "list_integrations": _list_integrations,
        "get_settings": _get_settings,
        "trigger_tool": _trigger_tool,
        "create_post": _create_post,
        "list_posts": _list_posts,
        "delete_post": _delete_post,
        "change_status": _change_status,
        "upload_media": _upload_media,
        "get_analytics": _get_analytics,
        "get_post_analytics": _get_post_analytics,
    }

    handler = dispatch.get(action)
    if not handler:
        return _fail(f"Unknown postiz action: {action}. Available: {', '.join(dispatch)}")

    return await handler(executor, args, base, api_key)


# ── Actions ───────────────────────────────────

async def _list_integrations(
    executor: ToolExecutor, args: dict, base: str, api_key: str
) -> dict:
    ok, data = await _postiz_request("GET", f"{base}/integrations", api_key)
    if not ok:
        return _fail(str(data))

    if not data:
        return _ok("No integrations connected. Connect social accounts in the Postiz web UI first.")

    lines = [f"Found {len(data)} integration(s):\n"]
    for i, intg in enumerate(data, 1):
        name = intg.get("name", "?")
        provider = intg.get("providerIdentifier") or intg.get("identifier") or intg.get("provider", "?")
        intg_id = intg.get("id", "?")
        lines.append(f"{i}. {name} ({provider}) — id: {intg_id}")
    return _ok("\n".join(lines))


async def _get_settings(
    executor: ToolExecutor, args: dict, base: str, api_key: str
) -> dict:
    integration_id = (args.get("integration_ids") or "").strip()
    if not integration_id:
        return _fail("get_settings requires 'integration_ids' (single integration ID)")

    # Take the first ID if multiple provided
    integration_id = integration_id.split(",")[0].strip()

    ok, data = await _postiz_request("GET", f"{base}/integration-settings/{integration_id}", api_key)
    if not ok:
        return _fail(str(data))

    return _ok(json.dumps(data, indent=2))


async def _trigger_tool(
    executor: ToolExecutor, args: dict, base: str, api_key: str
) -> dict:
    integration_id = (args.get("integration_ids") or "").strip()
    if not integration_id:
        return _fail("trigger_tool requires 'integration_ids' (single integration ID)")
    integration_id = integration_id.split(",")[0].strip()

    method_name = (args.get("method_name") or "").strip()
    if not method_name:
        return _fail("trigger_tool requires 'method_name' (e.g. getFlairs, getPlaylists, getChannels)")

    method_data: dict = {}
    raw_data = (args.get("method_data") or "").strip()
    if raw_data:
        try:
            method_data = json.loads(raw_data)
        except json.JSONDecodeError:
            return _fail(f"Invalid JSON in method_data: {raw_data}")

    ok, data = await _postiz_request(
        "POST",
        f"{base}/integration-trigger/{integration_id}",
        api_key,
        json_body={"methodName": method_name, "data": method_data},
    )
    if not ok:
        return _fail(str(data))

    return _ok(json.dumps(data, indent=2))


async def _create_post(
    executor: ToolExecutor, args: dict, base: str, api_key: str
) -> dict:
    integration_ids = (args.get("integration_ids") or "").strip()
    if not integration_ids:
        return _fail("create_post requires 'integration_ids' (comma-separated)")

    date = (args.get("date") or "").strip()
    if not date:
        return _fail("create_post requires 'date' (ISO 8601 schedule date, e.g. 2024-12-31T12:00:00Z)")

    content_raw = (args.get("content") or "").strip()
    if not content_raw:
        return _fail("create_post requires 'content' (post text)")

    post_type = (args.get("post_type") or "schedule").strip().lower()
    media_urls_raw = (args.get("media_urls") or "").strip()

    # Build posts array — support single string or JSON array for threads
    try:
        content_list = json.loads(content_raw)
        if not isinstance(content_list, list):
            content_list = [content_raw]
    except (json.JSONDecodeError, TypeError):
        content_list = [content_raw]

    media_list = [u.strip() for u in media_urls_raw.split(",") if u.strip()] if media_urls_raw else []

    # Build post body
    ids = [i.strip() for i in integration_ids.split(",") if i.strip()]
    posts = []
    for idx, text in enumerate(content_list):
        post_item: dict = {"content": text}
        # Attach media to corresponding post part (first media to first post, etc.)
        if idx < len(media_list):
            post_item["image"] = [media_list[idx]]
        posts.append(post_item)

    body: dict = {
        "integrations": ids,
        "posts": [{"post": posts}],
        "date": date,
        "type": post_type,
    }

    # Platform-specific settings
    settings_raw = (args.get("settings") or "").strip()
    if settings_raw:
        try:
            body["settings"] = json.loads(settings_raw)
        except json.JSONDecodeError:
            return _fail(f"Invalid JSON in settings: {settings_raw}")

    ok, data = await _postiz_request("POST", f"{base}/posts", api_key, json_body=body)
    if not ok:
        return _fail(str(data))

    post_id = data.get("id") or data.get("postId") or "unknown"
    return _ok(f"Post created (id: {post_id}, type: {post_type}, date: {date}, integrations: {', '.join(ids)})")


async def _list_posts(
    executor: ToolExecutor, args: dict, base: str, api_key: str
) -> dict:
    params: dict = {}
    if args.get("start_date"):
        params["startDate"] = args["start_date"]
    if args.get("end_date"):
        params["endDate"] = args["end_date"]

    qs = "&".join(f"{k}={v}" for k, v in params.items()) if params else ""
    url = f"{base}/posts?{qs}" if qs else f"{base}/posts"

    ok, data = await _postiz_request("GET", url, api_key)
    if not ok:
        return _fail(str(data))

    if not data:
        return _ok("No posts found.")

    posts = data if isinstance(data, list) else data.get("posts", data.get("data", []))
    lines = [f"Found {len(posts)} post(s):\n"]
    for i, p in enumerate(posts, 1):
        pid = p.get("id", "?")
        status = p.get("state") or p.get("status") or p.get("type", "?")
        date = p.get("publishDate") or p.get("date", "?")
        content_preview = ""
        post_items = p.get("posts") or p.get("post") or []
        if post_items and isinstance(post_items, list) and len(post_items) > 0:
            first = post_items[0] if isinstance(post_items[0], dict) else {}
            content_preview = (first.get("content") or "")[:80]
        lines.append(f"{i}. [{status}] {date} — {content_preview}... (id: {pid})")
    return _ok("\n".join(lines))


async def _delete_post(
    executor: ToolExecutor, args: dict, base: str, api_key: str
) -> dict:
    post_id = (args.get("post_id") or "").strip()
    if not post_id:
        return _fail("delete_post requires 'post_id'")

    ok, data = await _postiz_request("DELETE", f"{base}/posts/{post_id}", api_key)
    if not ok:
        return _fail(str(data))

    return _ok(f"Post {post_id} deleted.")


async def _change_status(
    executor: ToolExecutor, args: dict, base: str, api_key: str
) -> dict:
    post_id = (args.get("post_id") or "").strip()
    if not post_id:
        return _fail("change_status requires 'post_id'")

    status = (args.get("status") or "").strip().lower()
    if status not in ("draft", "schedule"):
        return _fail("change_status requires 'status' (draft or schedule)")

    ok, data = await _postiz_request(
        "PUT", f"{base}/posts/{post_id}/status", api_key, json_body={"status": status}
    )
    if not ok:
        return _fail(str(data))

    return _ok(f"Post {post_id} status changed to '{status}'.")


async def _upload_media(
    executor: ToolExecutor, args: dict, base: str, api_key: str
) -> dict:
    file_path = (args.get("file_path") or "").strip()
    if not file_path:
        return _fail("upload_media requires 'file_path' (workspace-relative path)")

    from app.services.tool_executor import LAB_RESOURCES_ROOT

    workspace = LAB_RESOURCES_ROOT / str(executor.lab_id)
    full_path = (workspace / file_path).resolve()

    # Security: ensure path stays within workspace
    if not str(full_path).startswith(str(workspace.resolve())):
        return _fail("File path must be within the lab workspace.")

    if not full_path.is_file():
        return _fail(f"File not found: {file_path}")

    mime_type, _ = mimetypes.guess_type(str(full_path))
    if not mime_type:
        mime_type = "application/octet-stream"

    try:
        file_bytes = full_path.read_bytes()
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{base}/upload",
                headers={"Authorization": api_key},
                files={"file": (full_path.name, file_bytes, mime_type)},
            )
            if not resp.is_success:
                try:
                    err = resp.json()
                except Exception:
                    err = resp.text
                return _fail(f"Upload failed ({resp.status_code}): {err}")

            data = resp.json()
    except httpx.TimeoutException:
        return _fail("Media upload timed out.")
    except Exception as e:
        return _fail(f"Upload error: {e}")

    url = data.get("path") or data.get("url") or json.dumps(data)
    return _ok(f"Uploaded: {file_path}\nURL: {url}\nUse this URL in create_post media_urls parameter.")


async def _get_analytics(
    executor: ToolExecutor, args: dict, base: str, api_key: str
) -> dict:
    integration_id = (args.get("integration_ids") or "").strip()
    if not integration_id:
        return _fail("get_analytics requires 'integration_ids' (single integration ID)")
    integration_id = integration_id.split(",")[0].strip()

    days = int(args.get("days", 7))

    ok, data = await _postiz_request(
        "GET", f"{base}/analytics/{integration_id}?date={days}", api_key
    )
    if not ok:
        return _fail(str(data))

    return _ok(json.dumps(data, indent=2))


async def _get_post_analytics(
    executor: ToolExecutor, args: dict, base: str, api_key: str
) -> dict:
    post_id = (args.get("post_id") or "").strip()
    if not post_id:
        return _fail("get_post_analytics requires 'post_id'")

    days = int(args.get("days", 7))

    ok, data = await _postiz_request(
        "GET", f"{base}/analytics/post/{post_id}?date={days}", api_key
    )
    if not ok:
        return _fail(str(data))

    return _ok(json.dumps(data, indent=2))


HANDLERS = {
    "postiz": postiz,
}
