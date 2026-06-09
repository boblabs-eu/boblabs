"""Bob Manager — Web3 service: crypto prices, wallet balances, tx history, portfolio snapshots."""

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import httpx
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.wallet import Wallet
from app.models.web3_settings import Web3Settings
from app.services.authorization import (
    Permission,
    check_permission,
    filter_query_by_access,
    get_default_acl,
)

logger = logging.getLogger(__name__)

TIMEOUT = 15.0

# ── Simple in-memory caches ──
#
# P10 — these process-local dicts are correct ONLY under the single-worker
# invariant enforced at startup (cluster N: `assert WORKERS == 1` in
# main.py). If we ever bump the worker count we must move at least
# ``_portfolio_cache`` and ``_wallet_chain_cache`` to a shared store
# (Redis) — otherwise two workers will serve stale, divergent snapshots
# of the same wallet to two requests in the same second. Price cache is
# tolerable to fork because the upstream rate limit dominates the TTL.
_price_cache: dict = {"data": {}, "ts": 0}
_PRICE_TTL = 60  # seconds
_portfolio_cache: dict[str, dict] = {}
_PORTFOLIO_TTL = 300  # 5 minutes
_wallet_chain_cache: dict[str, dict] = {}

_FETCH_RETRIES = 3
_CHAIN_CACHE_TTL = 1800  # 30 minutes
_MAX_TRANSIENT_FAILURES = 2

# ── Chain configurations ──
CHAINS = {
    "ethereum": {
        "name": "Ethereum",
        "symbol": "ETH",
        "rpc": "https://eth.llamarpc.com",
        "coingecko_id": "ethereum",
        "decimals": 18,
        "explorer": "https://etherscan.io/address/",
        "blockscout": "https://eth.blockscout.com",
    },
    "base": {
        "name": "Base",
        "symbol": "ETH",
        "rpc": "https://mainnet.base.org",
        "coingecko_id": "ethereum",  # Base uses ETH as native
        "decimals": 18,
        "explorer": "https://basescan.org/address/",
        "blockscout": "https://base.blockscout.com",
    },
    "bnb": {
        "name": "BNB Chain",
        "symbol": "BNB",
        "rpc": "https://bsc-dataseed.binance.org",
        "coingecko_id": "binancecoin",
        "decimals": 18,
        "explorer": "https://bscscan.com/address/",
        "blockscout": "https://bsc.blockscout.com",
    },
}


# ─── Crypto Prices ───────────────────────────────


async def get_crypto_prices() -> dict:
    """Fetch BTC, ETH, BNB prices with 24h/7d/30d/1y changes from CoinGecko."""
    global _price_cache
    now = time.time()
    if _price_cache["data"] and now - _price_cache["ts"] < _PRICE_TTL:
        return _price_cache["data"]

    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "ids": "bitcoin,ethereum,binancecoin",
        "price_change_percentage": "24h,7d,30d,1y",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            result = {}
            for coin in data:
                result[coin["id"]] = {
                    "price": coin.get("current_price"),
                    "market_cap": coin.get("market_cap"),
                    "change_24h": coin.get("price_change_percentage_24h"),
                    "change_7d": coin.get("price_change_percentage_7d_in_currency"),
                    "change_30d": coin.get("price_change_percentage_30d_in_currency"),
                    "change_1y": coin.get("price_change_percentage_1y_in_currency"),
                }
            _price_cache = {"data": result, "ts": now}
            return result
    except httpx.HTTPError as e:
        logger.error("Failed to fetch crypto prices: %s", e)
        return _price_cache.get("data") or {}


# ─── Wallet Balance ──────────────────────────────


async def _get_native_balance_once(rpc_url: str, address: str) -> Optional[int]:
    """Call eth_getBalance via JSON-RPC."""
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getBalance",
        "params": [address, "latest"],
        "id": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(rpc_url, json=payload)
            resp.raise_for_status()
            result = resp.json().get("result")
            if result:
                return int(result, 16)
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("RPC error for %s on %s: %s", address, rpc_url, e)
    return None


