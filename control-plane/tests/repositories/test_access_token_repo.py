"""AccessTokenRepository — token hash dual-read + pagination prep."""

from __future__ import annotations

import uuid

import pytest
from app.repositories.access_token_repo import AccessTokenRepository

pytestmark = pytest.mark.repo


@pytest.mark.asyncio
async def test_repo_instantiates(db):
    """Smoke: the repo can be constructed against a real session."""
    repo = AccessTokenRepository(db)
    assert repo is not None


def test_get_all_method_has_limit_param():
    """P04 (shipped Session 2): list method exposes limit/offset paginators."""
    import inspect

    members = [m for m in dir(AccessTokenRepository) if m.startswith(("get_all", "list_"))]
    assert members, "AccessTokenRepository exposes no list method"
    for m in members:
        fn = getattr(AccessTokenRepository, m)
        sig = inspect.signature(fn)
        assert "limit" in sig.parameters, (
            f"AccessTokenRepository.{m} regressed — `limit` parameter removed"
        )
        assert "offset" in sig.parameters, (
            f"AccessTokenRepository.{m} regressed — `offset` parameter removed"
        )
