"""Integration tools: youtube, mail, twitter, call_agent, clock."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

from app.services.sandbox_client import signed_post_json

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

TOOLS = {
    "youtube": {
        "description": "YouTube tool with multiple actions. download_audio: Download audio from a YouTube video URL (saved to workspace). list_channel: List recent videos from a YouTube channel.",
        "parameters": {
            "action": {
                "type": "string",
                "description": "Action: download_audio, list_channel",
                "required": True,
            },
            "url": {
                "type": "string",
                "description": "YouTube video URL (for download_audio)",
                "required": False,
            },
            "format": {
                "type": "string",
                "description": "Audio format: mp3 or wav (default: mp3)",
                "required": False,
            },
            "channel_url": {
                "type": "string",
                "description": "YouTube channel URL (for list_channel)",
                "required": False,
            },
            "max_videos": {
                "type": "integer",
                "description": "Max videos to list (default: 20)",
                "required": False,
            },
        },
    },
    "mail": {
        "description": "Send or read emails via SMTP/IMAP. Requires mail tool configuration in Settings → Tool Configs.",
        "sensitive": True,
        "sensitive_reason": (
            "Sends real emails from a configured mailbox and can read inbox contents. "
            "Outgoing messages are hard to retract and may contain sensitive data."
        ),
        "parameters": {
            "action": {"type": "string", "description": "Action: send or read", "required": True},
            "to": {
                "type": "string",
                "description": "Recipient email (for send)",
                "required": False,
            },
            "subject": {
                "type": "string",
                "description": "Email subject (for send)",
                "required": False,
            },
            "body": {
                "type": "string",
                "description": "Email body text or HTML (for send)",
                "required": False,
            },
            "html": {
                "type": "string",
                "description": "Set to 'true' to send body as HTML (default: false)",
                "required": False,
            },
            "folder": {
                "type": "string",
                "description": "IMAP folder to read (default: INBOX)",
                "required": False,
            },
            "limit": {
                "type": "integer",
                "description": "Max emails to read (default: 10, max: 50)",
                "required": False,
            },
            "search": {
                "type": "string",
                "description": "IMAP search criteria (default: ALL)",
                "required": False,
            },
        },
    },
    "twitter": {
        "description": "Post or read tweets via Twitter/X API v2. Requires Twitter API credentials in Settings → Tool Configs.",
        "sensitive": True,
        "sensitive_reason": (
            "Publishes tweets to a real X (Twitter) account. "
            "Posts are public and may be hard to retract."
        ),
        "parameters": {
            "action": {"type": "string", "description": "Action: post or read", "required": True},
            "text": {
                "type": "string",
                "description": "Tweet text (for post, max 280 chars)",
                "required": False,
            },
            "feed": {
                "type": "string",
                "description": "Feed to read: timeline, mentions, search (default: timeline)",
                "required": False,
            },
            "query": {
                "type": "string",
                "description": "Search query (required when feed=search)",
                "required": False,
            },
            "limit": {
                "type": "integer",
                "description": "Max tweets to return (default: 20, max: 100)",
                "required": False,
            },
        },
    },
    "call_agent": {
        "description": "Delegate a task to another agent in the lab. The agent will execute the instruction and return the result.",
        "parameters": {
            "agent_name": {
                "type": "string",
                "description": "Name of the agent to call",
                "required": True,
            },
            "instruction": {
                "type": "string",
                "description": "Task instruction for the agent",
                "required": True,
            },
        },
    },
    "clock": {
        "description": "Get current UTC timestamp or manage named timers. Actions: timestamp (get current time), start (start a timer), stop (stop a timer), elapsed (check timer), list (list all timers), reset (remove a timer).",
        "parameters": {
            "action": {
                "type": "string",
                "description": "Action: timestamp, start, stop, elapsed, list, reset (default: timestamp)",
                "required": False,
            },
            "name": {
                "type": "string",
                "description": "Timer name (default: 'default')",
                "required": False,
            },
        },
    },
}


# ── YouTube ───────────────────────────────────


async def youtube(executor: ToolExecutor, args: dict) -> dict:
    """Unified YouTube tool with action dispatch."""
    action = (args.get("action") or "").strip().lower()
    if not action:
        return {
            "success": False,
            "output": "youtube requires 'action' (download_audio or list_channel)",
        }

    allowed = executor._subtool_permissions.get("youtube", [])
    if allowed and action not in allowed:
        return {
            "success": False,
            "output": f"Action '{action}' not permitted. Allowed: {', '.join(allowed)}",
        }

    if action == "download_audio":
        return await _youtube_download_audio(executor, args)
    elif action == "list_channel":
        return await _youtube_list_channel(executor, args)
    else:
        return {
            "success": False,
            "output": f"Unknown youtube action: {action}. Use 'download_audio' or 'list_channel'.",
        }


async def _youtube_download_audio(executor: ToolExecutor, args: dict) -> dict:
    """Download audio from a YouTube URL via sandbox service."""
    url = str(args.get("url", "")).strip()
    fmt = str(args.get("format", "mp3")).strip().lower()

    if not url:
        return {"success": False, "output": "youtube download_audio requires 'url'"}

    try:
        sandbox_url = await executor.get_sandbox_url()
        result = await signed_post_json(
            sandbox_url,
            "/youtube_download",
            {
                "lab_id": str(executor.lab_id),
                "url": url,
                "audio_format": fmt,
                "timeout_sec": min(executor.timeout_sec, 300),
                "max_output_kb": executor.max_output_bytes // 1024,
            },
            timeout=330.0,
        )
    except httpx.TimeoutException:
        return {"success": False, "output": "YouTube download timed out."}
    except Exception as e:
        logger.exception("youtube download_audio failed for lab %s", executor.lab_id)
        return {"success": False, "output": f"Download error: {e}"}

    if not result.get("success"):
        return {"success": False, "output": result.get("output", "Download failed.")}

    try:
        info = json.loads(result["output"])
    except (json.JSONDecodeError, KeyError):
        return {"success": True, "output": result.get("output", "Download completed.")}

    rel_path = info.get("output_path", "")
    title = info.get("title", "unknown")
    duration = info.get("duration_seconds", 0)
    size = info.get("filesize_bytes", 0)

    dur_str = f" ({duration}s)" if duration else ""
    size_str = f" ({size // 1024}KB)" if size else ""

    return {
        "success": True,
        "output": f"Downloaded: {title}{dur_str}{size_str}\nFile: {rel_path}",
        "file_event": {
            "action": "created",
            "path": rel_path,
            "size_bytes": size,
        },
    }


async def _youtube_list_channel(executor: ToolExecutor, args: dict) -> dict:
    """List recent videos from a YouTube channel via sandbox."""
    channel_url = str(args.get("channel_url", "")).strip()
    max_videos = int(args.get("max_videos", 20))

    if not channel_url:
        return {"success": False, "output": "youtube list_channel requires 'channel_url'"}

    try:
        sandbox_url = await executor.get_sandbox_url()
        result = await signed_post_json(
            sandbox_url,
            "/youtube_channel_list",
            {
                "lab_id": str(executor.lab_id),
                "channel_url": channel_url,
                "max_videos": max_videos,
            },
            timeout=180.0,
        )
    except httpx.TimeoutException:
        return {"success": False, "output": "YouTube channel listing timed out."}
    except Exception as e:
        logger.exception("youtube list_channel failed for lab %s", executor.lab_id)
        return {"success": False, "output": f"Channel listing error: {e}"}

    if not result.get("success"):
        return {"success": False, "output": result.get("output", "Channel listing failed.")}

    try:
        info = json.loads(result["output"])
    except (json.JSONDecodeError, KeyError):
        return {"success": True, "output": result.get("output", "Listing completed.")}

    videos = info.get("videos", [])
    count = info.get("count", len(videos))
    channel = info.get("channel", channel_url)

    lines = [f"Found {count} videos on {channel}:\n"]
    for i, v in enumerate(videos, 1):
        date_str = f" ({v['publish_date']})" if v.get("publish_date") else ""
        lines.append(f"{i}. {v['title']}{date_str}\n   {v['url']}")

    return {
        "success": True,
        "output": "\n".join(lines),
    }


# ── Mail ──────────────────────────────────────


async def mail(executor: ToolExecutor, args: dict) -> dict:
    """Send or read emails via SMTP/IMAP."""
    action = (args.get("action") or "").strip().lower()
    if not action:
        return {"success": False, "output": "mail requires 'action' (send or read)"}

    allowed = executor._subtool_permissions.get("mail", [])
    if allowed and action not in allowed:
        return {
            "success": False,
            "output": f"Action '{action}' not permitted. Allowed: {', '.join(allowed)}",
        }

    from sqlalchemy import select

    from app.models.orchestrator import ToolConfig

    result = await executor.db.execute(select(ToolConfig).where(ToolConfig.tool_type == "mail"))
    tc = result.scalar_one_or_none()
    if not tc or not tc.config:
        return {
            "success": False,
            "output": "Mail tool not configured. Ask the admin to set up SMTP/IMAP in Settings → Tool Configs.",
        }
    cfg = tc.config

    if action == "send":
        return await _mail_send(executor, args, cfg)
    elif action == "read":
        return await _mail_read(args, cfg)
    else:
        return {"success": False, "output": f"Unknown mail action: {action}. Use 'send' or 'read'."}


async def _mail_send(executor: ToolExecutor, args: dict, cfg: dict) -> dict:
    """Send an email via SMTP."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    import aiosmtplib

    to_addr = (args.get("to") or "").strip()
    subject = (args.get("subject") or "").strip()
    body = (args.get("body") or "").strip()

    if not to_addr:
        return {"success": False, "output": "mail send requires 'to' (recipient email)"}
    if not subject:
        return {"success": False, "output": "mail send requires 'subject'"}
    if not body:
        return {"success": False, "output": "mail send requires 'body'"}

    smtp_host = cfg.get("smtp_host", "")
    smtp_port = int(cfg.get("smtp_port", 587))
    smtp_user = cfg.get("smtp_user", "")
    smtp_password = cfg.get("smtp_password", "")
    smtp_from = cfg.get("smtp_from", "") or smtp_user
    smtp_tls = cfg.get("smtp_tls", True)

    if not smtp_host or not smtp_user:
        return {
            "success": False,
            "output": "SMTP not configured (missing host or user). Check Tool Configs.",
        }

    is_html = str(args.get("html", "false")).lower() in ("true", "1", "yes")

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp_from
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html" if is_html else "plain", "utf-8"))

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
        return {"success": True, "output": f"Email sent to {to_addr} — subject: {subject}"}
    except Exception as e:
        return {"success": False, "output": f"SMTP error: {e}"}


