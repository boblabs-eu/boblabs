"""Bob Manager — Blog Post and Blog Token repositories."""

import re
import secrets
import unicodedata
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.blog_post import BlogPost, BlogToken
from app.repositories._paginate import MAX_LIMIT, clamp_limit


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
        # P05 — clamp caller-supplied limit so a malformed query string
        # can't ask for the whole blog table.
        result = await self.db.execute(
            select(BlogPost)
            .order_by(BlogPost.created_at.desc())
            .limit(clamp_limit(limit))
            .offset(max(0, offset))
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
        """Best-effort slug resolution. R12 — the atomic guard is in
        :meth:`create`'s retry loop on UNIQUE-violation; this helper
        only handles the common-case suffix bump so the first INSERT
        usually succeeds without a roundtrip retry."""
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
        """R12 — slug uniqueness is enforced atomically.

        Pre-fix: ``_resolve_unique_slug`` did a SELECT-then-INSERT race;
        two concurrent ``POST /blog`` calls with the same title both
        saw "slug-1 is free", both INSERTed, and the second got a
        5xx after the DB rejected the duplicate. Now: pick an
        optimistic slug, INSERT, and on UNIQUE-violation retry with
        a bumped suffix. The retry caps at 5 attempts (vanishingly
        unlikely to collide that many times in a row).
        """
        from sqlalchemy.exc import IntegrityError
        base = slugify(slug) if slug else slugify(title)
        candidate = await self._resolve_unique_slug(base)

        for attempt in range(5):
            post = BlogPost(
                title=title,
                slug=candidate,
                content=content,
                summary=summary,
                identity=identity,
                tags=tags or [],
            )
            self.db.add(post)
            try:
                await self.db.flush()
                await self.db.refresh(post)
                return post
            except IntegrityError:
                # Race: another transaction took our slug between the
                # SELECT and the INSERT. Bump the suffix and retry.
                await self.db.rollback()
                candidate = await self._resolve_unique_slug(
                    f"{base}-{attempt + 2}"
                )
        # All retries collided — surface a clean error rather than the
        # raw IntegrityError so the route returns a 409.
        from fastapi import HTTPException
        raise HTTPException(
            status_code=409,
            detail="Could not allocate a unique slug after 5 attempts.",
        )

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

    async def get_all(self, limit: int = MAX_LIMIT, offset: int = 0) -> list[BlogToken]:
        # P04 — cap unbounded scan.
        result = await self.db.execute(
            select(BlogToken)
            .order_by(BlogToken.created_at.desc())
            .limit(clamp_limit(limit))
            .offset(max(0, offset))
        )
        return list(result.scalars().all())

    async def create(self, label: str) -> BlogToken:
        token_value = f"blog_{secrets.token_urlsafe(32)}"
        import hashlib
        token = BlogToken(
            token=token_value,
            token_hash=hashlib.sha256(token_value.encode("utf-8")).hexdigest(),
            label=label,
        )
        self.db.add(token)
        await self.db.flush()
        await self.db.refresh(token)
        return token

    async def validate(self, token_str: str) -> BlogToken | None:
        """Return the token record if it exists and is not revoked.

        Cluster K — indexed token_hash lookup with dual-read fallback to
        the plaintext column during the deprecation window. Constant-
        time secondary check via hmac.compare_digest.
        """
        import hashlib
        import hmac
        digest = hashlib.sha256(token_str.encode("utf-8")).hexdigest()
        result = await self.db.execute(
            select(BlogToken).where(BlogToken.token_hash == digest)
        )
        record = result.scalar_one_or_none()
        if record is None:
            # Dual-read fallback.
            result = await self.db.execute(
                select(BlogToken).where(BlogToken.token == token_str)
            )
            record = result.scalar_one_or_none()
        if not record or record.revoked:
            return None
        if record.token_hash:
            if not hmac.compare_digest(record.token_hash, digest):
                return None
        elif record.token:
            if not hmac.compare_digest(record.token, token_str):
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
