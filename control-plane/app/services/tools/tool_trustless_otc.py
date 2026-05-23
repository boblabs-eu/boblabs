"""TrustlessOTC integration tool: P2P OTC trading via the OTC bot Agent API.

See OTC_API_DOC.md (repo root) for full reference.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

# All available actions (used in the description and dispatch table).
_ACTIONS = [
    # auth / account
    "register", "login", "mint_apikey", "list_apikeys", "revoke_apikey",
    # market
    "list_chains", "list_tokens", "get_price", "get_quote",
    # orders (read)
    "list_orders", "get_order", "my_orders",
    # orders (write)
    "sell", "buy", "swap", "reserve_order", "deposit_confirm",
    "payment_confirm", "refund_order", "cancel_order",
    # wallets
    "list_wallets", "set_wallet", "remove_wallet",
    # notifications
    "list_notifications", "mark_notification_read", "mark_all_read",
]

TOOLS = {
    "trustless_otc": {
        "sensitive": True,
        "sensitive_reason": (
            "Places, reserves, and confirms real P2P trades and movements of funds via the "
            "TrustlessOTC API. Trade and payment confirmations are hard to reverse."
        ),
        "description": (
            "TrustlessOTC P2P trading via the OTC Bot Agent API. "
            "Supports account management (register, login, mint_apikey), "
            "market data (list_chains, list_tokens, get_price, get_quote), "
            "order book (list_orders, get_order, my_orders), "
            "trading (sell, buy, swap, reserve_order, deposit_confirm, "
            "payment_confirm, refund_order, cancel_order), "
            "wallet management (list_wallets, set_wallet, remove_wallet), "
            "and notifications (list_notifications, mark_notification_read, mark_all_read). "
            "Requires admin to set api_base_url + api_key in Settings → Tool Configs → TrustlessOTC. "
            "All state-changing POSTs send an auto-generated UUID v4 Idempotency-Key. "
            "All amounts/prices are decimal numbers (NOT strings)."
        ),
        "parameters": {
            "action": {
                "type": "string",
                "description": f"Action to perform. One of: {', '.join(_ACTIONS)}.",
                "required": True,
            },
            # Auth
            "username": {"type": "string", "description": "Username (3..32 chars) for register/login.", "required": False},
            "email": {"type": "string", "description": "Email address for register.", "required": False},
            "password": {"type": "string", "description": "Password (>=8 chars) for register/login.", "required": False},
            "label": {"type": "string", "description": "Label for mint_apikey (1..64 chars).", "required": False},
            "scopes": {"type": "string", "description": "Comma-separated scopes for mint_apikey: market:read, orders:read, orders:write, wallets:write, apikeys:manage.", "required": False},
            "expires_in_days": {"type": "integer", "description": "Optional expiry in days for mint_apikey (1..3650).", "required": False},
            "key_id": {"type": "integer", "description": "API key ID for revoke_apikey.", "required": False},
            # Market
            "chain": {"type": "string", "description": "Chain identifier (lowercase): ethereum, base, arbitrum, bnb, solana, etc.", "required": False},
            "symbol": {"type": "string", "description": "Token ticker (uppercase) for get_price (e.g. ETH, USDC).", "required": False},
            "token_sell": {"type": "string", "description": "Ticker you sell (for get_quote, swap).", "required": False},
            "chain_sell": {"type": "string", "description": "Chain of token_sell (for get_quote, swap).", "required": False},
            "token_buy": {"type": "string", "description": "Ticker you buy (for get_quote, swap).", "required": False},
            "chain_buy": {"type": "string", "description": "Chain of token_buy (for get_quote, swap).", "required": False},
            "amount_sell": {"type": "number", "description": "Amount of token_sell (for get_quote, swap).", "required": False},
            "amount_buy": {"type": "number", "description": "Amount of token_buy (for swap).", "required": False},
            # Orders
            "order_id": {"type": "integer", "description": "Order ID for get_order, reserve_order, deposit_confirm, payment_confirm, refund_order, cancel_order.", "required": False},
            "status": {"type": "string", "description": "Order status filter for list_orders (pending|reserved|completed|cancelled|refunded). Default: pending.", "required": False},
            "limit": {"type": "integer", "description": "Result limit for list_orders (1..200, default 50).", "required": False},
            "sort": {"type": "string", "description": "Sort key for list_orders: timestamp, amount_sell, token_sell, chain_sell.", "required": False},
            # Sell / buy specific
            "coin": {"type": "string", "description": "Ticker being sold/bought (for sell/buy).", "required": False},
            "amount": {"type": "number", "description": "Amount of coin (for sell/buy).", "required": False},
            "price": {"type": "number", "description": "Price per 1 coin in stablecoin units (for sell/buy).", "required": False},
            "stablecoin": {"type": "string", "description": "Stablecoin ticker (for sell/buy).", "required": False},
            # Confirm
            "tx_hash": {"type": "string", "description": "On-chain transaction hash (for deposit_confirm, payment_confirm), 4..256 chars.", "required": False},
            # Wallets
            "address": {"type": "string", "description": "Wallet address for set_wallet (4..256 chars). Validate format yourself.", "required": False},
            # Notifications
            "notification_id": {"type": "integer", "description": "Notification ID for mark_notification_read.", "required": False},
            "unread_only": {"type": "boolean", "description": "Filter for list_notifications (default false).", "required": False},
        },
    },
}


# ── Helpers ───────────────────────────────────

async def _get_otc_config(executor: ToolExecutor) -> dict | None:
    from sqlalchemy import select
    from app.models.orchestrator import ToolConfig

    result = await executor.db.execute(
        select(ToolConfig).where(ToolConfig.tool_type == "trustless_otc")
    )
    tc = result.scalar_one_or_none()
    if not tc or not tc.config:
        return None
    return tc.config


def _fail(msg: str) -> dict:
    return {"success": False, "output": msg}


def _ok(payload: Any) -> dict:
    if isinstance(payload, str):
        return {"success": True, "output": payload}
    return {"success": True, "output": json.dumps(payload, indent=2, default=str)}


def _headers(api_key: str | None, *, idempotent: bool) -> dict:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    if idempotent:
        h["Idempotency-Key"] = str(uuid.uuid4())
    return h


async def _request(
    method: str,
    url: str,
    *,
    api_key: str | None = None,
    json_body: dict | None = None,
    params: dict | None = None,
    idempotent: bool = False,
    timeout: float = 30.0,
) -> tuple[bool, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method,
                url,
                headers=_headers(api_key, idempotent=idempotent),
                json=json_body,
                params=params,
            )
            if not resp.is_success:
                try:
                    err = resp.json()
                except Exception:
                    err = resp.text
                return False, f"OTC API error ({resp.status_code}): {err}"
            try:
                return True, resp.json()
            except Exception:
                return True, resp.text
    except httpx.TimeoutException:
        return False, "OTC API request timed out."
    except Exception as e:
        return False, f"OTC API request failed: {e}"


def _data(envelope: Any) -> Any:
    """Unwrap the standard `{success, message, data}` envelope when present."""
    if isinstance(envelope, dict) and "data" in envelope and "success" in envelope:
        return envelope["data"]
    return envelope


# ── Main dispatcher ───────────────────────────

async def trustless_otc(executor: ToolExecutor, args: dict) -> dict:
    action = (args.get("action") or "").strip().lower()
    if not action:
        return _fail(f"trustless_otc requires 'action'. Available: {', '.join(_ACTIONS)}")

    allowed = executor._subtool_permissions.get("trustless_otc", [])
    if allowed and action not in allowed:
        return _fail(f"Action '{action}' not permitted. Allowed: {', '.join(allowed)}")

    cfg = await _get_otc_config(executor)
    if not cfg:
        return _fail("TrustlessOTC not configured. Set api_base_url + api_key in Settings → Tool Configs → TrustlessOTC.")

    base = (cfg.get("api_base_url") or cfg.get("api_url") or "").rstrip("/")
    api_key = cfg.get("api_key") or ""
    if not base:
        return _fail("TrustlessOTC config missing api_base_url (e.g. https://otc.boblabs.eu/api/v1).")

    handler = _DISPATCH.get(action)
    if not handler:
        return _fail(f"Unknown trustless_otc action: {action}. Available: {', '.join(_ACTIONS)}")
    return await handler(args, base, api_key)


# ── Action handlers ───────────────────────────

# Auth
async def _register(args, base, _key):
    body = {
        "username": args.get("username"),
        "email": args.get("email"),
        "password": args.get("password"),
    }
    if not all(body.values()):
        return _fail("register requires username, email, password.")
    ok, data = await _request("POST", f"{base}/auth/register", json_body=body)
    return _ok(_data(data)) if ok else _fail(str(data))


async def _login(args, base, _key):
    body = {"username": args.get("username"), "password": args.get("password")}
    if not all(body.values()):
        return _fail("login requires username, password.")
    ok, data = await _request("POST", f"{base}/auth/login", json_body=body)
    return _ok(_data(data)) if ok else _fail(str(data))


async def _mint_apikey(args, base, key):
    if not key:
        return _fail("mint_apikey requires the bootstrap api_key configured in Tool Configs.")
    label = args.get("label")
    scopes_raw = (args.get("scopes") or "").strip()
    if not label or not scopes_raw:
        return _fail("mint_apikey requires label and scopes (comma-separated).")
    body: dict = {
        "label": label,
        "scopes": [s.strip() for s in scopes_raw.split(",") if s.strip()],
    }
    if args.get("expires_in_days"):
        body["expires_in_days"] = int(args["expires_in_days"])
    ok, data = await _request("POST", f"{base}/apikeys", api_key=key, json_body=body, idempotent=True)
    return _ok(_data(data)) if ok else _fail(str(data))


async def _list_apikeys(_args, base, key):
    ok, data = await _request("GET", f"{base}/apikeys", api_key=key)
    return _ok(_data(data)) if ok else _fail(str(data))


async def _revoke_apikey(args, base, key):
    kid = args.get("key_id")
    if not kid:
        return _fail("revoke_apikey requires key_id.")
    ok, data = await _request("DELETE", f"{base}/apikeys/{int(kid)}", api_key=key)
    return _ok("revoked") if ok else _fail(str(data))


# Market
async def _list_chains(_args, base, _key):
    ok, data = await _request("GET", f"{base}/chains")
    return _ok(_data(data)) if ok else _fail(str(data))


async def _list_tokens(args, base, _key):
    params = {}
    if args.get("chain"):
        params["chain"] = args["chain"]
    ok, data = await _request("GET", f"{base}/tokens", params=params or None)
    return _ok(_data(data)) if ok else _fail(str(data))


async def _get_price(args, base, _key):
    sym = (args.get("symbol") or "").strip().upper()
    if not sym:
        return _fail("get_price requires symbol (e.g. ETH).")
    ok, data = await _request("GET", f"{base}/prices/{sym}")
    return _ok(_data(data)) if ok else _fail(str(data))


async def _get_quote(args, base, _key):
    required = ["token_sell", "chain_sell", "token_buy", "chain_buy", "amount_sell"]
    missing = [k for k in required if args.get(k) in (None, "")]
    if missing:
        return _fail(f"get_quote missing: {', '.join(missing)}.")
    params = {k: args[k] for k in required}
    ok, data = await _request("GET", f"{base}/quote", params=params)
    return _ok(_data(data)) if ok else _fail(str(data))


# Orders (read)
async def _list_orders(args, base, _key):
    params = {}
    for k in ("chain_sell", "chain_buy", "token_sell", "token_buy", "status", "limit", "sort"):
        if args.get(k) not in (None, ""):
            params[k] = args[k]
    ok, data = await _request("GET", f"{base}/orders", params=params or None)
    return _ok(_data(data)) if ok else _fail(str(data))


async def _get_order(args, base, _key):
    oid = args.get("order_id")
    if not oid:
        return _fail("get_order requires order_id.")
    ok, data = await _request("GET", f"{base}/orders/{int(oid)}")
    return _ok(_data(data)) if ok else _fail(str(data))


async def _my_orders(args, base, key):
    if not key:
        return _fail("my_orders requires an authenticated api_key.")
    params = {"chain": args["chain"]} if args.get("chain") else None
    ok, data = await _request("GET", f"{base}/orders/mine", api_key=key, params=params)
    return _ok(_data(data)) if ok else _fail(str(data))


# Orders (write)
def _sell_buy_body(args):
    body = {
        "coin": args.get("coin"),
        "amount": args.get("amount"),
        "price": args.get("price"),
        "stablecoin": args.get("stablecoin"),
        "chain": args.get("chain"),
    }
    missing = [k for k, v in body.items() if v in (None, "")]
    return body, missing


async def _sell(args, base, key):
    if not key:
        return _fail("sell requires an authenticated api_key with orders:write scope.")
    body, missing = _sell_buy_body(args)
    if missing:
        return _fail(f"sell missing: {', '.join(missing)}.")
    ok, data = await _request("POST", f"{base}/orders/sell", api_key=key, json_body=body, idempotent=True)
    return _ok(_data(data)) if ok else _fail(str(data))


async def _buy(args, base, key):
    if not key:
        return _fail("buy requires an authenticated api_key with orders:write scope.")
    body, missing = _sell_buy_body(args)
    if missing:
        return _fail(f"buy missing: {', '.join(missing)}.")
    ok, data = await _request("POST", f"{base}/orders/buy", api_key=key, json_body=body, idempotent=True)
    return _ok(_data(data)) if ok else _fail(str(data))


async def _swap(args, base, key):
    if not key:
        return _fail("swap requires an authenticated api_key with orders:write scope.")
    required = ["token_sell", "chain_sell", "amount_sell", "token_buy", "chain_buy", "amount_buy"]
    missing = [k for k in required if args.get(k) in (None, "")]
    if missing:
        return _fail(f"swap missing: {', '.join(missing)}.")
    body = {k: args[k] for k in required}
    ok, data = await _request("POST", f"{base}/orders/swap", api_key=key, json_body=body, idempotent=True)
    return _ok(_data(data)) if ok else _fail(str(data))


async def _reserve_order(args, base, key):
    if not key:
        return _fail("reserve_order requires an authenticated api_key with orders:write scope.")
    oid = args.get("order_id")
    if not oid:
        return _fail("reserve_order requires order_id.")
    ok, data = await _request("POST", f"{base}/orders/{int(oid)}/reserve", api_key=key, idempotent=True)
    return _ok(_data(data)) if ok else _fail(str(data))


async def _deposit_confirm(args, base, key):
    if not key:
        return _fail("deposit_confirm requires an authenticated api_key with orders:write scope.")
    oid = args.get("order_id")
    tx = args.get("tx_hash")
    if not oid or not tx:
        return _fail("deposit_confirm requires order_id and tx_hash.")
    ok, data = await _request(
        "POST", f"{base}/orders/{int(oid)}/deposit-confirm",
        api_key=key, json_body={"tx_hash": tx}, idempotent=True,
    )
    return _ok(_data(data)) if ok else _fail(str(data))


async def _payment_confirm(args, base, key):
    if not key:
        return _fail("payment_confirm requires an authenticated api_key with orders:write scope.")
    oid = args.get("order_id")
    tx = args.get("tx_hash")
    if not oid or not tx:
        return _fail("payment_confirm requires order_id and tx_hash.")
    ok, data = await _request(
        "POST", f"{base}/orders/{int(oid)}/payment-confirm",
        api_key=key, json_body={"tx_hash": tx}, idempotent=True,
    )
    return _ok(_data(data)) if ok else _fail(str(data))


async def _refund_order(args, base, key):
    if not key:
        return _fail("refund_order requires an authenticated api_key with orders:write scope.")
    oid = args.get("order_id")
    if not oid:
        return _fail("refund_order requires order_id.")
    ok, data = await _request("POST", f"{base}/orders/{int(oid)}/refund", api_key=key, idempotent=True)
    return _ok(_data(data)) if ok else _fail(str(data))


async def _cancel_order(args, base, key):
    if not key:
        return _fail("cancel_order requires an authenticated api_key with orders:write scope.")
    oid = args.get("order_id")
    if not oid:
        return _fail("cancel_order requires order_id.")
    ok, data = await _request("POST", f"{base}/orders/{int(oid)}/cancel", api_key=key, idempotent=True)
    return _ok(_data(data)) if ok else _fail(str(data))


# Wallets
async def _list_wallets(_args, base, key):
    if not key:
        return _fail("list_wallets requires an authenticated api_key.")
    ok, data = await _request("GET", f"{base}/wallets", api_key=key)
    return _ok(_data(data)) if ok else _fail(str(data))


async def _set_wallet(args, base, key):
    if not key:
        return _fail("set_wallet requires an authenticated api_key with wallets:write scope.")
    chain = args.get("chain")
    address = args.get("address")
    if not chain or not address:
        return _fail("set_wallet requires chain and address.")
    ok, data = await _request(
        "POST", f"{base}/wallets",
        api_key=key, json_body={"chain": chain, "address": address}, idempotent=True,
    )
    return _ok(_data(data)) if ok else _fail(str(data))


async def _remove_wallet(args, base, key):
    if not key:
        return _fail("remove_wallet requires an authenticated api_key with wallets:write scope.")
    chain = args.get("chain")
    if not chain:
        return _fail("remove_wallet requires chain.")
    ok, data = await _request("DELETE", f"{base}/wallets/{chain}", api_key=key)
    return _ok("removed") if ok else _fail(str(data))


# Notifications
async def _list_notifications(args, base, key):
    if not key:
        return _fail("list_notifications requires an authenticated api_key.")
    params = {"unread_only": "true"} if args.get("unread_only") else None
    ok, data = await _request("GET", f"{base}/notifications", api_key=key, params=params)
    return _ok(_data(data)) if ok else _fail(str(data))


async def _mark_notification_read(args, base, key):
    if not key:
        return _fail("mark_notification_read requires an authenticated api_key.")
    nid = args.get("notification_id")
    if not nid:
        return _fail("mark_notification_read requires notification_id.")
    ok, data = await _request("POST", f"{base}/notifications/{int(nid)}/read", api_key=key, idempotent=True)
    return _ok(_data(data)) if ok else _fail(str(data))


async def _mark_all_read(_args, base, key):
    if not key:
        return _fail("mark_all_read requires an authenticated api_key.")
    ok, data = await _request("POST", f"{base}/notifications/read-all", api_key=key, idempotent=True)
    return _ok(_data(data)) if ok else _fail(str(data))


_DISPATCH = {
    "register": _register,
    "login": _login,
    "mint_apikey": _mint_apikey,
    "list_apikeys": _list_apikeys,
    "revoke_apikey": _revoke_apikey,
    "list_chains": _list_chains,
    "list_tokens": _list_tokens,
    "get_price": _get_price,
    "get_quote": _get_quote,
    "list_orders": _list_orders,
    "get_order": _get_order,
    "my_orders": _my_orders,
    "sell": _sell,
    "buy": _buy,
    "swap": _swap,
    "reserve_order": _reserve_order,
    "deposit_confirm": _deposit_confirm,
    "payment_confirm": _payment_confirm,
    "refund_order": _refund_order,
    "cancel_order": _cancel_order,
    "list_wallets": _list_wallets,
    "set_wallet": _set_wallet,
    "remove_wallet": _remove_wallet,
    "list_notifications": _list_notifications,
    "mark_notification_read": _mark_notification_read,
    "mark_all_read": _mark_all_read,
}


HANDLERS = {
    "trustless_otc": trustless_otc,
}
