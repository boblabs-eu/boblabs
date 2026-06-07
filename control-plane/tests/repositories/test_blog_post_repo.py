"""R12 — BlogPostRepository.create atomic-slug retry.

Pre-fix: SELECT-then-INSERT race could produce a 5xx on concurrent
posts with the same slug. Now: optimistic INSERT + retry on
IntegrityError.

This test seeds an existing post then has a second create() target
the same slug — the retry should bump and succeed.
"""

from __future__ import annotations

import pytest

from app.repositories.blog_post_repo import BlogPostRepository, slugify

pytestmark = pytest.mark.repo


@pytest.mark.asyncio
async def test_create_collision_retry_bumps_suffix(db):
    repo = BlogPostRepository(db)
    first = await repo.create(
        title="My Post",
        content="hello",
        summary="",
        identity="admin",
    )
    assert first.slug == "my-post"

    second = await repo.create(
        title="My Post",
        content="hello again",
        summary="",
        identity="admin",
    )
    assert second.slug != first.slug
    assert second.slug.startswith("my-post-")


def test_slugify_normalises_diacritics():
    assert slugify("Café résumé") == "cafe-resume"
    assert slugify("hello world") == "hello-world"
    assert slugify("") == "post"
