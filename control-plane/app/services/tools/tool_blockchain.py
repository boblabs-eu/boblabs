"""Blockchain query tools: balance, transactions, token_transfers, token_info for EVM and Solana."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

_CHAIN_CONFIG = {
    "ethereum": {
        "rpc": "https://eth.llamarpc.com",
        "blockscout": "https://eth.blockscout.com",
        "native_symbol": "ETH",
        "decimals": 18,
    },
    "base": {
        "rpc": "https://mainnet.base.org",
        "blockscout": "https://base.blockscout.com",
        "native_symbol": "ETH",
        "decimals": 18,
    },
    "bnb": {
        "rpc": "https://bsc-dataseed.binance.org",
        "blockscout": "https://bsc.blockscout.com",
        "native_symbol": "BNB",
        "decimals": 18,
    },
    "solana": {
        "rpc": "https://api.mainnet-beta.solana.com",
        "native_symbol": "SOL",
        "decimals": 9,
    },
}

TOOLS = {
    "blockchain": {
        "description": "Query on-chain blockchain data. Supports Ethereum, Base (L2), BNB Chain, and Solana. Actions: balance (native + token balances), transactions (recent tx history), token_transfers (ERC-20 transfers), token_info (token metadata and market data).",
        "parameters": {
            "action": {"type": "string", "description": "Action: balance, transactions, token_transfers, token_info", "required": True},
            "address": {"type": "string", "description": "Wallet or token contract address", "required": True},
            "chain": {"type": "string", "description": "Blockchain: ethereum, base, bnb, solana (default: ethereum)", "required": False},
            "limit": {"type": "integer", "description": "Max results for transactions/transfers (default: 20, max: 100)", "required": False},
        },
    },
}


async def _blockchain_balance(client: httpx.AsyncClient, address: str, chain: str) -> dict:
    config = _CHAIN_CONFIG[chain]

    if chain == "solana":
        return await _solana_balance(client, address, config)

    rpc_payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "eth_getBalance",
        "params": [address, "latest"],
    }
    resp = await client.post(config["rpc"], json=rpc_payload)
    data = resp.json()
    raw_balance = int(data.get("result", "0x0"), 16)
    native_balance = raw_balance / (10 ** config["decimals"])

    lines = [f"**{config['native_symbol']} Balance**: {native_balance:.6f} {config['native_symbol']}"]

    try:
        token_resp = await client.get(f"{config['blockscout']}/api/v2/addresses/{address}/token-balances")
        if token_resp.status_code == 200:
            tokens = token_resp.json()
            if isinstance(tokens, list):
                for t in tokens[:20]:
                    tok = t.get("token", {})
                    symbol = tok.get("symbol", "???")
                    decimals = int(tok.get("decimals", "18") or "18")
                    raw = int(t.get("value", "0") or "0")
                    bal = raw / (10 ** decimals) if decimals else raw
                    if bal > 0:
                        lines.append(f"  {symbol}: {bal:.6f}")
    except Exception:
        pass

    return {"success": True, "output": "\n".join(lines)}


async def _solana_balance(client: httpx.AsyncClient, address: str, config: dict) -> dict:
    resp = await client.post(config["rpc"], json={
        "jsonrpc": "2.0", "id": 1,
        "method": "getBalance",
        "params": [address],
    })
    data = resp.json()
    lamports = data.get("result", {}).get("value", 0)
    sol_balance = lamports / 1_000_000_000

    lines = [f"**SOL Balance**: {sol_balance:.6f} SOL"]

    try:
        tok_resp = await client.post(config["rpc"], json={
            "jsonrpc": "2.0", "id": 2,
            "method": "getTokenAccountsByOwner",
            "params": [
                address,
                {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                {"encoding": "jsonParsed"},
            ],
        })
        tok_data = tok_resp.json()
        accounts = tok_data.get("result", {}).get("value", [])
        for acc in accounts[:20]:
            info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            amount_info = info.get("tokenAmount", {})
            ui_amount = amount_info.get("uiAmount", 0)
            mint = info.get("mint", "")
            if ui_amount and ui_amount > 0:
                lines.append(f"  Token {mint[:8]}…: {ui_amount:.6f}")
    except Exception:
        pass

    return {"success": True, "output": "\n".join(lines)}


async def _blockchain_transactions(client: httpx.AsyncClient, address: str, chain: str, limit: int) -> dict:
    config = _CHAIN_CONFIG[chain]

    if chain == "solana":
        return await _solana_transactions(client, address, config, limit)

    resp = await client.get(
        f"{config['blockscout']}/api/v2/addresses/{address}/transactions",
        params={"limit": limit},
    )
    if resp.status_code != 200:
        return {"success": False, "output": f"Blockscout API error: {resp.status_code}"}

    data = resp.json()
    items = data.get("items", [])
    if not items:
        return {"success": True, "output": "No transactions found."}

    lines = [f"Recent transactions for {address[:10]}… on {chain} ({len(items)}):"]
    for tx in items[:limit]:
        value_raw = int(tx.get("value", "0") or "0")
        value = value_raw / (10 ** config["decimals"])
        status = "✓" if tx.get("status") == "ok" else "✗"
        lines.append(
            f"  {status} {tx.get('hash', '')[:12]}… | "
            f"{value:.4f} {config['native_symbol']} | "
            f"from {tx.get('from', {}).get('hash', '')[:10]}… → "
            f"{tx.get('to', {}).get('hash', '')[:10] if tx.get('to') else 'contract'}… | "
            f"{tx.get('timestamp', '')[:19]}"
        )
    return {"success": True, "output": "\n".join(lines)}


async def _solana_transactions(client: httpx.AsyncClient, address: str, config: dict, limit: int) -> dict:
    resp = await client.post(config["rpc"], json={
        "jsonrpc": "2.0", "id": 1,
        "method": "getSignaturesForAddress",
        "params": [address, {"limit": limit}],
    })
    data = resp.json()
    sigs = data.get("result", [])
    if not sigs:
        return {"success": True, "output": "No transactions found."}

    lines = [f"Recent transactions for {address[:10]}… on Solana ({len(sigs)}):"]
    for sig in sigs[:limit]:
        err = "✗" if sig.get("err") else "✓"
        memo = sig.get("memo", "")[:40] if sig.get("memo") else ""
        lines.append(
            f"  {err} {sig.get('signature', '')[:16]}… | "
            f"slot {sig.get('slot', '')} | "
            f"{memo}"
        )
    return {"success": True, "output": "\n".join(lines)}


async def _blockchain_token_transfers(client: httpx.AsyncClient, address: str, chain: str, limit: int) -> dict:
    config = _CHAIN_CONFIG[chain]

    if chain == "solana":
        return {"success": True, "output": "Token transfers on Solana: use 'transactions' action to see all signatures, then inspect individual txs on a Solana explorer."}

    resp = await client.get(
        f"{config['blockscout']}/api/v2/addresses/{address}/token-transfers",
        params={"type": "ERC-20", "limit": limit},
    )
    if resp.status_code != 200:
        return {"success": False, "output": f"Blockscout API error: {resp.status_code}"}

    data = resp.json()
    items = data.get("items", [])
    if not items:
        return {"success": True, "output": "No token transfers found."}

    lines = [f"Token transfers for {address[:10]}… on {chain} ({len(items)}):"]
    for tr in items[:limit]:
        tok = tr.get("token", {})
        symbol = tok.get("symbol", "???")
        decimals = int(tok.get("decimals", "18") or "18")
        raw = int(tr.get("total", {}).get("value", "0") or "0")
        amount = raw / (10 ** decimals) if decimals else raw
        direction = "←" if tr.get("to", {}).get("hash", "").lower() == address.lower() else "→"
        lines.append(
            f"  {direction} {amount:.4f} {symbol} | "
            f"from {tr.get('from', {}).get('hash', '')[:10]}… → "
            f"{tr.get('to', {}).get('hash', '')[:10]}… | "
            f"{tr.get('timestamp', '')[:19]}"
        )
    return {"success": True, "output": "\n".join(lines)}


async def _blockchain_token_info(client: httpx.AsyncClient, address: str, chain: str) -> dict:
    config = _CHAIN_CONFIG[chain]

    if chain == "solana":
        try:
            resp = await client.get(f"https://tokens.jup.ag/token/{address}")
            if resp.status_code == 200:
                data = resp.json()
                lines = [
                    f"**Token**: {data.get('name', 'Unknown')} ({data.get('symbol', '???')})",
                    f"  Decimals: {data.get('decimals', '?')}",
                    f"  Mint: {address}",
                ]
                if data.get("extensions", {}).get("coingeckoId"):
                    lines.append(f"  CoinGecko: {data['extensions']['coingeckoId']}")
                return {"success": True, "output": "\n".join(lines)}
        except Exception:
            pass
        return {"success": True, "output": f"Token info not found for {address} on Solana."}

    resp = await client.get(f"{config['blockscout']}/api/v2/tokens/{address}")
    if resp.status_code != 200:
        return {"success": False, "output": f"Token not found or API error: {resp.status_code}"}

    data = resp.json()
    lines = [
        f"**Token**: {data.get('name', 'Unknown')} ({data.get('symbol', '???')})",
        f"  Type: {data.get('type', '?')}",
        f"  Decimals: {data.get('decimals', '?')}",
        f"  Holders: {data.get('holders_count', '?')}",
    ]
    if data.get("exchange_rate"):
        lines.append(f"  Price: ${data['exchange_rate']}")
    if data.get("total_supply"):
        decimals = int(data.get("decimals", "18") or "18")
        supply = int(data["total_supply"]) / (10 ** decimals) if decimals else int(data["total_supply"])
        lines.append(f"  Total Supply: {supply:,.2f}")
    if data.get("circulating_market_cap"):
        lines.append(f"  Market Cap: ${float(data['circulating_market_cap']):,.0f}")

    return {"success": True, "output": "\n".join(lines)}


async def blockchain(executor: ToolExecutor, args: dict) -> dict:
    """Query on-chain blockchain data."""
    action = args.get("action", "").strip().lower()
    address = args.get("address", "").strip()
    chain = args.get("chain", "ethereum").strip().lower()
    limit = min(int(args.get("limit", 20)), 100)

    if not action:
        return {"success": False, "output": "blockchain requires 'action' (balance, transactions, token_transfers, token_info)"}
    if not address:
        return {"success": False, "output": "blockchain requires 'address'"}
    if chain not in _CHAIN_CONFIG:
        return {"success": False, "output": f"Unsupported chain: {chain}. Use: ethereum, base, bnb, solana"}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
            if action == "balance":
                return await _blockchain_balance(client, address, chain)
            elif action == "transactions":
                return await _blockchain_transactions(client, address, chain, limit)
            elif action == "token_transfers":
                return await _blockchain_token_transfers(client, address, chain, limit)
            elif action == "token_info":
                return await _blockchain_token_info(client, address, chain)
            else:
                return {"success": False, "output": f"Unknown action: {action}. Use: balance, transactions, token_transfers, token_info"}
    except Exception as e:
        return {"success": False, "output": f"Blockchain query failed: {e}"}


HANDLERS = {
    "blockchain": blockchain,
}
