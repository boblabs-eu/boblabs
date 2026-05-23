"""Trading tools: wallet management, token transfers, DEX swaps, position tracking.

Agent-facing tool for EVM-compatible blockchain trading on Ethereum, Base, BNB Chain.
Private keys from TRADING_PRIVATE_KEYS env var. Safety: max_tx_usd, confirmation_mode.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from web3 import Web3

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

TOOLS = {
    "trading": {
        "description": (
            "Crypto trading tool for EVM chains (Ethereum, Base, BNB). "
            "Actions: list_wallets (hot wallets), wallet_balance (native+token balances), "
            "gas_price (current gas), send_native (send ETH/BNB), send_token (ERC-20 transfer), "
            "approve_token (approve DEX spending), token_allowance (check allowance), "
            "quote (DEX swap quote), swap (execute DEX swap), "
            "open_position (record trade position), close_position (close position), "
            "list_positions (view positions with P&L), trade_history (recent trades), portfolio_pnl (aggregate P&L)."
        ),
        "sensitive": True,
        "sensitive_reason": (
            "Holds and uses real private keys to send funds and execute trades on-chain. "
            "Actions are irreversible."
        ),
        "parameters": {
            "action": {
                "type": "string",
                "description": (
                    "Action: list_wallets, wallet_balance, gas_price, send_native, send_token, "
                    "approve_token, token_allowance, quote, swap, "
                    "open_position, close_position, list_positions, trade_history, portfolio_pnl"
                ),
                "required": True,
            },
            "chain": {"type": "string", "description": "Chain: ethereum, base, bnb (default: ethereum)", "required": False},
            "wallet": {"type": "string", "description": "Wallet address (from list_wallets)", "required": False},
            "to": {"type": "string", "description": "Recipient address (for send_native/send_token)", "required": False},
            "amount": {"type": "string", "description": "Amount in human-readable units (e.g. '0.1' for 0.1 ETH)", "required": False},
            "token": {"type": "string", "description": "Token contract address (for send_token/approve/swap)", "required": False},
            "from_token": {"type": "string", "description": "Source token address or 'native' for ETH/BNB (for quote/swap)", "required": False},
            "to_token": {"type": "string", "description": "Destination token address or 'native' (for quote/swap)", "required": False},
            "spender": {"type": "string", "description": "Spender address (for approve_token/token_allowance)", "required": False},
            "position_id": {"type": "string", "description": "Position UUID (for close_position)", "required": False},
            "token_symbol": {"type": "string", "description": "Token symbol (for open_position)", "required": False},
            "entry_price": {"type": "string", "description": "Entry price in USD (for open_position)", "required": False},
            "stop_loss": {"type": "string", "description": "Stop-loss price USD (for open_position)", "required": False},
            "take_profit": {"type": "string", "description": "Take-profit price USD (for open_position)", "required": False},
            "notes": {"type": "string", "description": "Position notes", "required": False},
            "limit": {"type": "integer", "description": "Max results (default 20)", "required": False},
        },
    },
}

_SUPPORTED_CHAINS = {"ethereum", "base", "bnb"}
_READ_ACTIONS = {"list_wallets", "wallet_balance", "gas_price", "token_allowance", "quote",
                 "list_positions", "trade_history", "portfolio_pnl"}
_WRITE_ACTIONS = {"send_native", "send_token", "approve_token", "swap",
                  "open_position", "close_position"}

NATIVE_TOKEN_ADDRESS = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"


async def _get_trading_config(executor) -> dict:
    """Load trading ToolConfig from DB. Returns defaults if not configured."""
    from sqlalchemy import select
    from app.models.orchestrator import ToolConfig

    result = await executor.db.execute(
        select(ToolConfig).where(ToolConfig.tool_type == "trading")
    )
    tc = result.scalar_one_or_none()
    if tc and tc.config:
        return tc.config
    return {
        "max_tx_usd": 100,
        "allowed_chains": ["ethereum", "base", "bnb"],
        "confirmation_mode": "confirm",
        "gas_multiplier": 1.1,
        "slippage_bps": 50,
    }


async def _check_write_safety(executor, action: str, chain: str, config: dict,
                                usd_value: float | None = None) -> str | None:
    """Check if a write action is allowed. Returns error message or None."""
    allowed_chains = config.get("allowed_chains", ["ethereum", "base", "bnb"])
    if chain not in allowed_chains:
        return f"Chain '{chain}' not in allowed chains: {', '.join(allowed_chains)}"

    if usd_value is not None:
        max_usd = float(config.get("max_tx_usd", 100))
        if usd_value > max_usd:
            return (f"Transaction value ~${usd_value:.2f} exceeds max_tx_usd ${max_usd:.2f}. "
                    f"Update trading config to increase limit.")

    return None


def _resolve_token(token: str, chain: str) -> str:
    """Resolve 'native' to the native token sentinel address."""
    if not token or token.lower() in ("native", "eth", "bnb"):
        return NATIVE_TOKEN_ADDRESS
    return token


async def trading(executor: ToolExecutor, args: dict) -> dict:
    """Crypto trading tool dispatcher."""
    action = (args.get("action") or "").strip().lower()
    if not action:
        return {"success": False, "output": "trading requires 'action'"}

    # Subtool permission check
    allowed = executor._subtool_permissions.get("trading", [])
    if allowed and action not in allowed:
        return {"success": False, "output": f"Action '{action}' not permitted. Allowed: {', '.join(allowed)}"}

    chain = (args.get("chain") or "ethereum").strip().lower()
    if chain not in _SUPPORTED_CHAINS:
        return {"success": False, "output": f"Unsupported chain: {chain}. Use: {', '.join(_SUPPORTED_CHAINS)}"}

    try:
        if action == "list_wallets":
            return await _list_wallets(executor, args)
        elif action == "wallet_balance":
            return await _wallet_balance(executor, args, chain)
        elif action == "gas_price":
            return await _gas_price(chain)
        elif action == "send_native":
            return await _send_native(executor, args, chain)
        elif action == "send_token":
            return await _send_token(executor, args, chain)
        elif action == "approve_token":
            return await _approve_token(executor, args, chain)
        elif action == "token_allowance":
            return await _token_allowance(executor, args, chain)
        elif action == "quote":
            return await _quote(executor, args, chain)
        elif action == "swap":
            return await _swap(executor, args, chain)
        elif action == "open_position":
            return await _open_position(executor, args, chain)
        elif action == "close_position":
            return await _close_position(executor, args)
        elif action == "list_positions":
            return await _list_positions(executor, args)
        elif action == "trade_history":
            return await _trade_history(executor, args)
        elif action == "portfolio_pnl":
            return await _portfolio_pnl(executor, args)
        else:
            return {"success": False, "output": f"Unknown action: {action}"}
    except ValueError as e:
        return {"success": False, "output": str(e)}
    except Exception as e:
        logger.exception("trading tool error: %s", e)
        return {"success": False, "output": f"Trading error: {e}"}


# ── Read-only actions ────────────────────────────────────────────────────

async def _list_wallets(executor, args: dict) -> dict:
    from app.services.trading_service import list_hot_wallets, get_native_balance, CHAIN_CONFIG
    wallets = list_hot_wallets()
    if not wallets:
        return {"success": True, "output": "No hot wallets loaded. Set TRADING_PRIVATE_KEYS env var."}

    lines = [f"**Hot Wallets** ({len(wallets)}):"]
    for w in wallets:
        addr = w["address"]
        lines.append(f"  {addr}")
    return {"success": True, "output": "\n".join(lines)}


async def _wallet_balance(executor, args: dict, chain: str) -> dict:
    from app.services.trading_service import get_native_balance, get_w3, CHAIN_CONFIG, ERC20_ABI
    import httpx

    wallet = args.get("wallet", "").strip()
    if not wallet:
        return {"success": False, "output": "wallet_balance requires 'wallet' address"}

    native = await get_native_balance(chain, wallet)
    lines = [f"**{native['symbol']} Balance** on {chain}: {native['balance']} {native['symbol']}"]

    # Fetch ERC-20 tokens from Blockscout
    config = CHAIN_CONFIG.get(chain, {})
    blockscout = config.get("blockscout")
    if blockscout:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{blockscout}/api/v2/addresses/{wallet}/token-balances")
                if resp.status_code == 200:
                    tokens = resp.json()
                    for t in tokens[:20]:
                        tok = t.get("token", {})
                        if tok.get("type") != "ERC-20":
                            continue
                        symbol = tok.get("symbol", "???")
                        decimals = int(tok.get("decimals", 18) or 18)
                        raw = int(t.get("value", "0") or "0")
                        bal = float(Decimal(raw) / Decimal(10 ** decimals))
                        rate = tok.get("exchange_rate")
                        usd = ""
                        if rate and bal > 0:
                            usd_val = round(bal * float(rate), 2)
                            if usd_val > 0:
                                usd = f" (${usd_val:,.2f})"
                                lines.append(f"  {symbol}: {bal:.6f}{usd}")
        except Exception:
            pass

    return {"success": True, "output": "\n".join(lines)}


async def _gas_price(chain: str) -> dict:
    from app.services.trading_service import get_gas_price
    result = await get_gas_price(chain)
    return {"success": True, "output": f"Gas price on {chain}: {result['gas_price_gwei']:.2f} Gwei"}


async def _token_allowance(executor, args: dict, chain: str) -> dict:
    from app.services.trading_service import get_token_allowance
    token = args.get("token", "").strip()
    owner = args.get("wallet", "").strip()
    spender = args.get("spender", "").strip()
    if not all([token, owner, spender]):
        return {"success": False, "output": "token_allowance requires 'token', 'wallet', 'spender'"}

    result = await get_token_allowance(chain, owner, spender, token)
    return {"success": True, "output": (
        f"Allowance: {result['allowance']:.6f} {result['symbol']} "
        f"(owner: {owner[:10]}… → spender: {spender[:10]}…)"
    )}


async def _quote(executor, args: dict, chain: str) -> dict:
    from app.services.trading_service import (
        get_swap_quote, get_v2_quote, get_w3,
        CHAIN_CONFIG, ERC20_ABI, NATIVE_TOKEN_ADDRESS,
    )

    from_token = _resolve_token(args.get("from_token", ""), chain)
    to_token = _resolve_token(args.get("to_token", ""), chain)
    amount_str = args.get("amount", "").strip()

    if not all([from_token, to_token, amount_str]):
        return {"success": False, "output": "quote requires 'from_token', 'to_token', 'amount'"}

    # Get decimals for amount conversion
    if from_token.lower() == NATIVE_TOKEN_ADDRESS.lower():
        decimals = CHAIN_CONFIG[chain]["decimals"]
        from_symbol = CHAIN_CONFIG[chain]["native_symbol"]
    else:
        w3 = get_w3(chain)
        contract = w3.eth.contract(address=Web3.to_checksum_address(from_token), abi=ERC20_ABI)
        decimals = contract.functions.decimals().call()
        from_symbol = contract.functions.symbol().call()

    if to_token.lower() == NATIVE_TOKEN_ADDRESS.lower():
        to_decimals = CHAIN_CONFIG[chain]["decimals"]
        to_symbol = CHAIN_CONFIG[chain]["native_symbol"]
    else:
        w3 = get_w3(chain)
        contract = w3.eth.contract(address=Web3.to_checksum_address(to_token), abi=ERC20_ABI)
        to_decimals = contract.functions.decimals().call()
        to_symbol = contract.functions.symbol().call()

    amount_raw = int(Decimal(amount_str) * Decimal(10 ** decimals))

    # Try 1inch first, fallback to V2 router
    lines = [f"**Swap Quote** on {chain}: {amount_str} {from_symbol} → {to_symbol}"]
    try:
        quote_data = await get_swap_quote(chain, from_token, to_token, amount_raw)
        dst_amount = int(quote_data.get("dstAmount", quote_data.get("toAmount", 0)))
        out = float(Decimal(dst_amount) / Decimal(10 ** to_decimals))
        lines.append(f"  1inch: {out:.8f} {to_symbol}")
    except Exception as e:
        lines.append(f"  1inch: unavailable ({e})")

    try:
        v2_data = await get_v2_quote(chain, from_token, to_token, amount_raw)
        v2_out = float(Decimal(int(v2_data["amount_out"])) / Decimal(10 ** to_decimals))
        lines.append(f"  {v2_data['router']}: {v2_out:.8f} {to_symbol}")
    except Exception as e:
        lines.append(f"  V2 Router: unavailable ({e})")

    return {"success": True, "output": "\n".join(lines)}


# ── Write actions ────────────────────────────────────────────────────────

async def _send_native(executor, args: dict, chain: str) -> dict:
    from app.services.trading_service import send_native, estimate_usd_value, NATIVE_TOKEN_ADDRESS, get_w3

    wallet = args.get("wallet", "").strip()
    to = args.get("to", "").strip()
    amount_str = args.get("amount", "").strip()
    if not all([wallet, to, amount_str]):
        return {"success": False, "output": "send_native requires 'wallet', 'to', 'amount'"}

    amount = float(amount_str)
    config = await _get_trading_config(executor)
    gas_mult = float(config.get("gas_multiplier", 1.1))

    # Estimate USD value
    w3 = get_w3(chain)
    amount_wei = w3.to_wei(amount, "ether")
    usd_value = await estimate_usd_value(chain, NATIVE_TOKEN_ADDRESS, amount_wei)

    # Safety check
    err = await _check_write_safety(executor, "send_native", chain, config, usd_value)
    if err:
        return {"success": False, "output": err}

    # Confirmation mode
    if config.get("confirmation_mode") == "confirm":
        symbol = config.get("native_symbol", "ETH")
        return {"success": True, "output": (
            f"**CONFIRMATION REQUIRED** — send_native\n"
            f"  From: {wallet}\n  To: {to}\n  Amount: {amount} {chain.upper()}\n"
            f"  Est. USD: ${usd_value or '?'}\n"
            f"  Set confirmation_mode to 'autonomous' in trading config to execute directly."
        )}

    result = await send_native(chain, wallet, to, amount, gas_mult)
    await _record_trade(executor, chain, wallet, result["tx_hash"], "send",
                        NATIVE_TOKEN_ADDRESS, str(amount), "", "0", usd_value)
    return {"success": True, "output": (
        f"Sent {amount} on {chain}.\n"
        f"  TX: {result['tx_hash']}\n  Explorer: {result['explorer_url']}"
    )}


async def _send_token(executor, args: dict, chain: str) -> dict:
    from app.services.trading_service import send_token, estimate_usd_value, get_w3, ERC20_ABI

    wallet = args.get("wallet", "").strip()
    to = args.get("to", "").strip()
    token = args.get("token", "").strip()
    amount_str = args.get("amount", "").strip()
    if not all([wallet, to, token, amount_str]):
        return {"success": False, "output": "send_token requires 'wallet', 'to', 'token', 'amount'"}

    amount = float(amount_str)
    config = await _get_trading_config(executor)
    gas_mult = float(config.get("gas_multiplier", 1.1))

    # Get decimals + estimate USD
    w3 = get_w3(chain)
    contract = w3.eth.contract(address=Web3.to_checksum_address(token), abi=ERC20_ABI)
    decimals = contract.functions.decimals().call()
    symbol = contract.functions.symbol().call()
    amount_raw = int(Decimal(amount_str) * Decimal(10 ** decimals))
    usd_value = await estimate_usd_value(chain, token, amount_raw)

    err = await _check_write_safety(executor, "send_token", chain, config, usd_value)
    if err:
        return {"success": False, "output": err}

    if config.get("confirmation_mode") == "confirm":
        return {"success": True, "output": (
            f"**CONFIRMATION REQUIRED** — send_token\n"
            f"  From: {wallet}\n  To: {to}\n  Token: {symbol} ({token[:10]}…)\n"
            f"  Amount: {amount} {symbol}\n  Est. USD: ${usd_value or '?'}\n"
            f"  Set confirmation_mode to 'autonomous' in trading config to execute directly."
        )}

    result = await send_token(chain, wallet, token, to, amount, gas_mult)
    await _record_trade(executor, chain, wallet, result["tx_hash"], "send",
                        token, amount_str, "", "0", usd_value)
    return {"success": True, "output": (
        f"Sent {amount} {symbol} on {chain}.\n"
        f"  TX: {result['tx_hash']}\n  Explorer: {result['explorer_url']}"
    )}


async def _approve_token(executor, args: dict, chain: str) -> dict:
    from app.services.trading_service import approve_token

    wallet = args.get("wallet", "").strip()
    token = args.get("token", "").strip()
    spender = args.get("spender", "").strip()
    amount_str = args.get("amount", "").strip() or None
    if not all([wallet, token, spender]):
        return {"success": False, "output": "approve_token requires 'wallet', 'token', 'spender'"}

    config = await _get_trading_config(executor)
    gas_mult = float(config.get("gas_multiplier", 1.1))

    err = await _check_write_safety(executor, "approve_token", chain, config)
    if err:
        return {"success": False, "output": err}

    amount = float(amount_str) if amount_str else None
    result = await approve_token(chain, wallet, token, spender, amount, gas_mult)
    limit_str = f"{amount}" if amount else "unlimited"
    await _record_trade(executor, chain, wallet, result["tx_hash"], "approve",
                        token, limit_str, "", "0", None)
    return {"success": True, "output": (
        f"Approved {limit_str} spending on {chain}.\n"
        f"  TX: {result['tx_hash']}\n  Explorer: {result['explorer_url']}"
    )}


async def _swap(executor, args: dict, chain: str) -> dict:
    from app.services.trading_service import (
        build_swap_tx, estimate_and_send, get_v2_quote, execute_v2_swap,
        estimate_usd_value, get_w3, CHAIN_CONFIG, ERC20_ABI,
        NATIVE_TOKEN_ADDRESS, get_token_allowance,
    )

    wallet = args.get("wallet", "").strip()
    from_token = _resolve_token(args.get("from_token", ""), chain)
    to_token = _resolve_token(args.get("to_token", ""), chain)
    amount_str = args.get("amount", "").strip()

    if not all([wallet, from_token, to_token, amount_str]):
        return {"success": False, "output": "swap requires 'wallet', 'from_token', 'to_token', 'amount'"}

    config = await _get_trading_config(executor)
    gas_mult = float(config.get("gas_multiplier", 1.1))
    slippage_bps = int(config.get("slippage_bps", 50))
    slippage_pct = slippage_bps / 100.0

    # Resolve decimals
    if from_token.lower() == NATIVE_TOKEN_ADDRESS.lower():
        from_decimals = CHAIN_CONFIG[chain]["decimals"]
        from_symbol = CHAIN_CONFIG[chain]["native_symbol"]
    else:
        w3 = get_w3(chain)
        c = w3.eth.contract(address=Web3.to_checksum_address(from_token), abi=ERC20_ABI)
        from_decimals = c.functions.decimals().call()
        from_symbol = c.functions.symbol().call()

    if to_token.lower() == NATIVE_TOKEN_ADDRESS.lower():
        to_decimals = CHAIN_CONFIG[chain]["decimals"]
        to_symbol = CHAIN_CONFIG[chain]["native_symbol"]
    else:
        w3 = get_w3(chain)
        c = w3.eth.contract(address=Web3.to_checksum_address(to_token), abi=ERC20_ABI)
        to_decimals = c.functions.decimals().call()
        to_symbol = c.functions.symbol().call()

    amount_raw = int(Decimal(amount_str) * Decimal(10 ** from_decimals))

    # Estimate USD value
    usd_value = await estimate_usd_value(chain, from_token, amount_raw)

    # Safety check
    err = await _check_write_safety(executor, "swap", chain, config, usd_value)
    if err:
        return {"success": False, "output": err}

    # Confirmation mode
    if config.get("confirmation_mode") == "confirm":
        return {"success": True, "output": (
            f"**CONFIRMATION REQUIRED** — swap\n"
            f"  Chain: {chain}\n  From: {amount_str} {from_symbol}\n  To: {to_symbol}\n"
            f"  Wallet: {wallet}\n  Slippage: {slippage_pct}%\n"
            f"  Est. USD: ${usd_value or '?'}\n"
            f"  Set confirmation_mode to 'autonomous' in trading config to execute directly."
        )}

    # Try 1inch first, then V2 router fallback
    result = None
    method = None
    to_amount_str = "?"

    try:
        swap_data = await build_swap_tx(chain, from_token, to_token, amount_raw, wallet, slippage_pct)
        tx_dict = swap_data.get("tx", {})
        if tx_dict:
            tx = {
                "from": Web3.to_checksum_address(wallet),
                "to": Web3.to_checksum_address(tx_dict["to"]),
                "data": tx_dict["data"],
                "value": int(tx_dict.get("value", 0)),
            }
            result = await estimate_and_send(chain, wallet, tx, gas_mult)
            method = "1inch"
            dst = swap_data.get("dstAmount", swap_data.get("toAmount", "0"))
            to_amount_str = str(float(Decimal(int(dst)) / Decimal(10 ** to_decimals)))
    except Exception as e:
        logger.info("1inch swap failed, trying V2 router: %s", e)

    if not result:
        # V2 router fallback
        try:
            v2_quote = await get_v2_quote(chain, from_token, to_token, amount_raw)
            amount_out = int(v2_quote["amount_out"])
            min_out = int(amount_out * (1 - slippage_pct / 100))
            result = await execute_v2_swap(chain, wallet, from_token, to_token,
                                           amount_raw, min_out, gas_mult)
            method = v2_quote["router"]
            to_amount_str = str(float(Decimal(amount_out) / Decimal(10 ** to_decimals)))
        except Exception as e:
            return {"success": False, "output": f"Swap failed on both 1inch and V2 router: {e}"}

    # Record trade
    await _record_trade(executor, chain, wallet, result["tx_hash"], "swap",
                        from_token, amount_str, to_token, to_amount_str, usd_value)

    return {"success": True, "output": (
        f"Swap executed via {method} on {chain}.\n"
        f"  {amount_str} {from_symbol} → ~{to_amount_str} {to_symbol}\n"
        f"  TX: {result['tx_hash']}\n  Explorer: {result['explorer_url']}"
    )}


# ── Position tracking actions ────────────────────────────────────────────

async def _open_position(executor, args: dict, chain: str) -> dict:
    from app.repositories.trading_repo import TradingRepo

    wallet = args.get("wallet", "").strip()
    token = args.get("token", "").strip()
    token_symbol = args.get("token_symbol", "").strip()
    amount_str = args.get("amount", "").strip()
    entry_price = args.get("entry_price", "").strip()

    if not all([wallet, token, amount_str]):
        return {"success": False, "output": "open_position requires 'wallet', 'token', 'amount'"}

    repo = TradingRepo(executor.db)
    pos = await repo.open_position(
        wallet_address=wallet,
        chain=chain,
        token_address=token,
        token_symbol=token_symbol or "???",
        amount=float(amount_str),
        entry_price_usd=float(entry_price) if entry_price else None,
        stop_loss_usd=float(args["stop_loss"]) if args.get("stop_loss") else None,
        take_profit_usd=float(args["take_profit"]) if args.get("take_profit") else None,
        notes=args.get("notes", ""),
        lab_id=executor.lab_id,
    )
    return {"success": True, "output": (
        f"Position opened: {amount_str} {token_symbol or '???'} on {chain}\n"
        f"  ID: {pos['id']}\n  Entry: ${entry_price or '?'}"
    )}


async def _close_position(executor, args: dict) -> dict:
    from app.repositories.trading_repo import TradingRepo

    position_id = args.get("position_id", "").strip()
    if not position_id:
        return {"success": False, "output": "close_position requires 'position_id'"}

    exit_price = args.get("entry_price", "").strip()  # reuse field for exit
    repo = TradingRepo(executor.db)
    pos = await repo.close_position(
        position_id=position_id,
        exit_price_usd=float(exit_price) if exit_price else None,
        exit_tx_hash=args.get("tx_hash", ""),
    )
    if not pos:
        return {"success": False, "output": f"Position {position_id} not found or already closed."}
    return {"success": True, "output": (
        f"Position closed: {pos['token_symbol']} on {pos['chain']}\n"
        f"  Entry: ${pos.get('entry_price_usd', '?')} → Exit: ${pos.get('exit_price_usd', '?')}"
    )}


async def _list_positions(executor, args: dict) -> dict:
    from app.repositories.trading_repo import TradingRepo

    wallet = args.get("wallet", "").strip() or None
    status = args.get("notes", "").strip().lower() if args.get("notes", "").strip().lower() in ("open", "closed", "all") else "open"
    limit = min(int(args.get("limit", 20)), 100)

    repo = TradingRepo(executor.db)
    positions = await repo.list_positions(wallet_address=wallet, status=status, limit=limit)

    if not positions:
        return {"success": True, "output": f"No {status} positions found."}

    lines = [f"**Positions** ({status}, {len(positions)}):"]
    for p in positions:
        entry = f"${p['entry_price_usd']:.2f}" if p.get("entry_price_usd") else "?"
        amt = f"{p['amount']:.6f}" if p.get("amount") else "?"
        sl = f" SL:${p['stop_loss_usd']:.2f}" if p.get("stop_loss_usd") else ""
        tp = f" TP:${p['take_profit_usd']:.2f}" if p.get("take_profit_usd") else ""
        lines.append(
            f"  [{p['id'][:8]}] {p['token_symbol']} on {p['chain']} | "
            f"{amt} @ {entry}{sl}{tp} | {p['status']}"
        )
    return {"success": True, "output": "\n".join(lines)}


async def _trade_history(executor, args: dict) -> dict:
    from app.repositories.trading_repo import TradingRepo

    wallet = args.get("wallet", "").strip() or None
    limit = min(int(args.get("limit", 20)), 100)

    repo = TradingRepo(executor.db)
    trades = await repo.get_trade_history(wallet_address=wallet, limit=limit)

    if not trades:
        return {"success": True, "output": "No trade history found."}

    lines = [f"**Trade History** ({len(trades)}):"]
    for t in trades:
        usd = f" (${t['value_usd']:.2f})" if t.get("value_usd") else ""
        lines.append(
            f"  {t['timestamp'][:19]} | {t['tx_type']} on {t['chain']} | "
            f"{t.get('from_amount', '?')} {t.get('from_token_symbol', '?')} → "
            f"{t.get('to_amount', '?')} {t.get('to_token_symbol', '?')}{usd}"
        )
    return {"success": True, "output": "\n".join(lines)}


async def _portfolio_pnl(executor, args: dict) -> dict:
    from app.repositories.trading_repo import TradingRepo

    repo = TradingRepo(executor.db)
    pnl = await repo.get_portfolio_pnl()
    if not pnl:
        return {"success": True, "output": "No open positions to calculate P&L."}

    lines = [f"**Portfolio P&L** ({pnl['position_count']} open positions):"]
    lines.append(f"  Total entry value: ${pnl['total_entry_value']:.2f}")
    if pnl.get("positions"):
        for p in pnl["positions"]:
            lines.append(f"  {p['token_symbol']} on {p['chain']}: {p['amount']:.6f} @ ${p['entry_price_usd']:.2f}")
    return {"success": True, "output": "\n".join(lines)}


# ── Trade recording helper ───────────────────────────────────────────────

async def _record_trade(executor, chain: str, wallet: str, tx_hash: str,
                         tx_type: str, from_token: str, from_amount: str,
                         to_token: str, to_amount: str, value_usd: float | None) -> None:
    """Record a trade in the trade_history table."""
    try:
        from app.repositories.trading_repo import TradingRepo
        repo = TradingRepo(executor.db)
        await repo.record_trade(
            wallet_address=wallet,
            chain=chain,
            tx_hash=tx_hash,
            tx_type=tx_type,
            from_token=from_token,
            from_amount=from_amount,
            to_token=to_token,
            to_amount=to_amount,
            value_usd=value_usd,
            lab_id=executor.lab_id,
        )
    except Exception as e:
        logger.warning("Failed to record trade: %s", e)


HANDLERS = {
    "trading": trading,
}
