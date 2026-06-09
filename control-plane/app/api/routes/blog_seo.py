"""Bob Labs — public-blog SEO surfaces (prerender + sitemap + RSS + dynamic OG).

Mounted on the root (no /api prefix) so search engines and social-card crawlers
can hit clean URLs:

    GET /blog                          (prerendered HTML for bots; humans get SPA via nginx)
    GET /blog/{slug}                   (prerendered HTML for bots)
    GET /sitemap.xml                   (full XML sitemap)
    GET /rss.xml                       (RSS 2.0 feed)
    GET /og/blog/{slug}.png            (dynamic Open Graph image, 1200x630 PNG)

nginx routes bot User-Agents (Googlebot, Twitterbot, etc.) to /blog and /blog/{slug};
human users hit the React SPA. Sitemap, RSS, and OG images always proxy here.
"""

from __future__ import annotations

import html
import json as _json
import logging
from datetime import datetime, timezone
from email.utils import format_datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse

from app.api.dependencies import DbSession
from app.repositories.blog_post_repo import BlogPostRepository
from app.services.og_renderer import render_og_png

logger = logging.getLogger(__name__)

router = APIRouter(tags=["blog-seo"])


# ── Constants ────────────────────────────────────

SITE_ORIGIN = "https://lab.boblabs.eu"
SITE_NAME = "Bob Labs"
DEFAULT_OG_IMAGE = f"{SITE_ORIGIN}/assets/og-blog-default.png"

CACHE_POST = "public, s-maxage=3600, stale-while-revalidate=604800"
CACHE_INDEX = "public, s-maxage=300, stale-while-revalidate=86400"
CACHE_FEED = "public, s-maxage=3600"
CACHE_OG = "public, max-age=3600, s-maxage=86400, immutable"


# ── Helpers ──────────────────────────────────────


def _esc(s: str | None) -> str:
    return html.escape(s or "", quote=True)


def _xml_esc(s: str | None) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _excerpt(text: str, n: int = 280) -> str:
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[: n - 1].rsplit(" ", 1)[0] + "…"


def _iso(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _rfc822(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_datetime(dt)


def _post_url(slug: str) -> str:
    return f"{SITE_ORIGIN}/blog/{slug}"


def _og_url(slug: str, updated_at: datetime | None) -> str:
    v = int(updated_at.timestamp()) if updated_at else 0
    return f"{SITE_ORIGIN}/og/blog/{slug}.png?v={v}"


# ── Prerender: /blog (index for bots) ────────────


@router.get("/blog", response_class=HTMLResponse)
async def prerender_blog_index(db: DbSession):
    repo = BlogPostRepository(db)
    posts = await repo.get_all(limit=100, offset=0)

    title = f"Blog — {SITE_NAME}"
    description = "Updates, technical notes, and AI-agent dispatches from Bob Labs."
    canonical = f"{SITE_ORIGIN}/blog"

    items_html = "\n".join(
        f'<li><a href="{_esc(_post_url(p.slug))}"><strong>{_esc(p.title)}</strong></a>'
        f" <small>by {_esc(p.identity)}</small>"
        f"<p>{_esc(_excerpt(p.summary or p.content, 240))}</p></li>"
        for p in posts
    )

    body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(description)}">
<link rel="canonical" href="{_esc(canonical)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{_esc(SITE_NAME)}">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(description)}">
<meta property="og:url" content="{_esc(canonical)}">
<meta property="og:image" content="{_esc(DEFAULT_OG_IMAGE)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{_esc(title)}">
<meta name="twitter:description" content="{_esc(description)}">
<meta name="twitter:image" content="{_esc(DEFAULT_OG_IMAGE)}">
<link rel="alternate" type="application/rss+xml" title="{_esc(SITE_NAME)} blog" href="{_esc(SITE_ORIGIN)}/rss.xml">
</head>
<body>
<h1>{_esc(title)}</h1>
<p>{_esc(description)}</p>
<ul>
{items_html}
</ul>
</body>
</html>
"""
    return HTMLResponse(body, headers={"Cache-Control": CACHE_INDEX})


# ── Prerender: /blog/{slug} ──────────────────────


@router.get("/blog/{slug}", response_class=HTMLResponse)
async def prerender_blog_post(slug: str, db: DbSession):
    repo = BlogPostRepository(db)
    post = await repo.get_by_slug(slug)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")

    title = f"{post.title} — {SITE_NAME}"
    description = _excerpt(post.summary or post.content, 280) or post.title
    canonical = _post_url(post.slug)
    og_image = _og_url(post.slug, post.updated_at)

    # JSON-LD BlogPosting
    ld = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post.title,
        "description": description,
        "datePublished": _iso(post.created_at),
        "dateModified": _iso(post.updated_at),
        "author": {"@type": "Person", "name": post.identity},
        "image": og_image,
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        "publisher": {
            "@type": "Organization",
            "name": SITE_NAME,
            "url": SITE_ORIGIN,
        },
        "url": canonical,
        "keywords": ", ".join(post.tags or []),
    }
    ld_json = _json.dumps(ld, ensure_ascii=False)

    # Body — paragraph-split, escaped. Crawlers ingest this as the article text.
    paragraphs = "\n".join(
        f"<p>{_esc(line.strip())}</p>" for line in (post.content or "").split("\n") if line.strip()
    )
    tags_html = " ".join(f'<span class="tag">{_esc(t)}</span>' for t in (post.tags or []))

    body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(description)}">
<link rel="canonical" href="{_esc(canonical)}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{_esc(SITE_NAME)}">
<meta property="og:title" content="{_esc(post.title)}">
<meta property="og:description" content="{_esc(description)}">
<meta property="og:url" content="{_esc(canonical)}">
<meta property="og:image" content="{_esc(og_image)}">
<meta property="article:published_time" content="{_esc(_iso(post.created_at))}">
<meta property="article:modified_time" content="{_esc(_iso(post.updated_at))}">
<meta property="article:author" content="{_esc(post.identity)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{_esc(post.title)}">
<meta name="twitter:description" content="{_esc(description)}">
<meta name="twitter:image" content="{_esc(og_image)}">
<link rel="alternate" type="application/rss+xml" title="{_esc(SITE_NAME)} blog" href="{_esc(SITE_ORIGIN)}/rss.xml">
<script type="application/ld+json">{ld_json}</script>
</head>
<body>
<article>
<h1>{_esc(post.title)}</h1>
<p class="byline">by {_esc(post.identity)} · <time datetime="{_esc(_iso(post.created_at))}">{_esc(_iso(post.created_at)[:10])}</time></p>
<div class="tags">{tags_html}</div>
{paragraphs}
</article>
<p><a href="{_esc(SITE_ORIGIN)}/blog">← All posts</a></p>
</body>
</html>
"""
    return HTMLResponse(
        body,
        headers={
            "Cache-Control": CACHE_POST,
            "Cache-Tag": f"blog,blog-{post.slug}",
        },
    )


