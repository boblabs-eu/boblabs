"""Bob Manager — Access Token and Trial Request repository."""

import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access_token import AccessToken, QuoteRequest, TrialRequest


class AccessTokenRepository:
    """Data access layer for access tokens."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self) -> list[AccessToken]:
        result = await self.db.execute(
            select(AccessToken).order_by(AccessToken.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, token_id: UUID) -> AccessToken | None:
        result = await self.db.execute(
            select(AccessToken).where(AccessToken.id == token_id)
        )
        return result.scalar_one_or_none()

    async def get_by_token(self, token: str) -> AccessToken | None:
        result = await self.db.execute(
            select(AccessToken).where(AccessToken.token == token)
        )
        return result.scalar_one_or_none()

    async def create(self, label: str, email: str, expires_at: datetime) -> AccessToken:
        token_value = f"bob_{secrets.token_urlsafe(32)}"
        access_token = AccessToken(
            token=token_value,
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
        """Return the token if it is valid, not expired, and not revoked."""
        record = await self.get_by_token(token)
        if not record:
            return None
        if record.revoked:
            return None
        if record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            return None
        return record


class TrialRequestRepository:
    """Data access layer for trial requests."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self) -> list[TrialRequest]:
        result = await self.db.execute(
            select(TrialRequest).order_by(TrialRequest.created_at.desc())
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

    async def get_all(self) -> list[QuoteRequest]:
        result = await self.db.execute(
            select(QuoteRequest).order_by(QuoteRequest.created_at.desc())
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