async def _get_native_balance(rpc_url: str, address: str) -> Optional[int]:
    """Fetch native balance with lightweight retries for flaky RPC endpoints."""
    for _ in range(_FETCH_RETRIES):
        balance = await _get_native_balance_once(rpc_url, address)
        if balance is not None:
            return balance
    return None


async def _fetch_token_balances_once(
    blockscout_url: Optional[str], address: str
) -> list[dict] | None:
    """Fetch ERC-20 token balances from Blockscout API.

    Only returns tokens whose USD value > 0 (filters out scams / dust).
    """
    if not blockscout_url:
        return []
    url = f"{blockscout_url}/api/v2/addresses/{address}/token-balances"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "BobManager/1.0"})
            resp.raise_for_status()
            data = resp.json()
            tokens = []
            for item in data:
                token = item.get("token", {})
                if token.get("type") != "ERC-20":
                    continue
                raw_value = item.get("value", "0")
                decimals = int(token.get("decimals") or 18)
                exchange_rate = token.get("exchange_rate")

                balance = float(Decimal(int(raw_value)) / Decimal(10**decimals))

                usd_value = 0.0
                if exchange_rate:
                    try:
                        usd_value = round(balance * float(exchange_rate), 2)
                    except (ValueError, TypeError):
                        usd_value = 0.0

                # Only include tokens with value > $0
                if usd_value > 0:
                    tokens.append(
                        {
                            "name": token.get("name", "Unknown"),
                            "symbol": token.get("symbol", "???"),
                            "balance": round(balance, 6),
                            "value_usd": usd_value,
                            "contract": token.get("address", ""),
                            "icon_url": token.get("icon_url"),
                        }
                    )
            tokens.sort(key=lambda t: t["value_usd"], reverse=True)
            return tokens
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        logger.warning("Failed to fetch tokens from %s: %s", blockscout_url, e)
        return None


async def _fetch_token_balances(
    blockscout_url: Optional[str], address: str
) -> tuple[list[dict], bool]:
    """Fetch token balances with retries.

    Returns (tokens, ok) where ok=False means every upstream attempt failed.
    """
    if not blockscout_url:
        return [], True

    for _ in range(_FETCH_RETRIES):
        tokens = await _fetch_token_balances_once(blockscout_url, address)
        if tokens is not None:
            return tokens, True

    return [], False


def _wallet_chain_cache_key(chain_id: str, address: str) -> str:
    return f"{chain_id}:{address.lower()}"


def _cache_is_fresh(ts: float | None) -> bool:
    return bool(ts) and (time.time() - ts) < _CHAIN_CACHE_TTL


async def _get_chain_value(chain_id: str, address: str, prices: dict) -> dict:
    """Return resilient per-chain wallet valuation.

    Upstream RPC and Blockscout responses can intermittently return null/empty data.
    To avoid fake portfolio cliffs, reuse the last known good chain component for a small
    number of consecutive transient failures.
    """
    chain = CHAINS[chain_id]
    cache_key = _wallet_chain_cache_key(chain_id, address)
    cached = _wallet_chain_cache.get(cache_key, {})
    now = time.time()

    native_balance_wei = await _get_native_balance(chain["rpc"], address)
    native_failures = 0
    if native_balance_wei is None:
        cached_native = cached.get("native_balance_wei")
        cached_native_failures = int(cached.get("native_failures", 0))
        if (
            cached_native is not None
            and _cache_is_fresh(cached.get("native_ts"))
            and cached_native_failures < _MAX_TRANSIENT_FAILURES
        ):
            native_balance_wei = cached_native
            native_failures = cached_native_failures + 1
            logger.info(
                "Using cached native balance for %s on %s after transient fetch failure",
                address,
                chain_id,
            )

    tokens, token_fetch_ok = await _fetch_token_balances(chain.get("blockscout"), address)
    tokens_value = round(sum(t["value_usd"] for t in tokens), 2)
    token_failures = 0
    cached_tokens_value = float(cached.get("tokens_value_usd", 0.0) or 0.0)
    cached_token_failures = int(cached.get("token_failures", 0))
    if (
        (not token_fetch_ok or (not tokens and cached_tokens_value > 0))
        and cached_tokens_value > 0
        and _cache_is_fresh(cached.get("tokens_ts"))
        and cached_token_failures < _MAX_TRANSIENT_FAILURES
    ):
        tokens = cached.get("tokens", [])
        tokens_value = cached_tokens_value
        token_failures = cached_token_failures + 1
        logger.info(
            "Using cached token balances for %s on %s after transient fetch failure",
            address,
            chain_id,
        )

    if native_balance_wei is not None:
        balance = float(Decimal(native_balance_wei) / Decimal(10 ** chain["decimals"]))
        price = (prices.get(chain["coingecko_id"]) or {}).get("price") or 0
        native_usd = round(balance * price, 2)
    else:
        balance = None
        native_usd = None

    if native_balance_wei is not None and native_failures == 0:
        cached["native_balance_wei"] = native_balance_wei
        cached["native_ts"] = now
    cached["native_failures"] = native_failures

    if token_failures == 0:
        cached["tokens"] = tokens
        cached["tokens_value_usd"] = tokens_value
        cached["tokens_ts"] = now
    cached["token_failures"] = token_failures
    _wallet_chain_cache[cache_key] = cached

    if balance is not None:
        return {
            "chain": chain["name"],
            "symbol": chain["symbol"],
            "balance": round(balance, 6),
            "value_usd": native_usd,
            "tokens": tokens,
            "tokens_value_usd": tokens_value,
            "total_value_usd": round((native_usd or 0) + tokens_value, 2),
            "explorer_url": f"{chain['explorer']}{address}",
        }

    return {
        "chain": chain["name"],
        "symbol": chain["symbol"],
        "balance": None,
        "value_usd": None,
        "tokens": tokens,
        "tokens_value_usd": tokens_value,
        "total_value_usd": tokens_value,
        "explorer_url": f"{chain['explorer']}{address}",
    }


