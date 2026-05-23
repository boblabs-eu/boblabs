"""Bob Manager — Lab-scoped tracked-wallet access service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.web3_repo import LabWeb3AccessRepository
from app.services.web3_service import get_wallet_record, list_wallets


async def augment_tool_names_with_web3_access(
    db: AsyncSession, lab_id: UUID, tool_names: list[str] | None
) -> list[str]:
    """Auto-add or strip tracked-wallet tool access based on lab grants."""
    original = tool_names or []
    explicit = [
        name for name in original
        if name == "web3_portfolio" or name.startswith("web3_portfolio:")
    ]
    base = [
        name for name in original
        if name != "web3_portfolio" and not name.startswith("web3_portfolio:")
    ]

    access_repo = LabWeb3AccessRepository(db)
    if await access_repo.has_any_access(lab_id):
        base.extend(explicit or ["web3_portfolio"])

    return list(dict.fromkeys(base))


class Web3AccessService:
    """Service for lab-scoped tracked-wallet access management."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.access = LabWeb3AccessRepository(db)

    async def list_lab_access(self, lab_id: UUID) -> list[dict]:
        rows = await self.access.get_by_lab(lab_id)
        return [
            {
                "id": str(entry.id),
                "lab_id": str(entry.lab_id),
                "wallet_id": str(wallet.id),
                "address": wallet.address,
                "label": wallet.label,
                "can_read": entry.can_read,
                "created_at": entry.created_at,
            }
            for entry, wallet in rows
        ]

    async def list_candidate_wallets(self, user: dict) -> list[dict]:
        wallets = await list_wallets(self.db, user=user)
        return [
            {
                "wallet_id": wallet["id"],
                "address": wallet["address"],
                "label": wallet["label"],
                "created_at": wallet["created_at"],
            }
            for wallet in wallets
        ]

    async def grant_lab_access(self, lab_id: UUID, wallet_ids: list[UUID]) -> list[dict]:
        granted: list[dict] = []
        for wallet_id in dict.fromkeys(wallet_ids):
            wallet = await get_wallet_record(self.db, wallet_id)
            if wallet is None:
                raise ValueError(f"Wallet {wallet_id} not found")

            entry = await self.access.get_entry(lab_id, wallet.id)
            if entry is None:
                entry = await self.access.create(
                    lab_id=lab_id,
                    wallet_id=wallet.id,
                    can_read=True,
                )
            elif not entry.can_read:
                entry = await self.access.update(lab_id, wallet.id, can_read=True)

            granted.append(
                {
                    "id": str(entry.id),
                    "lab_id": str(entry.lab_id),
                    "wallet_id": str(wallet.id),
                    "address": wallet.address,
                    "label": wallet.label,
                    "can_read": entry.can_read,
                    "created_at": entry.created_at,
                }
            )
        return granted

    async def revoke_lab_access(self, lab_id: UUID, wallet_id: UUID) -> bool:
        deleted = await self.access.delete(lab_id, wallet_id)
        return deleted > 0

    async def get_lab_wallet_ids(self, lab_id: UUID) -> list[UUID]:
        return await self.access.list_wallet_ids(lab_id)