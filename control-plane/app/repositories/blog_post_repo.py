"""Bob Manager — Blog Post and Blog Token repositories."""

import re
import secrets
import unicodedata
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blog_post import BlogPost, BlogToken


def slugify(text: str) -> str:
    """ASCII-fold + lowercase + dash-collapse. Returns 'post' if input is empty."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:180] or "post"


class BlogPostRepository:
    """Data access layer for blog posts."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self, limit: int = 50, offset: int = 0) -> list[BlogPost]:
        result = await self.db.execute(
            select(BlogPost)
            .order_by(BlogPost.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_by_id(self, post_id: UUID) -> BlogPost | None:
        result = await self.db.execute(
            select(BlogPost).where(BlogPost.id == post_id)
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> BlogPost | None:
        result = await self.db.execute(
            select(BlogPost).where(BlogPost.slug == slug)
        )
        return result.scalar_one_or_none()

    async def _resolve_unique_slug(self, base: str) -> str:
        slug = base
        i = 2
        while await self.get_by_slug(slug) is not None:
            suffix = f"-{i}"
            slug = base[: 180 - len(suffix)] + suffix
            i += 1
        return slug

    async def create(
        self,
        title: str,
        content: str,
        summary: str,
        identity: str,
        tags: list[str] | None = None,
        slug: str | None = None,
    ) -> BlogPost:
        base = slugify(slug) if slug else slugify(title)
        unique_slug = await self._resolve_unique_slug(base)
        post = BlogPost(
            title=title,
            slug=unique_slug,
            content=content,
            summary=summary,
            identity=identity,
            tags=tags or [],
        )
        self.db.add(post)
        await self.db.flush()
        await self.db.refresh(post)
        return post

    async def delete(self, post_id: UUID) -> bool:
        post = await self.get_by_id(post_id)
        if not post:
            return False
        await self.db.delete(post)
        await self.db.flush()
        return True


class BlogTokenRepository:
    """Data access layer for blog tokens."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self) -> list[BlogToken]:
        result = await self.db.execute(
            select(BlogToken).order_by(BlogToken.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(self, label: str) -> BlogToken:
        token_value = f"blog_{secrets.token_urlsafe(32)}"
        token = BlogToken(token=token_value, label=label)
        self.db.add(token)
        await self.db.flush()
        await self.db.refresh(token)
        return token

    async def validate(self, token_str: str) -> BlogToken | None:
        """Return the token record if it exists and is not revoked."""
        result = await self.db.execute(
            select(BlogToken).where(BlogToken.token == token_str)
        )
        record = result.scalar_one_or_none()
        if not record or record.revoked:
            return None
        return record

    async def revoke(self, token_id: UUID) -> bool:
        token = await self.db.execute(
            select(BlogToken).where(BlogToken.id == token_id)
        )
        if not token.scalar_one_or_none():
            return False
        await self.db.execute(
            update(BlogToken)
            .where(BlogToken.id == token_id)
            .values(revoked=True)
        )
        await self.db.flush()
        return True