async def _mail_read(args: dict, cfg: dict) -> dict:
    """Read recent emails via IMAP."""
    import email
    import imaplib
    from email.header import decode_header

    imap_host = cfg.get("imap_host", "")
    imap_port = int(cfg.get("imap_port", 993))
    imap_user = cfg.get("imap_user", "") or cfg.get("smtp_user", "")
    imap_password = cfg.get("imap_password", "") or cfg.get("smtp_password", "")
    imap_tls = cfg.get("imap_tls", True)

    if not imap_host or not imap_user:
        return {
            "success": False,
            "output": "IMAP not configured (missing host or user). Check Tool Configs.",
        }

    folder = args.get("folder", "INBOX").strip()
    limit = min(int(args.get("limit", 10)), 50)
    search_criteria = args.get("search", "ALL").strip()

    def _read_sync():
        if imap_tls:
            conn = imaplib.IMAP4_SSL(imap_host, imap_port)
        else:
            conn = imaplib.IMAP4(imap_host, imap_port)
        try:
            conn.login(imap_user, imap_password)
            conn.select(folder, readonly=True)
            _, msg_nums = conn.search(None, search_criteria)
            ids = msg_nums[0].split()
            if not ids:
                return []
            ids = ids[-limit:]
            results = []
            for mid in reversed(ids):
                _, data = conn.fetch(mid, "(RFC822)")
                raw = data[0][1]
                msg = email.message_from_bytes(raw)
                subj_parts = decode_header(msg.get("Subject", ""))
                subj = ""
                for part, enc in subj_parts:
                    if isinstance(part, bytes):
                        subj += part.decode(enc or "utf-8", errors="replace")
                    else:
                        subj += part
                from_addr = msg.get("From", "")
                date_str = msg.get("Date", "")
                body_text = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ct = part.get_content_type()
                        if ct == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body_text = payload.decode(
                                    part.get_content_charset() or "utf-8", errors="replace"
                                )
                                break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body_text = payload.decode(
                            msg.get_content_charset() or "utf-8", errors="replace"
                        )
                if len(body_text) > 2000:
                    body_text = body_text[:2000] + "\n... [truncated]"
                results.append(
                    {
                        "from": from_addr,
                        "subject": subj,
                        "date": date_str,
                        "body": body_text.strip(),
                    }
                )
            return results
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    try:
        messages = await asyncio.to_thread(_read_sync)
    except Exception as e:
        return {"success": False, "output": f"IMAP error: {e}"}

    if not messages:
        return {
            "success": True,
            "output": f"No messages found in {folder} (search: {search_criteria}).",
        }

    lines = [f"Found {len(messages)} message(s) in {folder}:\n"]
    for i, m in enumerate(messages, 1):
        lines.append(f"--- Message {i} ---")
        lines.append(f"From: {m['from']}")
        lines.append(f"Date: {m['date']}")
        lines.append(f"Subject: {m['subject']}")
        lines.append(f"Body:\n{m['body']}")
        lines.append("")
    return {"success": True, "output": "\n".join(lines)}


