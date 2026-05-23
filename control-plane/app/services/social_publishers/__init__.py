"""Per-platform social-media publisher adapters.

Each adapter is responsible for taking a resolved account credential dict
and a piece of post content, then publishing it to the platform.

For now every adapter runs in **dry-run** mode and just returns a synthetic
post id without contacting any external API. When real API keys are wired
later, replace the body of each `publish_*` function with the actual HTTP
call — no changes are needed in the calling tool layer.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


def _stub(platform: str, account: dict, content: str) -> dict:
    posted_id = f"stub-{platform}-{uuid.uuid4().hex[:10]}"
    logger.info(
        "social_publishers[%s] DRY-RUN account=%s len=%d id=%s",
        platform, account.get("account_id"), len(content), posted_id,
    )
    return {
        "success": True,
        "dry_run": True,
        "posted_id": posted_id,
        "platform": platform,
        "account_id": account.get("account_id"),
        "posted_at": int(time.time()),
    }


async def publish_x(account: dict, content: str, media_urls: list[str]) -> dict:
    # TODO: real X API v2 POST /tweets when bearer/access tokens are configured.
    return _stub("x", account, content)


async def publish_linkedin(account: dict, content: str, media_urls: list[str]) -> dict:
    # TODO: real LinkedIn UGC POST /v2/ugcPosts when access_token + person_urn are configured.
    return _stub("linkedin", account, content)


async def publish_instagram(account: dict, content: str, media_urls: list[str]) -> dict:
    # TODO: real Instagram Graph API POST /{ig-user-id}/media + /media_publish.
    return _stub("instagram", account, content)


async def publish_facebook(account: dict, content: str, media_urls: list[str]) -> dict:
    # TODO: real Facebook Graph POST /{page-id}/feed when page_access_token is configured.
    return _stub("facebook", account, content)


_DISPATCH: dict[str, Callable[[dict, str, list[str]], Awaitable[dict]]] = {
    "x": publish_x,
    "linkedin": publish_linkedin,
    "instagram": publish_instagram,
    "facebook": publish_facebook,
}


async def publish(*, platform: str, account: dict, content: str, media_urls: list[str]) -> dict:
    fn = _DISPATCH.get(platform)
    if fn is None:
        return {"success": False, "error": f"Unknown platform '{platform}'"}
    try:
        return await fn(account, content, media_urls)
    except Exception as exc:
        logger.exception("social_publishers[%s] failed", platform)
        return {"success": False, "error": str(exc)}