async def get_wallet_balances(address: str) -> dict:
    """Get native balances + ERC-20 tokens for an address across all chains."""
    result = {}
    prices = await get_crypto_prices()

    for chain_id, _chain in CHAINS.items():
        result[chain_id] = await _get_chain_value(chain_id, address, prices)

    return result


def _portfolio_cache_key(user: dict | None) -> str | None:
    """Return a safe cache key for portfolio totals."""
    if user is None or user.get("role") == "admin":
        return "__all__"
    return None


async def get_wallet_record(db: AsyncSession, wallet_id: str | uuid.UUID) -> Wallet | None:
    """Fetch a tracked wallet by ID."""
    try:
        uid = wallet_id if isinstance(wallet_id, uuid.UUID) else uuid.UUID(str(wallet_id))
    except (ValueError, TypeError):
        return None

    result = await db.execute(select(Wallet).where(Wallet.id == uid))
    return result.scalar_one_or_none()


async def get_wallet_for_user(
    db: AsyncSession,
    wallet_id: str | uuid.UUID,
    user: dict,
    permission: Permission = Permission.VIEW,
) -> Wallet | None:
    """Fetch a tracked wallet and enforce ACL for the requesting user."""
    wallet = await get_wallet_record(db, wallet_id)
    if wallet is None:
        return None
    check_permission(user, wallet.acl, permission)
    return wallet


# ─── Portfolio Total ─────────────────────────────


async def get_portfolio_total(db: AsyncSession, user: dict | None = None) -> dict:
    """Compute total portfolio value across all tracked wallets (cached)."""
    global _portfolio_cache
    now = time.time()
    cache_key = _portfolio_cache_key(user)
    if cache_key:
        cached = _portfolio_cache.get(cache_key)
        if cached and now - cached["ts"] < _PORTFOLIO_TTL:
            return cached["data"]

    wallets = await list_wallets(db, user=user)
    total = 0.0
    prices = await get_crypto_prices()

    for wallet_data in wallets:
        address = wallet_data["address"]
        for chain_id in CHAINS:
            chain_value = await _get_chain_value(chain_id, address, prices)
            total += chain_value.get("total_value_usd") or 0

    result = {"total_value_usd": round(total, 2), "wallet_count": len(wallets)}
    if cache_key:
        _portfolio_cache[cache_key] = {"data": result, "ts": now}
    return result


