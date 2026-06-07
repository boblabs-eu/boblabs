"""Bob Manager — Access Token and Trial Request repository."""

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access_token import AccessToken, QuoteRequest, TrialRequest
from app.repositories._paginate import MAX_LIMIT, clamp_limit


def _hash_token(token: str) -> str:
    """SHA-256 hex of the plaintext token (cluster K)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AccessTokenRepository:
    """Data access layer for access tokens."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self, limit: int = MAX_LIMIT, offset: int = 0) -> list[AccessToken]:
        # P04 — cap unbounded scan; admin token UI shows ~20 at a time.
        result = await self.db.execute(
            select(AccessToken)
            .order_by(AccessToken.created_at.desc())
            .limit(clamp_limit(limit))
            .offset(max(0, offset))
        )
        return list(result.scalars().all())

    async def get_by_id(self, token_id: UUID) -> AccessToken | None:
        result = await self.db.execute(
            select(AccessToken).where(AccessToken.id == token_id)
        )
        return result.scalar_one_or_none()

    async def get_by_token(self, token: str) -> AccessToken | None:
        """Lookup by token. Cluster K — prefer the hash index; fall back
        to the plaintext path during the dual-read deprecation window so
        tokens issued before migration 0006 keep working."""
        digest = _hash_token(token)
        result = await self.db.execute(
            select(AccessToken).where(AccessToken.token_hash == digest)
        )
        record = result.scalar_one_or_none()
        if record is not None:
            return record
        # Dual-read fallback. Will be removed once the deprecation window
        # closes and we drop the plaintext column.
        result = await self.db.execute(
            select(AccessToken).where(AccessToken.token == token)
        )
        return result.scalar_one_or_none()

    async def create(self, label: str, email: str, expires_at: datetime) -> AccessToken:
        token_value = f"bob_{secrets.token_urlsafe(32)}"
        access_token = AccessToken(
            token=token_value,
            token_hash=_hash_token(token_value),
            label=label,
            email=email,
            expires_at=expires_at,
        )
        self.db.add(access_token)
        await self.db.flush()
        await self.db.refresh(access_token)
        return access_token

    async def revoke(self, token_id: UUID) -> bool:
        token = await self.get_by_id(token_id)
        if token:
            await self.db.execute(
                update(AccessToken)
                .where(AccessToken.id == token_id)
                .values(revoked=True)
            )
            await self.db.flush()
            return True
        return False

    async def validate(self, token: str) -> AccessToken | None:
        """Return the token if it is valid, not expired, and not revoked.

        Cluster K — Constant-time secondary check via hmac.compare_digest
        on top of the indexed token_hash lookup so a successful index
        hit can't be distinguished from a near-miss by timing.
        """
        record = await self.get_by_token(token)
        if not record:
            return None
        if record.revoked:
            return None
        if record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            return None
        # Defence-in-depth: ensure the row's plaintext (or hash) actually
        # matches the presented token. Index lookups should never return
        # a mismatched row, but compare in constant time anyway.
        if record.token_hash:
            if not hmac.compare_digest(record.token_hash, _hash_token(token)):
                return None
        elif record.token:
            if not hmac.compare_digest(record.token, token):
                return None
        return record


class TrialRequestRepository:
    """Data access layer for trial requests."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self, limit: int = MAX_LIMIT, offset: int = 0) -> list[TrialRequest]:
        # P04 — cap unbounded scan.
        result = await self.db.execute(
            select(TrialRequest)
            .order_by(TrialRequest.created_at.desc())
            .limit(clamp_limit(limit))
            .offset(max(0, offset))
        )
        return list(result.scalars().all())

    async def get_by_id(self, request_id: UUID) -> TrialRequest | None:
        result = await self.db.execute(
            select(TrialRequest).where(TrialRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    async def create(self, name: str, email: str, enterprise: str, role: str, purpose: str) -> TrialRequest:
        trial_request = TrialRequest(
            name=name,
            email=email,
            enterprise=enterprise,
            role=role,
            purpose=purpose,
        )
        self.db.add(trial_request)
        await self.db.flush()
        await self.db.refresh(trial_request)
        return trial_request

    async def update_status(self, request_id: UUID, status: str) -> TrialRequest | None:
        await self.db.execute(
            update(TrialRequest)
            .where(TrialRequest.id == request_id)
            .values(status=status)
        )
        await self.db.flush()
        return await self.get_by_id(request_id)


class QuoteRequestRepository:
    """Data access layer for quote requests."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self, limit: int = MAX_LIMIT, offset: int = 0) -> list[QuoteRequest]:
        # P04 — cap unbounded scan.
        result = await self.db.execute(
            select(QuoteRequest)
            .order_by(QuoteRequest.created_at.desc())
            .limit(clamp_limit(limit))
            .offset(max(0, offset))
        )
        return list(result.scalars().all())

    async def get_by_id(self, request_id: UUID) -> QuoteRequest | None:
        result = await self.db.execute(
            select(QuoteRequest).where(QuoteRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self, name: str, email: str, company: str, phone: str, plan: str, description: str,
    ) -> QuoteRequest:
        quote_request = QuoteRequest(
            name=name,
            email=email,
            company=company,
            phone=phone,
            plan=plan,
            description=description,
        )
        self.db.add(quote_request)
        await self.db.flush()
        await self.db.refresh(quote_request)
        return quote_request

    async def update_status(self, request_id: UUID, status: str) -> QuoteRequest | None:
        await self.db.execute(
            update(QuoteRequest)
            .where(QuoteRequest.id == request_id)
            .values(status=status)
        )
        await self.db.flush()
        return await self.get_by_id(request_id)