# ── Twitter ───────────────────────────────────


async def twitter(executor: ToolExecutor, args: dict) -> dict:
    """Post or read tweets via Twitter/X API v2."""
    action = (args.get("action") or "").strip().lower()
    if not action:
        return {"success": False, "output": "twitter requires 'action' (post or read)"}

    allowed = executor._subtool_permissions.get("twitter", [])
    if allowed and action not in allowed:
        return {
            "success": False,
            "output": f"Action '{action}' not permitted. Allowed: {', '.join(allowed)}",
        }

    from sqlalchemy import select

    from app.models.orchestrator import ToolConfig

    result = await executor.db.execute(select(ToolConfig).where(ToolConfig.tool_type == "twitter"))
    tc = result.scalar_one_or_none()
    if not tc or not tc.config:
        return {
            "success": False,
            "output": "Twitter tool not configured. Ask the admin to set up API keys in Settings → Tool Configs.",
        }
    cfg = tc.config

    if action == "post":
        return await _twitter_post(args, cfg)
    elif action == "read":
        return await _twitter_read(args, cfg)
    else:
        return {
            "success": False,
            "output": f"Unknown twitter action: {action}. Use 'post' or 'read'.",
        }


async def _twitter_post(args: dict, cfg: dict) -> dict:
    """Post a tweet via Twitter API v2."""
    text = (args.get("text") or "").strip()
    if not text:
        return {"success": False, "output": "twitter post requires 'text'"}
    if len(text) > 280:
        return {"success": False, "output": f"Tweet too long ({len(text)} chars). Max 280."}

    api_key = cfg.get("api_key", "")
    api_secret = cfg.get("api_secret", "")
    access_token = cfg.get("access_token", "")
    access_token_secret = cfg.get("access_token_secret", "")

    if not all([api_key, api_secret, access_token, access_token_secret]):
        return {
            "success": False,
            "output": "Twitter OAuth credentials incomplete. Need api_key, api_secret, access_token, access_token_secret.",
        }

    def _post_sync():
        import tweepy

        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_token_secret,
        )
        resp = client.create_tweet(text=text)
        return resp.data

    try:
        data = await asyncio.to_thread(_post_sync)
        tweet_id = data.get("id", "unknown")
        return {"success": True, "output": f"Tweet posted (id: {tweet_id}): {text}"}
    except Exception as e:
        return {"success": False, "output": f"Twitter API error: {e}"}


