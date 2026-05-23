"""DeFi market data tools: prices, TVL, yields, DEX pairs, gas tracker.

All actions are read-only. Data from CoinGecko, DeFiLlama, DEX Screener (free, no API keys).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

TOOLS = {
    "defi_data": {
        "description": (
            "DeFi market data tool (read-only). "
            "Actions: prices (token prices from CoinGecko), token_search (find token by name/symbol), "
            "protocol_tvl (DeFiLlama protocol TVL), chain_tvl (total chain TVLs), "
            "yields (DeFiLlama yield pools by chain/project/APY), "
            "dex_pair (DEX Screener pair data for a token), dex_search (search DEX pairs), "
            "gas_tracker (current gas prices across chains)."
        ),
        "parameters": {
            "action": {
                "type": "string",
                "description": "Action: prices, token_search, protocol_tvl, chain_tvl, yields, dex_pair, dex_search, gas_tracker",
                "required": True,
            },
            "query": {"type": "string", "description": "Search query (for token_search, dex_search) or protocol slug (for protocol_tvl)", "required": False},
            "token_ids": {"type": "string", "description": "Comma-separated CoinGecko token IDs (for prices, e.g. 'bitcoin,ethereum')", "required": False},
            "contract": {"type": "string", "description": "Token contract address (for dex_pair, prices by contract)", "required": False},
            "chain": {"type": "string", "description": "Chain filter (for yields, dex_pair, prices by contract). e.g. ethereum, bsc, base", "required": False},
            "project": {"type": "string", "description": "Project filter for yields (e.g. 'aave-v3', 'uniswap-v3')", "required": False},
            "min_apy": {"type": "string", "description": "Minimum APY filter for yields (e.g. '5.0')", "required": False},
            "min_tvl": {"type": "string", "description": "Minimum TVL in USD for yields (e.g. '1000000')", "required": False},
            "limit": {"type": "integer", "description": "Max results (default: 20, max: 50)", "required": False},
        },
    },
}

_TIMEOUT = 15.0

# Simple in-memory caches
_cache: dict[str, dict] = {}
_PRICE_TTL = 60
_DATA_TTL = 300


def _get_cached(key: str, ttl: int) -> dict | None:
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < ttl:
        return entry["data"]
    return None


def _set_cached(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}


async def defi_data(executor: ToolExecutor, args: dict) -> dict:
    """DeFi market data dispatcher."""
    action = (args.get("action") or "").strip().lower()
    if not action:
        return {"success": False, "output": "defi_data requires 'action'"}

    try:
        if action == "prices":
            return await _prices(args)
        elif action == "token_search":
            return await _token_search(args)
        elif action == "protocol_tvl":
            return await _protocol_tvl(args)
        elif action == "chain_tvl":
            return await _chain_tvl(args)
        elif action == "yields":
            return await _yields(args)
        elif action == "dex_pair":
            return await _dex_pair(args)
        elif action == "dex_search":
            return await _dex_search(args)
        elif action == "gas_tracker":
            return await _gas_tracker(args)
        else:
            return {"success": False, "output": f"Unknown action: {action}"}
    except Exception as e:
        logger.exception("defi_data error: %s", e)
        return {"success": False, "output": f"DeFi data error: {e}"}


# ── CoinGecko ────────────────────────────────────────────────────────────

async def _prices(args: dict) -> dict:
    """Get token prices from CoinGecko by ID or contract address."""
    token_ids = (args.get("token_ids") or "").strip()
    contract = (args.get("contract") or "").strip()
    chain = (args.get("chain") or "").strip()

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        if contract and chain:
            # Price by contract address
            platform_map = {
                "ethereum": "ethereum", "base": "base", "bnb": "binance-smart-chain",
                "bsc": "binance-smart-chain", "arbitrum": "arbitrum-one", "polygon": "polygon-pos",
            }
            platform = platform_map.get(chain.lower(), chain.lower())
            cache_key = f"price_contract_{platform}_{contract}"
            cached = _get_cached(cache_key, _PRICE_TTL)
            if cached:
                return {"success": True, "output": cached}

            resp = await client.get(
                f"https://api.coingecko.com/api/v3/simple/token_price/{platform}",
                params={"contract_addresses": contract, "vs_currencies": "usd",
                        "include_24hr_change": "true", "include_market_cap": "true"},
            )
            if resp.status_code != 200:
                return {"success": False, "output": f"CoinGecko API error: {resp.status_code}"}
            data = resp.json()
            lines = []
            for addr, info in data.items():
                price = info.get("usd", "?")
                change = info.get("usd_24h_change")
                mcap = info.get("usd_market_cap")
                line = f"  {addr[:10]}…: ${price}"
                if change is not None:
                    line += f" ({change:+.2f}% 24h)"
                if mcap:
                    line += f" | MCap: ${mcap:,.0f}"
                lines.append(line)
            output = f"**Token Price** ({chain}):\n" + "\n".join(lines) if lines else "No price data found."
            _set_cached(cache_key, output)
            return {"success": True, "output": output}

        if not token_ids:
            token_ids = "bitcoin,ethereum,binancecoin"

        cache_key = f"prices_{token_ids}"
        cached = _get_cached(cache_key, _PRICE_TTL)
        if cached:
            return {"success": True, "output": cached}

        resp = await client.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "usd", "ids": token_ids,
                    "price_change_percentage": "24h,7d,30d"},
        )
        if resp.status_code != 200:
            return {"success": False, "output": f"CoinGecko API error: {resp.status_code}"}

        data = resp.json()
        lines = ["**Crypto Prices**:"]
        for coin in data:
            c24 = coin.get("price_change_percentage_24h")
            c7d = coin.get("price_change_percentage_7d_in_currency")
            c30d = coin.get("price_change_percentage_30d_in_currency")
            changes = []
            if c24 is not None:
                changes.append(f"24h:{c24:+.1f}%")
            if c7d is not None:
                changes.append(f"7d:{c7d:+.1f}%")
            if c30d is not None:
                changes.append(f"30d:{c30d:+.1f}%")
            change_str = " | ".join(changes)
            mcap = coin.get("market_cap", 0)
            lines.append(
                f"  {coin['name']} ({coin['symbol'].upper()}): ${coin['current_price']:,.2f} | "
                f"{change_str} | MCap: ${mcap:,.0f}"
            )
        output = "\n".join(lines)
        _set_cached(cache_key, output)
        return {"success": True, "output": output}


async def _token_search(args: dict) -> dict:
    """Search tokens by name or symbol on CoinGecko."""
    query = (args.get("query") or "").strip()
    if not query:
        return {"success": False, "output": "token_search requires 'query'"}

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://api.coingecko.com/api/v3/search",
            params={"query": query},
        )
        if resp.status_code != 200:
            return {"success": False, "output": f"CoinGecko search error: {resp.status_code}"}

        data = resp.json()
        coins = data.get("coins", [])[:20]
        if not coins:
            return {"success": True, "output": f"No tokens found for '{query}'."}

        lines = [f"**Token Search** '{query}' ({len(coins)} results):"]
        for c in coins:
            mcap_rank = c.get("market_cap_rank")
            rank = f" #{mcap_rank}" if mcap_rank else ""
            lines.append(f"  {c['name']} ({c['symbol'].upper()}) | ID: {c['id']}{rank}")
        return {"success": True, "output": "\n".join(lines)}


# ── DeFiLlama ────────────────────────────────────────────────────────────

async def _protocol_tvl(args: dict) -> dict:
    """Get protocol TVL data from DeFiLlama."""
    query = (args.get("query") or "").strip()
    if not query:
        return {"success": False, "output": "protocol_tvl requires 'query' (protocol slug, e.g. 'aave')"}

    cache_key = f"protocol_tvl_{query}"
    cached = _get_cached(cache_key, _DATA_TTL)
    if cached:
        return {"success": True, "output": cached}

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"https://api.llama.fi/protocol/{query}")
        if resp.status_code != 200:
            return {"success": False, "output": f"DeFiLlama error: {resp.status_code}. Try searching at https://defillama.com/"}

        data = resp.json()
        name = data.get("name", query)
        tvl = data.get("tvl")
        chains = data.get("chains", [])
        category = data.get("category", "?")

        # Current chain TVLs
        chain_tvls = data.get("currentChainTvls", {})
        top_chains = sorted(chain_tvls.items(), key=lambda x: x[1], reverse=True)[:10]

        lines = [
            f"**{name}** ({category})",
            f"  Total TVL: ${tvl:,.0f}" if tvl else "  TVL: unknown",
            f"  Chains: {', '.join(chains[:10])}",
        ]
        if top_chains:
            lines.append("  Chain breakdown:")
            for ch, val in top_chains:
                lines.append(f"    {ch}: ${val:,.0f}")

        output = "\n".join(lines)
        _set_cached(cache_key, output)
        return {"success": True, "output": output}


async def _chain_tvl(args: dict) -> dict:
    """Get TVL across all chains from DeFiLlama."""
    cache_key = "chain_tvls"
    cached = _get_cached(cache_key, _DATA_TTL)
    if cached:
        return {"success": True, "output": cached}

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get("https://api.llama.fi/v2/chains")
        if resp.status_code != 200:
            return {"success": False, "output": f"DeFiLlama error: {resp.status_code}"}

        data = resp.json()
        # Sort by TVL descending
        data.sort(key=lambda x: x.get("tvl", 0), reverse=True)
        limit = min(int(args.get("limit") or 20), 50)

        lines = [f"**Chain TVL Rankings** (top {limit}):"]
        for i, chain in enumerate(data[:limit], 1):
            name = chain.get("name", "?")
            tvl = chain.get("tvl", 0)
            lines.append(f"  {i}. {name}: ${tvl:,.0f}")

        output = "\n".join(lines)
        _set_cached(cache_key, output)
        return {"success": True, "output": output}


async def _yields(args: dict) -> dict:
    """Get yield pool data from DeFiLlama."""
    cache_key = "yield_pools"
    cached = _get_cached(cache_key, _DATA_TTL)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        if cached:
            pools = cached
        else:
            resp = await client.get("https://yields.llama.fi/pools")
            if resp.status_code != 200:
                return {"success": False, "output": f"DeFiLlama yields error: {resp.status_code}"}
            data = resp.json()
            pools = data.get("data", [])
            _set_cached(cache_key, pools)

    # Apply filters
    chain_filter = (args.get("chain") or "").strip().lower()
    project_filter = (args.get("project") or "").strip().lower()
    min_apy = float(args.get("min_apy", 0) or 0)
    min_tvl = float(args.get("min_tvl", 0) or 0)
    limit = min(int(args.get("limit") or 20), 50)

    filtered = []
    for p in pools:
        if chain_filter and p.get("chain", "").lower() != chain_filter:
            continue
        if project_filter and p.get("project", "").lower() != project_filter:
            continue
        apy = p.get("apy") or 0
        tvl = p.get("tvlUsd") or 0
        if apy < min_apy or tvl < min_tvl:
            continue
        filtered.append(p)

    # Sort by APY descending
    filtered.sort(key=lambda x: x.get("apy", 0), reverse=True)
    filtered = filtered[:limit]

    if not filtered:
        return {"success": True, "output": "No yield pools match the filters."}

    lines = [f"**Yield Pools** ({len(filtered)} results):"]
    for p in filtered:
        symbol = p.get("symbol", "?")
        project = p.get("project", "?")
        chain = p.get("chain", "?")
        apy = p.get("apy", 0)
        tvl = p.get("tvlUsd", 0)
        lines.append(
            f"  {symbol} | {project} on {chain} | APY: {apy:.2f}% | TVL: ${tvl:,.0f}"
        )
    return {"success": True, "output": "\n".join(lines)}


# ── DEX Screener ─────────────────────────────────────────────────────────

async def _dex_pair(args: dict) -> dict:
    """Get DEX pair data for a token from DEX Screener."""
    contract = (args.get("contract") or "").strip()
    if not contract:
        return {"success": False, "output": "dex_pair requires 'contract' address"}

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"https://api.dexscreener.com/latest/dex/tokens/{contract}")
        if resp.status_code != 200:
            return {"success": False, "output": f"DEX Screener error: {resp.status_code}"}

        data = resp.json()
        pairs = data.get("pairs", [])

        # Optionally filter by chain
        chain_filter = (args.get("chain") or "").strip().lower()
        if chain_filter:
            chain_map = {"ethereum": "ethereum", "base": "base", "bnb": "bsc", "bsc": "bsc"}
            mapped = chain_map.get(chain_filter, chain_filter)
            pairs = [p for p in pairs if p.get("chainId", "").lower() == mapped]

        limit = min(int(args.get("limit") or 10), 50)
        pairs = pairs[:limit]

        if not pairs:
            return {"success": True, "output": f"No DEX pairs found for {contract[:10]}…"}

        lines = [f"**DEX Pairs** for {contract[:10]}… ({len(pairs)}):"]
        for p in pairs:
            base = p.get("baseToken", {})
            quote = p.get("quoteToken", {})
            price = p.get("priceUsd", "?")
            vol24 = p.get("volume", {}).get("h24", 0)
            liq = p.get("liquidity", {}).get("usd", 0)
            dex = p.get("dexId", "?")
            chain = p.get("chainId", "?")
            c5m = p.get("priceChange", {}).get("m5", "")
            c1h = p.get("priceChange", {}).get("h1", "")
            c24h = p.get("priceChange", {}).get("h24", "")
            changes = []
            if c5m:
                changes.append(f"5m:{c5m}%")
            if c1h:
                changes.append(f"1h:{c1h}%")
            if c24h:
                changes.append(f"24h:{c24h}%")
            change_str = " ".join(changes)
            lines.append(
                f"  {base.get('symbol', '?')}/{quote.get('symbol', '?')} on {dex}/{chain} | "
                f"${price} | Vol24h: ${vol24:,.0f} | Liq: ${liq:,.0f} | {change_str}"
            )
        return {"success": True, "output": "\n".join(lines)}


async def _dex_search(args: dict) -> dict:
    """Search DEX pairs by query."""
    query = (args.get("query") or "").strip()
    if not query:
        return {"success": False, "output": "dex_search requires 'query'"}

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"https://api.dexscreener.com/latest/dex/search?q={query}")
        if resp.status_code != 200:
            return {"success": False, "output": f"DEX Screener search error: {resp.status_code}"}

        data = resp.json()
        pairs = data.get("pairs", [])
        limit = min(int(args.get("limit") or 10), 50)
        pairs = pairs[:limit]

        if not pairs:
            return {"success": True, "output": f"No pairs found for '{query}'."}

        lines = [f"**DEX Search** '{query}' ({len(pairs)} results):"]
        for p in pairs:
            base = p.get("baseToken", {})
            quote = p.get("quoteToken", {})
            price = p.get("priceUsd", "?")
            dex = p.get("dexId", "?")
            chain = p.get("chainId", "?")
            vol24 = p.get("volume", {}).get("h24", 0)
            lines.append(
                f"  {base.get('symbol', '?')}/{quote.get('symbol', '?')} on {dex}/{chain} | "
                f"${price} | Vol24h: ${vol24:,.0f} | {base.get('address', '')[:10]}…"
            )
        return {"success": True, "output": "\n".join(lines)}


# ── Gas Tracker ──────────────────────────────────────────────────────────

async def _gas_tracker(args: dict) -> dict:
    """Get current gas prices across chains."""
    from app.services.trading_service import CHAIN_CONFIG

    lines = ["**Gas Prices**:"]
    async with httpx.AsyncClient(timeout=10.0) as client:
        for chain_id, config in CHAIN_CONFIG.items():
            try:
                resp = await client.post(config["rpc"], json={
                    "jsonrpc": "2.0", "id": 1,
                    "method": "eth_gasPrice", "params": [],
                })
                if resp.status_code == 200:
                    data = resp.json()
                    gas_wei = int(data.get("result", "0x0"), 16)
                    gas_gwei = gas_wei / 1e9
                    lines.append(f"  {chain_id}: {gas_gwei:.2f} Gwei")
            except Exception:
                lines.append(f"  {chain_id}: unavailable")

    return {"success": True, "output": "\n".join(lines)}


HANDLERS = {
    "defi_data": defi_data,
}
