"""Bob Manager — Web3 API routes (crypto prices, wallet tracker, tx history, portfolio history)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.database import get_db
from app.services.authorization import Permission
from app.services.web3_service import (
    add_wallet,
    cleanup_old_snapshots,
    get_crypto_prices,
    get_portfolio_history,
    get_portfolio_total,
    get_wallet_balances,
    get_wallet_for_user,
    get_wallet_token_transfers,
    get_wallet_transactions,
    get_web3_settings,
    list_wallets,
    record_portfolio_snapshot,
    remove_wallet,
    update_web3_settings,
)

router = APIRouter(prefix="/web3", tags=["web3"])


def _require_admin(user: dict) -> None:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


# ─── Schemas ─────────────────────────────────────


class WalletCreate(BaseModel):
    address: str
    label: str = ""


class SettingsUpdate(BaseModel):
    refresh_interval: Optional[int] = None
    retention_full_hours: Optional[int] = None
    retention_step_hours: Optional[int] = None


# ─── Prices ──────────────────────────────────────


@router.get("/prices")
async def prices():
    """Get live BTC, ETH, BNB prices from CoinGecko."""
    data = await get_crypto_prices()
    if not data:
        raise HTTPException(status_code=502, detail="Failed to fetch crypto prices")
    return data


@router.get("/portfolio")
async def portfolio(db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    """Get total portfolio value across all tracked wallets."""
    return await get_portfolio_total(db, user=user)


# ─── Settings ────────────────────────────────────


@router.get("/settings")
async def settings_get(db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    """Get user-configurable Web3 settings."""
    _require_admin(user)
    return await get_web3_settings(db)


@router.put("/settings")
async def settings_update(
    body: SettingsUpdate, db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)
):
    """Update Web3 settings (refresh_interval, retention_full_hours, retention_step_hours)."""
    _require_admin(user)
    return await update_web3_settings(
        db,
        refresh_interval=body.refresh_interval,
        retention_full_hours=body.retention_full_hours,
        retention_step_hours=body.retention_step_hours,
    )


# ─── Wallets CRUD ────────────────────────────────


@router.get("/wallets")
async def wallets_list(db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    """List all tracked wallets the user can see."""
    return await list_wallets(db, user=user)


@router.post("/wallets", status_code=201)
async def wallets_add(
    body: WalletCreate, db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)
):
    """Add a wallet address to track."""
    try:
        wallet = await add_wallet(db, body.address, body.label, user=user)
        return wallet
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/wallets/{wallet_id}")
async def wallets_remove(
    wallet_id: str, db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)
):
    """Remove a tracked wallet."""
    removed = await remove_wallet(db, wallet_id, user=user)
    if not removed:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return {"status": "deleted"}


# ─── Wallet Balances ─────────────────────────────


@router.get("/wallets/{wallet_id}/balances")
async def wallet_balances(
    wallet_id: str, db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)
):
    """Get native balances for a wallet across all chains."""
    wallet = await get_wallet_for_user(db, wallet_id, user, permission=Permission.VIEW)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    balances = await get_wallet_balances(wallet.address)
    return {
        "wallet_id": str(wallet.id),
        "address": wallet.address,
        "label": wallet.label,
        "chains": balances,
    }


# ─── Transaction History ─────────────────────────


@router.get("/wallets/{wallet_id}/transactions")
async def wallet_transactions(
    wallet_id: str,
    chain: str = Query("ethereum", description="Chain ID: ethereum, base, bnb"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get recent transactions for a wallet on a specific chain."""
    wallet = await get_wallet_for_user(db, wallet_id, user, permission=Permission.VIEW)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    txns = await get_wallet_transactions(wallet.address, chain)
    transfers = await get_wallet_token_transfers(wallet.address, chain)

    return {
        "wallet_id": str(wallet.id),
        "address": wallet.address,
        "chain": chain,
        "transactions": txns,
        "token_transfers": transfers,
    }


# ─── Portfolio History (time-series) ─────────────


@router.get("/portfolio/history")
async def portfolio_history(
    wallet_id: Optional[str] = Query(None, description="Filter by wallet UUID"),
    hours: int = Query(24, ge=1, le=8760, description="How many hours of history"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get portfolio value history for charting."""
    return await get_portfolio_history(db, wallet_id=wallet_id, hours=hours, user=user)


@router.post("/portfolio/snapshot")
async def portfolio_snapshot(
    db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)
):
    """Manually trigger a portfolio snapshot."""
    _require_admin(user)
    return await record_portfolio_snapshot(db)


@router.post("/portfolio/cleanup")
async def portfolio_cleanup(
    db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)
):
    """Manually trigger old snapshot cleanup/downsampling."""
    _require_admin(user)
    return await cleanup_old_snapshots(db)