async def _twitter_read(args: dict, cfg: dict) -> dict:
    """Read tweets from timeline, mentions, or search."""
    feed = (args.get("feed") or "timeline").strip().lower()
    limit = min(int(args.get("limit", 20)), 100)
    query = (args.get("query") or "").strip()

    bearer_token = cfg.get("bearer_token", "")
    api_key = cfg.get("api_key", "")
    api_secret = cfg.get("api_secret", "")
    access_token = cfg.get("access_token", "")
    access_token_secret = cfg.get("access_token_secret", "")

    if not bearer_token and not all([api_key, api_secret, access_token, access_token_secret]):
        return {
            "success": False,
            "output": "Twitter credentials missing. Need bearer_token or full OAuth keys.",
        }

    def _read_sync():
        import tweepy

        client = tweepy.Client(
            bearer_token=bearer_token or None,
            consumer_key=api_key or None,
            consumer_secret=api_secret or None,
            access_token=access_token or None,
            access_token_secret=access_token_secret or None,
        )

        tweet_fields = ["created_at", "author_id", "public_metrics"]

        if feed == "mentions":
            me = client.get_me()
            resp = client.get_users_mentions(
                me.data.id,
                max_results=min(limit, 100),
                tweet_fields=tweet_fields,
            )
        elif feed == "search":
            if not query:
                return [{"error": "feed='search' requires 'query' parameter"}]
            resp = client.search_recent_tweets(
                query=query,
                max_results=min(limit, 100),
                tweet_fields=tweet_fields,
            )
        else:  # timeline
            me = client.get_me()
            resp = client.get_users_tweets(
                me.data.id,
                max_results=min(limit, 100),
                tweet_fields=tweet_fields,
            )

        if not resp.data:
            return []
        results = []
        for tw in resp.data:
            results.append(
                {
                    "id": str(tw.id),
                    "text": tw.text,
                    "created_at": str(tw.created_at) if tw.created_at else "",
                    "metrics": tw.public_metrics or {},
                }
            )
        return results

    try:
        tweets = await asyncio.to_thread(_read_sync)
    except Exception as e:
        return {"success": False, "output": f"Twitter API error: {e}"}

    if not tweets:
        return {"success": True, "output": f"No tweets found ({feed})."}

    if tweets and "error" in tweets[0]:
        return {"success": False, "output": tweets[0]["error"]}

    lines = [f"Found {len(tweets)} tweet(s) ({feed}):\n"]
    for i, tw in enumerate(tweets, 1):
        metrics = tw.get("metrics", {})
        stats = f"♡{metrics.get('like_count', 0)} 🔁{metrics.get('retweet_count', 0)}"
        lines.append(f"{i}. [{tw['created_at']}] {tw['text']}")
        lines.append(f"   id={tw['id']} {stats}")
        lines.append("")
    return {"success": True, "output": "\n".join(lines)}