async def list_wallets(db: AsyncSession, user: dict | None = None) -> list[dict]:
    """List all tracked wallets the user can see."""
    query = select(Wallet).order_by(Wallet.created_at.desc())
    if user:
        query = filter_query_by_access(query, Wallet, user)
    result = await db.execute(query)
    wallets = result.scalars().all()
    return [
        {
            "id": str(w.id),
            "address": w.address,
            "label": w.label,
            "acl": w.acl,
            "created_at": w.created_at.isoformat() if w.created_at else None,
        }
        for w in wallets
    ]


async def add_wallet(
    db: AsyncSession, address: str, label: str = "", user: dict | None = None
) -> dict:
    """Add a wallet address to track."""
    address = address.strip().lower()
    if not address.startswith("0x") or len(address) != 42:
        raise ValueError("Invalid EVM address — must be 42-character hex starting with 0x")

    # Check duplicate
    existing = await db.execute(select(Wallet).where(Wallet.address == address))
    if existing.scalar_one_or_none():
        raise ValueError(f"Wallet {address} is already tracked")

    acl = get_default_acl(user.get("sub", "admin")) if user else get_default_acl("admin")
    wallet = Wallet(id=uuid.uuid4(), address=address, label=label, acl=acl)
    db.add(wallet)
    await db.flush()
    return {
        "id": str(wallet.id),
        "address": wallet.address,
        "label": wallet.label,
        "created_at": wallet.created_at.isoformat() if wallet.created_at else None,
    }


async def remove_wallet(db: AsyncSession, wallet_id: str, user: dict | None = None) -> bool:
    """Remove a tracked wallet by ID."""
    if user is not None:
        wallet = await get_wallet_for_user(db, wallet_id, user, permission=Permission.DELETE)
        if wallet is None:
            return False
        uid = wallet.id
    else:
        uid = uuid.UUID(wallet_id)
    result = await db.execute(delete(Wallet).where(Wallet.id == uid))
    return result.rowcount > 0


# ─── Transaction History ─────────────────────────


