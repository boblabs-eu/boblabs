"""Bob Manager — News API routes."""

from typing import Optional

from fastapi import APIRouter, Query

from app.services.news_service import fetch_news, get_feed_sources

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/")
async def list_news(
    category: Optional[str] = Query(
        None, description="Filter by category: geopolitics, market, global, crypto"
    ),
    limit: int = Query(50, ge=1, le=200),
):
    """Fetch latest news articles from configured RSS feeds."""
    articles = await fetch_news(category=category, limit=limit)
    return articles


@router.get("/sources")
async def list_sources():
    """Return the list of configured news feed sources."""
    return get_feed_sources()
