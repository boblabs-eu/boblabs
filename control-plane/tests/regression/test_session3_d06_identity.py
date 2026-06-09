"""D06 — POST /public/blog identity comes from auth, not from payload.

Pre-fix: blog_posts.identity stored whatever the client submitted.
A third-party blog-token holder could publish a post claiming to be
'admin'. Now:
  - admin_secret writers always land as identity='admin'
  - blog-token writers land as identity=<token.label>
  - payload.identity is ignored
"""

from __future__ import annotations

import os
import uuid

import pytest
from app.models.blog_post import BlogPost, BlogToken
from sqlalchemy import select

pytestmark = pytest.mark.regression


@pytest.mark.asyncio
async def test_admin_secret_writes_identity_admin(anonymous_client, db):
    r = await anonymous_client.post(
        "/api/v1/public/blog",
        json={
            "title": "Hello",
            "content": "world",
            "summary": "",
            "identity": "i-am-attacker",  # lie — must be ignored
            "admin_secret": os.environ["ADMIN_SECRET"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["identity"] == "admin"
    # DB check
    row = (await db.execute(select(BlogPost).where(BlogPost.slug == body["slug"]))).scalar_one()
    assert row.identity == "admin"


@pytest.mark.asyncio
async def test_blog_token_writes_identity_from_label(anonymous_client, db):
    """Mint a BlogToken with a known label, post with it, assert the
    identity equals the label."""
    from app.repositories.blog_post_repo import BlogTokenRepository

    repo = BlogTokenRepository(db)
    token = await repo.create(label="weekly-newsletter")
    await db.commit()

    r = await anonymous_client.post(
        "/api/v1/public/blog",
        json={
            "title": "Issue 1",
            "content": "...",
            "summary": "",
            "identity": "i-am-someone-else",  # lie — must be ignored
            "token": token.token,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["identity"] == "weekly-newsletter", body


@pytest.mark.asyncio
async def test_blog_post_admin_login_uses_compare_digest(anonymous_client):
    """D06 also tightens the admin_secret compare to hmac.compare_digest.
    A wrong admin_secret must still 403."""
    r = await anonymous_client.post(
        "/api/v1/public/blog",
        json={
            "title": "ignored",
            "content": "ignored",
            "summary": "",
            "identity": "ignored",
            "admin_secret": "wrong-secret",
        },
    )
    assert r.status_code == 403
