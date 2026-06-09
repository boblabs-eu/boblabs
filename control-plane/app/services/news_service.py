"""Bob Manager — News service: fetches RSS/API news feeds."""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── RSS/Atom feed sources ──
FEEDS = [
    {
        "id": "bbc-world",
        "name": "BBC World",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "category": "geopolitics",
    },
    {
        "id": "bbc-business",
        "name": "BBC Business",
        "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "category": "market",
    },
    {
        "id": "reuters-world",
        "name": "Reuters World",
        "url": "https://www.reutersagency.com/feed/?best-topics=political-general",
        "category": "geopolitics",
    },
    {
        "id": "cnbc-world",
        "name": "CNBC World",
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362",
        "category": "global",
    },
    {
        "id": "coindesk",
        "name": "CoinDesk",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "category": "crypto",
    },
]

TIMEOUT = 10.0


def _parse_rss(xml_text: str, source: dict, limit: int = 20) -> list[dict]:
    """Parse RSS 2.0 XML text into a list of article dicts."""
    articles = []
    try:
        root = ET.fromstring(xml_text)
        # Standard RSS 2.0: <rss><channel><item>…</item></channel></rss>
        items = root.findall(".//item")
        for item in items[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()

            # Strip HTML tags from description
            if "<" in description:
                import re

                description = re.sub(r"<[^>]+>", "", description).strip()

            articles.append(
                {
                    "title": title,
                    "link": link,
                    "description": description[:300],
                    "pub_date": pub_date,
                    "source": source["name"],
                    "source_id": source["id"],
                    "category": source["category"],
                }
            )
    except ET.ParseError as e:
        logger.warning("Failed to parse RSS from %s: %s", source["name"], e)
    return articles


async def fetch_news(
    category: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Fetch news from all configured RSS feeds.

    Args:
        category: Filter by category (geopolitics, market, global, crypto). None = all.
        limit: Max articles per feed.

    Returns:
        List of article dicts sorted by pub_date descending.
    """
    all_articles = []
    sources = FEEDS if category is None else [f for f in FEEDS if f["category"] == category]

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        for source in sources:
            try:
                resp = await client.get(
                    source["url"],
                    headers={
                        "User-Agent": "BobManager/1.0 (RSS Reader)",
                    },
                )
                if resp.status_code == 200:
                    articles = _parse_rss(resp.text, source, limit=limit)
                    all_articles.extend(articles)
                else:
                    logger.warning("Feed %s returned HTTP %d", source["name"], resp.status_code)
            except httpx.HTTPError as e:
                logger.warning("Failed to fetch feed %s: %s", source["name"], e)

    # Sort by pub_date descending (best effort parsing)
    def parse_date(article):
        from datetime import timezone

        for fmt in (
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
        ):
            try:
                dt = datetime.strptime(article["pub_date"], fmt)
                # Normalize to UTC-aware datetime for consistent comparison
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, KeyError):
                continue
        return datetime.min.replace(tzinfo=timezone.utc)

    all_articles.sort(key=parse_date, reverse=True)
    return all_articles


def get_feed_sources() -> list[dict]:
    """Return the list of configured feed sources."""
    return [{"id": f["id"], "name": f["name"], "category": f["category"]} for f in FEEDS]