async def get_wallet_transactions(address: str, chain_id: str = "ethereum") -> list[dict]:
    """Fetch recent transactions for an address from Blockscout."""
    chain = CHAINS.get(chain_id)
    if not chain or not chain.get("blockscout"):
        return []

    blockscout = chain["blockscout"]
    url = f"{blockscout}/api/v2/addresses/{address}/transactions"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(
                url,
                params={"type": "all"},
                headers={"User-Agent": "BobManager/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", data) if isinstance(data, dict) else data
            txns = []
            for tx in items[:100]:  # cap at 100 most recent
                value_wei = int(tx.get("value", "0") or "0")
                value = float(Decimal(value_wei) / Decimal(10**18))
                fee_wei = (
                    int(tx.get("fee", {}).get("value", "0") or "0")
                    if isinstance(tx.get("fee"), dict)
                    else int(tx.get("fee", "0") or "0")
                )
                fee = float(Decimal(fee_wei) / Decimal(10**18))
                txns.append(
                    {
                        "hash": tx.get("hash", ""),
                        "block": tx.get("block", tx.get("block_number")),
                        "timestamp": tx.get("timestamp"),
                        "from": tx.get("from", {}).get("hash", "")
                        if isinstance(tx.get("from"), dict)
                        else tx.get("from", ""),
                        "to": tx.get("to", {}).get("hash", "")
                        if isinstance(tx.get("to"), dict)
                        else tx.get("to", ""),
                        "value": round(value, 6),
                        "fee": round(fee, 6),
                        "symbol": chain["symbol"],
                        "status": tx.get("status"),
                        "method": tx.get(
                            "method",
                            tx.get("decoded_input", {}).get("method_call", "")
                            if isinstance(tx.get("decoded_input"), dict)
                            else "",
                        ),
                        "tx_types": tx.get("tx_types", []),
                    }
                )
            return txns
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        logger.warning("Failed to fetch transactions for %s on %s: %s", address, chain_id, e)
        return []


async def get_wallet_token_transfers(address: str, chain_id: str = "ethereum") -> list[dict]:
    """Fetch ERC-20 token transfers for an address from Blockscout."""
    chain = CHAINS.get(chain_id)
    if not chain or not chain.get("blockscout"):
        return []

    blockscout = chain["blockscout"]
    url = f"{blockscout}/api/v2/addresses/{address}/token-transfers"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(
                url,
                params={"type": "ERC-20"},
                headers={"User-Agent": "BobManager/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", data) if isinstance(data, dict) else data
            transfers = []
            for t in items[:100]:
                token = t.get("token", {})
                decimals = int(token.get("decimals") or 18)
                raw = int(
                    t.get("total", {}).get("value", "0")
                    if isinstance(t.get("total"), dict)
                    else t.get("value", "0") or "0"
                )
                amount = float(Decimal(raw) / Decimal(10**decimals))
                transfers.append(
                    {
                        "hash": t.get("tx_hash", ""),
                        "timestamp": t.get("timestamp"),
                        "from": t.get("from", {}).get("hash", "")
                        if isinstance(t.get("from"), dict)
                        else t.get("from", ""),
                        "to": t.get("to", {}).get("hash", "")
                        if isinstance(t.get("to"), dict)
                        else t.get("to", ""),
                        "token_symbol": token.get("symbol", "???"),
                        "token_name": token.get("name", ""),
                        "amount": round(amount, 6),
                        "method": t.get("method", ""),
                    }
                )
            return transfers
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        logger.warning("Failed to fetch token transfers for %s on %s: %s", address, chain_id, e)
        return []


# ─── Web3 Settings ───────────────────────────────


async def get_web3_settings(db: AsyncSession) -> dict:
    """Return the singleton settings row (create if missing)."""
    result = await db.execute(select(Web3Settings).where(Web3Settings.id == 1))
    row = result.scalar_one_or_none()
    if row is None:
        row = Web3Settings(id=1)
        db.add(row)
        await db.flush()
    return {
        "refresh_interval": row.refresh_interval,
        "retention_full_hours": row.retention_full_hours,
        "retention_step_hours": row.retention_step_hours,
    }


async def update_web3_settings(
    db: AsyncSession,
    refresh_interval: Optional[int] = None,
    retention_full_hours: Optional[int] = None,
    retention_step_hours: Optional[int] = None,
) -> dict:
    """Update user-configurable Web3 settings."""
    result = await db.execute(select(Web3Settings).where(Web3Settings.id == 1))
    row = result.scalar_one_or_none()
    if row is None:
        row = Web3Settings(id=1)
        db.add(row)
        await db.flush()
        await db.refresh(row)

    if refresh_interval is not None:
        row.refresh_interval = max(60, refresh_interval)  # floor: 1 min
    if retention_full_hours is not None:
        row.retention_full_hours = max(1, retention_full_hours)
    if retention_step_hours is not None:
        row.retention_step_hours = max(1, retention_step_hours)

    await db.flush()
    return {
        "refresh_interval": row.refresh_interval,
        "retention_full_hours": row.retention_full_hours,
        "retention_step_hours": row.retention_step_hours,
    }


# ─── Portfolio Snapshot Recording ────────────────


async def record_portfolio_snapshot(db: AsyncSession) -> dict:
    """Record a value snapshot for every tracked wallet right now."""
    wallets = await list_wallets(db)
    if not wallets:
        return {"recorded": 0}

    prices = await get_crypto_prices()
    now = datetime.now(timezone.utc)
    count = 0

    for w in wallets:
        address = w["address"]
        total = 0.0
        breakdown = {}

        for chain_id in CHAINS:
            chain_value = await _get_chain_value(chain_id, address, prices)
            chain_val = round(chain_value.get("value_usd") or 0, 2)
            tokens = chain_value.get("tokens") or []
            tokens_val = round(chain_value.get("tokens_value_usd") or 0, 2)
            chain_total = round(chain_value.get("total_value_usd") or 0, 2)
            total += chain_total

            breakdown[chain_id] = {
                "native_usd": chain_val,
                "tokens_usd": tokens_val,
                "total_usd": chain_total,
                "tokens": [
                    {"symbol": t["symbol"], "value_usd": t["value_usd"]} for t in tokens[:20]
                ],
            }

        snap = PortfolioSnapshot(
            ts=now,
            wallet_id=uuid.UUID(w["id"]),
            wallet_address=address,
            wallet_label=w.get("label", ""),
            total_value_usd=round(total, 2),
            breakdown=breakdown,
        )
        db.add(snap)
        count += 1

    await db.flush()
    _portfolio_cache.clear()
    return {"recorded": count, "ts": now.isoformat()}


# ─── Portfolio History Queries ───────────────────


async def get_portfolio_history(
    db: AsyncSession,
    wallet_id: Optional[str] = None,
    hours: int = 24,
    user: dict | None = None,
) -> list[dict]:
    """Return time-series of portfolio value. Optionally filter by wallet."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    if wallet_id:
        if user is not None:
            wallet = await get_wallet_for_user(db, wallet_id, user, permission=Permission.VIEW)
            if wallet is None:
                return []
            uid = wallet.id
        else:
            uid = uuid.UUID(wallet_id)
        stmt = (
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.wallet_id == uid, PortfolioSnapshot.ts >= since)
            .order_by(PortfolioSnapshot.ts.asc())
        )
    else:
        stmt = (
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.ts >= since)
            .order_by(PortfolioSnapshot.ts.asc())
        )
        if user is not None:
            visible_wallets = await list_wallets(db, user=user)
            wallet_ids = [uuid.UUID(wallet["id"]) for wallet in visible_wallets]
            if not wallet_ids:
                return []
            stmt = stmt.where(PortfolioSnapshot.wallet_id.in_(wallet_ids))

    result = await db.execute(stmt)
    rows = result.scalars().all()

    if wallet_id:
        return [
            {
                "ts": r.ts.isoformat(),
                "wallet_id": str(r.wallet_id),
                "wallet_label": r.wallet_label,
                "total_value_usd": float(r.total_value_usd),
                "breakdown": r.breakdown,
            }
            for r in rows
        ]

    # Aggregate across wallets per timestamp
    from collections import defaultdict

    buckets = defaultdict(lambda: {"total": 0.0, "wallets": {}})
    for r in rows:
        key = r.ts.isoformat()
        total_value = float(r.total_value_usd)
        buckets[key]["total"] += total_value
        buckets[key]["wallets"][str(r.wallet_id)] = {
            "label": r.wallet_label,
            "value": total_value,
        }

    return [
        {"ts": ts, "total_value_usd": round(v["total"], 2), "wallets": v["wallets"]}
        for ts, v in sorted(buckets.items())
    ]


# ─── Data Retention / Downsampling ───────────────


async def cleanup_old_snapshots(db: AsyncSession) -> dict:
    """Downsample and delete old snapshot data according to settings."""
    settings = await get_web3_settings(db)
    retention_hours = settings["retention_full_hours"]
    step_hours = settings["retention_step_hours"]

    cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)

    # For data older than cutoff, keep only one row per wallet per step_hours bucket.
    # We do this by: for each wallet, among rows older than cutoff,
    # keep the first row in each time-bucket, delete the rest.
    deleted = 0
    try:
        # Use a CTE to mark rows to keep (first per bucket)
        # This works with or without TimescaleDB
        sql = text("""
            DELETE FROM portfolio_snapshots
            WHERE ts < :cutoff
              AND (ts, wallet_id) NOT IN (
                SELECT DISTINCT ON (wallet_id, time_bucket)
                    ts, wallet_id
                FROM (
                    SELECT ts, wallet_id,
                           date_trunc('hour', ts) +
                           (EXTRACT(hour FROM ts)::int / :step * :step || ' hours')::interval
                           AS time_bucket
                    FROM portfolio_snapshots
                    WHERE ts < :cutoff
                ) sub
                ORDER BY wallet_id, time_bucket, ts ASC
              )
        """)
        result = await db.execute(sql, {"cutoff": cutoff, "step": step_hours})
        deleted = result.rowcount
        await db.flush()
    except Exception as e:
        logger.warning("Snapshot cleanup error (trying simple fallback): %s", e)
        # Simple fallback: just delete everything older than 2x retention
        hard_cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours * 2)
        result = await db.execute(
            delete(PortfolioSnapshot).where(PortfolioSnapshot.ts < hard_cutoff)
        )
        deleted = result.rowcount
        await db.flush()

    _portfolio_cache.clear()
    return {"deleted": deleted, "cutoff": cutoff.isoformat()}