# ── /sitemap.xml ─────────────────────────────────


@router.get("/sitemap.xml")
async def sitemap_xml(db: DbSession):
    repo = BlogPostRepository(db)
    posts = await repo.get_all(limit=10_000, offset=0)

    urls: list[str] = [
        f"<url><loc>{SITE_ORIGIN}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>",
        f"<url><loc>{SITE_ORIGIN}/blog</loc><changefreq>daily</changefreq><priority>0.8</priority></url>",
        f"<url><loc>{SITE_ORIGIN}/docs</loc><changefreq>weekly</changefreq><priority>0.6</priority></url>",
    ]
    for p in posts:
        lastmod = _iso(p.updated_at)
        urls.append(
            f"<url><loc>{_xml_esc(_post_url(p.slug))}</loc>"
            f"<lastmod>{_xml_esc(lastmod)}</lastmod>"
            f"<changefreq>weekly</changefreq><priority>0.7</priority></url>"
        )

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    return Response(
        content=body,
        media_type="application/xml",
        headers={"Cache-Control": CACHE_FEED},
    )


# ── /rss.xml ─────────────────────────────────────


@router.get("/rss.xml")
async def rss_xml(db: DbSession):
    repo = BlogPostRepository(db)
    posts = await repo.get_all(limit=50, offset=0)

    last_build = _rfc822(datetime.now(timezone.utc))
    items: list[str] = []
    for p in posts:
        link = _post_url(p.slug)
        desc = _excerpt(p.summary or p.content, 600)
        items.append(
            "<item>\n"
            f"<title>{_xml_esc(p.title)}</title>\n"
            f"<link>{_xml_esc(link)}</link>\n"
            f'<guid isPermaLink="true">{_xml_esc(link)}</guid>\n'
            f"<pubDate>{_xml_esc(_rfc822(p.created_at))}</pubDate>\n"
            f"<author>noreply@boblabs.eu ({_xml_esc(p.identity)})</author>\n"
            f"<description><![CDATA[{desc}]]></description>\n"
            "</item>"
        )

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "<channel>\n"
        f"<title>{_xml_esc(SITE_NAME)} — Blog</title>\n"
        f"<link>{_xml_esc(SITE_ORIGIN)}/blog</link>\n"
        f'<atom:link href="{_xml_esc(SITE_ORIGIN)}/rss.xml" rel="self" type="application/rss+xml" />\n'
        "<description>Updates, technical notes, and AI-agent dispatches from Bob Labs.</description>\n"
        "<language>en</language>\n"
        f"<lastBuildDate>{_xml_esc(last_build)}</lastBuildDate>\n"
        + "\n".join(items)
        + "\n</channel>\n</rss>\n"
    )
    return Response(
        content=body,
        media_type="application/rss+xml",
        headers={"Cache-Control": CACHE_FEED},
    )


# ── /og/blog/{slug}.png ─────────────────────────


@router.get("/og/blog/{slug}.png")
async def og_blog_image(slug: str, request: Request, db: DbSession):
    if slug.endswith(".png"):
        slug = slug[:-4]
    repo = BlogPostRepository(db)
    post = await repo.get_by_slug(slug)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")

    updated_epoch = int(post.updated_at.timestamp()) if post.updated_at else 0
    etag = f'"{post.slug}-{updated_epoch}"'

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": CACHE_OG})

    png_bytes: bytes = render_og_png(
        title=post.title,
        summary=post.summary or _excerpt(post.content, 200),
        identity=post.identity,
        cache_key=(post.slug, updated_epoch),
    )

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "ETag": etag,
            "Cache-Control": CACHE_OG,
            "Content-Length": str(len(png_bytes)),
        },
    )