# ── Call Agent ────────────────────────────────


async def call_agent(executor: ToolExecutor, args: dict) -> dict:
    agent_name = args.get("agent_name", "").strip()
    instruction = args.get("instruction", "").strip()
    if not agent_name:
        return {"success": False, "output": "call_agent requires 'agent_name'"}
    if not instruction:
        return {"success": False, "output": "call_agent requires 'instruction'"}

    if not executor._call_agent_handler:
        return {
            "success": False,
            "output": "Agent-to-agent calling is not available in this context.",
        }

    try:
        result = await executor._call_agent_handler(agent_name, instruction)
        return {"success": True, "output": result}
    except Exception as e:
        return {"success": False, "output": f"call_agent failed: {e}"}


# ── Clock ─────────────────────────────────────


async def clock(executor: ToolExecutor, args: dict) -> dict:
    action = args.get("action", "timestamp").lower()
    name = args.get("name", "default")
    now = datetime.now(timezone.utc)

    if action == "timestamp":
        return {"success": True, "output": now.isoformat()}

    if action == "list":
        if not executor._timers:
            return {"success": True, "output": "No active timers."}
        lines = []
        for tname, t in executor._timers.items():
            if t["running"]:
                elapsed = t["elapsed"] + (now - t["start"]).total_seconds()
                lines.append(f"  {tname}: {elapsed:.2f}s (running)")
            else:
                lines.append(f"  {tname}: {t['elapsed']:.2f}s (stopped)")
        return {"success": True, "output": "Timers:\n" + "\n".join(lines)}

    if action == "start":
        executor._timers[name] = {"start": now, "elapsed": 0.0, "running": True}
        return {"success": True, "output": f"Timer '{name}' started at {now.isoformat()}"}

    if action == "stop":
        t = executor._timers.get(name)
        if not t:
            return {"success": False, "output": f"Timer '{name}' not found."}
        if t["running"]:
            t["elapsed"] += (now - t["start"]).total_seconds()
            t["running"] = False
        return {"success": True, "output": f"Timer '{name}' stopped. Elapsed: {t['elapsed']:.2f}s"}

    if action == "elapsed":
        t = executor._timers.get(name)
        if not t:
            return {"success": False, "output": f"Timer '{name}' not found."}
        elapsed = t["elapsed"]
        if t["running"]:
            elapsed += (now - t["start"]).total_seconds()
        return {"success": True, "output": f"Timer '{name}': {elapsed:.2f}s"}

    if action == "reset":
        if name in executor._timers:
            del executor._timers[name]
            return {"success": True, "output": f"Timer '{name}' reset."}
        return {"success": True, "output": f"Timer '{name}' was not active."}

    return {"success": False, "output": f"Unknown clock action: {action}"}


HANDLERS = {
    "youtube": youtube,
    "mail": mail,
    "twitter": twitter,
    "call_agent": call_agent,
    "clock": clock,
}
