"""Bob Manager — Trading service: wallet signing, DEX aggregation, direct router calls.

Private keys loaded from TRADING_PRIVATE_KEYS env var (JSON array of hex strings).
Keys are NEVER logged, returned via API, or stored in the database.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from decimal import Decimal
from typing import Any

import httpx
from eth_account import Account
from web3 import Web3
from web3.exceptions import ContractLogicError

logger = logging.getLogger(__name__)

# ── Chain configuration ──────────────────────────────────────────────────

CHAIN_CONFIG = {
    "ethereum": {
        "chain_id": 1,
        "rpc": "https://eth.llamarpc.com",
        "native_symbol": "ETH",
        "decimals": 18,
        "blockscout": "https://eth.blockscout.com",
        "explorer_tx": "https://etherscan.io/tx/",
        "1inch_chain_id": 1,
        # A01 — 1inch v6 aggregation router (same address across mainnets).
        "1inch_router": "0x111111125421cA6dc452d289314280a0f8842A65",
        "uniswap_v2_router": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
        "uniswap_v3_router": "0xE592427A0AEce92De3Edee1F18E0157C05861564",
        "uniswap_v3_nft_manager": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
        "weth": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    },
    "base": {
        "chain_id": 8453,
        "rpc": "https://mainnet.base.org",
        "native_symbol": "ETH",
        "decimals": 18,
        "blockscout": "https://base.blockscout.com",
        "explorer_tx": "https://basescan.org/tx/",
        "1inch_chain_id": 8453,
        "1inch_router": "0x111111125421cA6dc452d289314280a0f8842A65",
        "uniswap_v2_router": "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24",
        "uniswap_v3_router": "0x2626664c2603336E57B271c5C0b26F421741e481",
        "uniswap_v3_nft_manager": "0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1",
        "weth": "0x4200000000000000000000000000000000000006",
    },
    "bnb": {
        "chain_id": 56,
        "rpc": "https://bsc-dataseed.binance.org",
        "native_symbol": "BNB",
        "decimals": 18,
        "blockscout": "https://bsc.blockscout.com",
        "explorer_tx": "https://bscscan.com/tx/",
        "1inch_chain_id": 56,
        "1inch_router": "0x111111125421cA6dc452d289314280a0f8842A65",
        "pancakeswap_v2_router": "0x10ED43C718714eb63d5aA57B78B54704E256024E",
        "pancakeswap_v3_nft_manager": "0x46A15B0b27311cedF172AB29E4f4766fbE7F4364",
        "weth": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",  # WBNB
    },
}


# A01 — keys whose values are router contracts we sign swap transactions
# against. ``assert_swap_router_allowed`` builds the per-chain allow-list
# by reading these keys out of CHAIN_CONFIG. Adding a new router (e.g. a
# Curve pool) means adding the address here AND to the relevant chain
# dict — there is no "any address that 1inch sends us" escape hatch.
_SWAP_ROUTER_KEYS = (
    "1inch_router",
    "uniswap_v2_router",
    "uniswap_v3_router",
    "pancakeswap_v2_router",
)


def get_swap_router_allowlist(chain: str) -> set[str]:
    """Return the set of lowercase router addresses we will sign for on ``chain``."""
    cfg = CHAIN_CONFIG.get(chain, {})
    out: set[str] = set()
    for k in _SWAP_ROUTER_KEYS:
        addr = cfg.get(k)
        if addr:
            out.add(addr.lower())
    return out


def assert_swap_router_allowed(chain: str, tx_to: str) -> None:
    """A01 — refuse to sign a swap tx whose target isn't on our per-chain allow-list.

    Pre-fix: ``tx.to`` came verbatim from 1inch's swap-build response.
    A compromised 1inch (or a MITM on a leaky DNS path) could replace
    the router address with an attacker contract; the hot wallet would
    sign the substituted target without notice.

    The allow-list is built from ``CHAIN_CONFIG`` so adding a new
    router (Curve, Balancer, …) requires an explicit code change and
    PR review. Non-swap paths (``send_native``, ``send_token``) do
    NOT go through this check — those legitimately target arbitrary
    recipients.
    """
    if not tx_to:
        raise ValueError("Swap tx has no destination address (tx.to is empty)")
    allowed = get_swap_router_allowlist(chain)
    if not allowed:
        raise ValueError(
            f"No swap router allow-list configured for chain '{chain}' — "
            "refusing to sign a swap tx."
        )
    if tx_to.lower() not in allowed:
        raise ValueError(
            f"Swap router {tx_to} is not on the allow-list for chain "
            f"'{chain}'. Expected one of: {sorted(allowed)}. "
            "If this address is a legitimate new router, add it to "
            "CHAIN_CONFIG['{chain}'] and to _SWAP_ROUTER_KEYS."
        )

# ── Minimal ABIs ─────────────────────────────────────────────────────────

ERC20_ABI = [
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
]

UNISWAP_V2_ROUTER_ABI = [
    {"inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "path", "type": "address[]"}], "name": "getAmountsOut", "outputs": [{"name": "amounts", "type": "uint256[]"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "amountOutMin", "type": "uint256"}, {"name": "path", "type": "address[]"}, {"name": "to", "type": "address"}, {"name": "deadline", "type": "uint256"}], "name": "swapExactTokensForTokens", "outputs": [{"name": "amounts", "type": "uint256[]"}], "type": "function"},
    {"inputs": [{"name": "amountOutMin", "type": "uint256"}, {"name": "path", "type": "address[]"}, {"name": "to", "type": "address"}, {"name": "deadline", "type": "uint256"}], "name": "swapExactETHForTokens", "outputs": [{"name": "amounts", "type": "uint256[]"}], "type": "function", "stateMutability": "payable"},
    {"inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "amountOutMin", "type": "uint256"}, {"name": "path", "type": "address[]"}, {"name": "to", "type": "address"}, {"name": "deadline", "type": "uint256"}], "name": "swapExactTokensForETH", "outputs": [{"name": "amounts", "type": "uint256[]"}], "type": "function"},
]

UNISWAP_V3_ROUTER_ABI = [
    {"inputs": [{"components": [{"name": "tokenIn", "type": "address"}, {"name": "tokenOut", "type": "address"}, {"name": "fee", "type": "uint24"}, {"name": "recipient", "type": "address"}, {"name": "deadline", "type": "uint256"}, {"name": "amountIn", "type": "uint256"}, {"name": "amountOutMinimum", "type": "uint256"}, {"name": "sqrtPriceLimitX96", "type": "uint160"}], "name": "params", "type": "tuple"}], "name": "exactInputSingle", "outputs": [{"name": "amountOut", "type": "uint256"}], "stateMutability": "payable", "type": "function"},
]

# ── Hot wallet management ────────────────────────────────────────────────
#
# Cluster R — wallets are loaded lazily on first access instead of at module
# import. This lets operators rotate TRADING_PRIVATE_KEYS without a full
# bob-api restart (call reset_hot_wallets() then any accessor) and makes the
# trading_service safe to import from contexts that don't have the env yet
# (tests, scripts).
#
# A per-wallet asyncio.Lock keyed by lowercase address serialises
# estimate_and_send's nonce read / sign / send block — concurrent calls for
# the same wallet previously raced on `w3.eth.get_transaction_count`.

_HOT_WALLETS: dict[str, Account] = {}
_HOT_WALLETS_LOADED: bool = False
_WALLET_LOCKS: dict[str, asyncio.Lock] = {}


def _load_hot_wallets() -> None:
    """Load private keys from TRADING_PRIVATE_KEYS env var. Idempotent."""
    global _HOT_WALLETS_LOADED
    if _HOT_WALLETS_LOADED:
        return
    _HOT_WALLETS_LOADED = True
    raw = os.environ.get("TRADING_PRIVATE_KEYS", "").strip()
    if not raw:
        return
    try:
        # Support both JSON array and comma-separated formats
        if raw.startswith("["):
            keys = json.loads(raw)
            if not isinstance(keys, list):
                keys = [keys]
        else:
            keys = [k.strip() for k in raw.split(",") if k.strip()]
        for key in keys:
            key = key.strip()
            if not key.startswith("0x"):
                key = "0x" + key
            acct = Account.from_key(key)
            _HOT_WALLETS[acct.address.lower()] = acct
        if _HOT_WALLETS:
            logger.info("Loaded %d trading wallet(s): %s", len(_HOT_WALLETS),
                        ", ".join(a[:10] + "…" for a in _HOT_WALLETS))
    except (json.JSONDecodeError, Exception) as e:
        logger.error("Failed to load TRADING_PRIVATE_KEYS: %s", e)


def reset_hot_wallets() -> None:
    """Reset cached wallets so the next accessor re-reads the env.

    Intended for tests and operator key rotation. Per-wallet locks are kept
    so any in-flight estimate_and_send call still finishes against its
    original lock.
    """
    global _HOT_WALLETS_LOADED
    _HOT_WALLETS.clear()
    _HOT_WALLETS_LOADED = False


def _ensure_loaded() -> None:
    if not _HOT_WALLETS_LOADED:
        _load_hot_wallets()


def list_hot_wallets() -> list[dict]:
    """Return addresses of loaded hot wallets (never exposes keys)."""
    _ensure_loaded()
    return [{"address": addr} for addr in _HOT_WALLETS]


def get_hot_wallet(address: str) -> Account | None:
    """Get a hot wallet Account by address. Returns None if not loaded."""
    _ensure_loaded()
    return _HOT_WALLETS.get(address.lower())


def has_hot_wallets() -> bool:
    _ensure_loaded()
    return len(_HOT_WALLETS) > 0


def _wallet_lock(address: str) -> asyncio.Lock:
    """Return a per-wallet asyncio.Lock; created lazily on first use."""
    key = address.lower()
    lock = _WALLET_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _WALLET_LOCKS[key] = lock
    return lock


# ── Web3 helpers ─────────────────────────────────────────────────────────

def get_w3(chain: str) -> Web3:
    """Get a Web3 instance for the given chain."""
    config = CHAIN_CONFIG.get(chain)
    if not config:
        raise ValueError(f"Unsupported chain: {chain}")
    return Web3(Web3.HTTPProvider(config["rpc"]))


def get_native_symbol(chain: str) -> str:
    return CHAIN_CONFIG.get(chain, {}).get("native_symbol", "ETH")


async def get_gas_price(chain: str) -> dict:
    """Get current gas price for a chain."""
    w3 = get_w3(chain)
    gas_wei = w3.eth.gas_price
    gas_gwei = float(Web3.from_wei(gas_wei, "gwei"))
    return {"chain": chain, "gas_price_gwei": round(gas_gwei, 2), "gas_price_wei": gas_wei}


async def get_native_balance(chain: str, address: str) -> dict:
    """Get native coin balance."""
    w3 = get_w3(chain)
    balance_wei = w3.eth.get_balance(Web3.to_checksum_address(address))
    balance = float(Web3.from_wei(balance_wei, "ether"))
    symbol = get_native_symbol(chain)
    return {"chain": chain, "address": address, "balance": round(balance, 8), "symbol": symbol}


async def get_token_balance(chain: str, address: str, token_address: str) -> dict:
    """Get ERC-20 token balance."""
    w3 = get_w3(chain)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=ERC20_ABI,
    )
    raw_balance = contract.functions.balanceOf(Web3.to_checksum_address(address)).call()
    decimals = contract.functions.decimals().call()
    symbol = contract.functions.symbol().call()
    balance = float(Decimal(raw_balance) / Decimal(10 ** decimals))
    return {
        "chain": chain, "token": token_address, "symbol": symbol,
        "balance": round(balance, 8), "decimals": decimals,
    }


async def get_token_allowance(chain: str, owner: str, spender: str, token_address: str) -> dict:
    """Check ERC-20 allowance."""
    w3 = get_w3(chain)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=ERC20_ABI,
    )
    allowance = contract.functions.allowance(
        Web3.to_checksum_address(owner),
        Web3.to_checksum_address(spender),
    ).call()
    decimals = contract.functions.decimals().call()
    symbol = contract.functions.symbol().call()
    return {
        "chain": chain, "token": token_address, "symbol": symbol, "owner": owner,
        "spender": spender, "allowance_raw": str(allowance),
        "allowance": float(Decimal(allowance) / Decimal(10 ** decimals)),
    }


# ── Transaction building & signing ──────────────────────────────────────

async def estimate_and_send(
    chain: str,
    wallet_address: str,
    tx_dict: dict,
    gas_multiplier: float = 1.1,
    simulate: bool = True,
) -> dict:
    """Estimate gas, optionally simulate, sign and send a transaction.

    Returns {"tx_hash": ..., "explorer_url": ..., ...} on success.
    Raises ValueError on simulation failure or missing wallet.
    """
    acct = get_hot_wallet(wallet_address)
    if not acct:
        raise ValueError(f"No hot wallet loaded for {wallet_address}")

    config = CHAIN_CONFIG[chain]
    w3 = get_w3(chain)
    checksum_addr = Web3.to_checksum_address(wallet_address)

    # Cluster R — serialise per-wallet so concurrent calls (same address,
    # different transactions) cannot race on `get_transaction_count` and
    # produce two transactions with the same nonce.
    async with _wallet_lock(wallet_address):
        # Fill nonce
        tx_dict["nonce"] = w3.eth.get_transaction_count(checksum_addr)
        tx_dict["chainId"] = config["chain_id"]

        # Estimate gas
        if "gas" not in tx_dict:
            estimated = w3.eth.estimate_gas(tx_dict)
            tx_dict["gas"] = int(estimated * gas_multiplier)

        # Gas price (use EIP-1559 if supported)
        if "maxFeePerGas" not in tx_dict and "gasPrice" not in tx_dict:
            try:
                latest = w3.eth.get_block("latest")
                base_fee = latest.get("baseFeePerGas")
                if base_fee:
                    priority = w3.eth.max_priority_fee
                    tx_dict["maxFeePerGas"] = int((base_fee * 2 + priority) * gas_multiplier)
                    tx_dict["maxPriorityFeePerGas"] = int(priority * gas_multiplier)
                else:
                    tx_dict["gasPrice"] = int(w3.eth.gas_price * gas_multiplier)
            except Exception:
                tx_dict["gasPrice"] = int(w3.eth.gas_price * gas_multiplier)

        # Simulate with eth_call
        if simulate:
            try:
                w3.eth.call(tx_dict, "latest")
            except ContractLogicError as e:
                raise ValueError(f"Transaction simulation reverted: {e}")
            except Exception as e:
                # Some simple transfers don't support eth_call well, allow through
                logger.debug("Simulation warning (proceeding): %s", e)

        # Sign and send. eth_account renamed `rawTransaction` to
        # `raw_transaction` in 0.10.0; keep both spellings supported so a
        # downstream-pin downgrade still works.
        signed = acct.sign_transaction(tx_dict)
        raw_tx = getattr(signed, "raw_transaction", None)
        if raw_tx is None:
            raw_tx = getattr(signed, "rawTransaction", None)
        if raw_tx is None:
            raise ValueError(
                "Signed transaction has neither raw_transaction nor "
                "rawTransaction attribute; unsupported eth_account version."
            )
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        tx_hash_hex = tx_hash.hex()

    return {
        "tx_hash": tx_hash_hex,
        "explorer_url": f"{config['explorer_tx']}{tx_hash_hex}",
        "gas_used": tx_dict["gas"],
        "nonce": tx_dict["nonce"],
    }


async def send_native(chain: str, wallet_address: str, to: str, amount_ether: float,
                       gas_multiplier: float = 1.1) -> dict:
    """Send native ETH/BNB."""
    w3 = get_w3(chain)
    tx_dict = {
        "from": Web3.to_checksum_address(wallet_address),
        "to": Web3.to_checksum_address(to),
        "value": w3.to_wei(amount_ether, "ether"),
    }
    return await estimate_and_send(chain, wallet_address, tx_dict, gas_multiplier, simulate=False)


async def send_token(chain: str, wallet_address: str, token_address: str,
                      to: str, amount: float, gas_multiplier: float = 1.1) -> dict:
    """Send ERC-20 tokens."""
    w3 = get_w3(chain)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=ERC20_ABI,
    )
    decimals = contract.functions.decimals().call()
    raw_amount = int(Decimal(str(amount)) * Decimal(10 ** decimals))

    tx_dict = contract.functions.transfer(
        Web3.to_checksum_address(to), raw_amount,
    ).build_transaction({
        "from": Web3.to_checksum_address(wallet_address),
    })
    return await estimate_and_send(chain, wallet_address, tx_dict, gas_multiplier)


async def approve_token(chain: str, wallet_address: str, token_address: str,
                         spender: str, amount: float | None = None,
                         gas_multiplier: float = 1.1) -> dict:
    """Approve ERC-20 spending. amount=None means unlimited."""
    w3 = get_w3(chain)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=ERC20_ABI,
    )
    if amount is None:
        raw_amount = 2**256 - 1  # Max uint256
    else:
        decimals = contract.functions.decimals().call()
        raw_amount = int(Decimal(str(amount)) * Decimal(10 ** decimals))

    tx_dict = contract.functions.approve(
        Web3.to_checksum_address(spender), raw_amount,
    ).build_transaction({
        "from": Web3.to_checksum_address(wallet_address),
    })
    return await estimate_and_send(chain, wallet_address, tx_dict, gas_multiplier)


# ── 1inch Aggregator ────────────────────────────────────────────────────

_1INCH_BASE = "https://api.1inch.dev/swap/v6.0"
_1INCH_API_KEY = os.environ.get("ONEINCH_API_KEY", "")

NATIVE_TOKEN_ADDRESS = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"


async def get_swap_quote(
    chain: str,
    from_token: str,
    to_token: str,
    amount_raw: int,
) -> dict:
    """Get best swap quote from 1inch aggregator."""
    config = CHAIN_CONFIG.get(chain)
    if not config:
        raise ValueError(f"Unsupported chain: {chain}")

    chain_id = config["1inch_chain_id"]
    url = f"{_1INCH_BASE}/{chain_id}/quote"
    params = {
        "src": Web3.to_checksum_address(from_token),
        "dst": Web3.to_checksum_address(to_token),
        "amount": str(amount_raw),
    }
    headers = {}
    if _1INCH_API_KEY:
        headers["Authorization"] = f"Bearer {_1INCH_API_KEY}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            raise ValueError(f"1inch quote failed ({resp.status_code}): {resp.text[:300]}")
        return resp.json()


async def build_swap_tx(
    chain: str,
    from_token: str,
    to_token: str,
    amount_raw: int,
    wallet_address: str,
    slippage_percent: float = 0.5,
) -> dict:
    """Build a swap transaction via 1inch aggregator. Returns raw tx dict."""
    config = CHAIN_CONFIG.get(chain)
    if not config:
        raise ValueError(f"Unsupported chain: {chain}")

    chain_id = config["1inch_chain_id"]
    url = f"{_1INCH_BASE}/{chain_id}/swap"
    params = {
        "src": Web3.to_checksum_address(from_token),
        "dst": Web3.to_checksum_address(to_token),
        "amount": str(amount_raw),
        "from": Web3.to_checksum_address(wallet_address),
        "slippage": str(slippage_percent),
        "disableEstimate": "false",
    }
    headers = {}
    if _1INCH_API_KEY:
        headers["Authorization"] = f"Bearer {_1INCH_API_KEY}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            raise ValueError(f"1inch swap build failed ({resp.status_code}): {resp.text[:300]}")
        return resp.json()


# ── Direct DEX router calls ─────────────────────────────────────────────

def _get_v2_router(chain: str) -> tuple[str | None, str]:
    """Get the V2 router address for a chain. Returns (router_addr, router_name)."""
    config = CHAIN_CONFIG.get(chain, {})
    if chain == "bnb":
        return config.get("pancakeswap_v2_router"), "PancakeSwap V2"
    return config.get("uniswap_v2_router"), "Uniswap V2"


async def get_v2_quote(chain: str, from_token: str, to_token: str, amount_raw: int) -> dict:
    """Get swap quote from Uniswap V2 / PancakeSwap V2 router."""
    router_addr, router_name = _get_v2_router(chain)
    if not router_addr:
        raise ValueError(f"No V2 router for chain {chain}")

    w3 = get_w3(chain)
    weth = CHAIN_CONFIG[chain]["weth"]
    router = w3.eth.contract(
        address=Web3.to_checksum_address(router_addr),
        abi=UNISWAP_V2_ROUTER_ABI,
    )
    # Build path: if one side is native, use WETH
    path = [Web3.to_checksum_address(from_token), Web3.to_checksum_address(to_token)]
    if from_token.lower() == NATIVE_TOKEN_ADDRESS.lower():
        path[0] = Web3.to_checksum_address(weth)
    if to_token.lower() == NATIVE_TOKEN_ADDRESS.lower():
        path[1] = Web3.to_checksum_address(weth)

    amounts = router.functions.getAmountsOut(amount_raw, path).call()
    return {
        "router": router_name,
        "amount_in": str(amounts[0]),
        "amount_out": str(amounts[-1]),
        "path": [str(p) for p in path],
    }


async def execute_v2_swap(
    chain: str,
    wallet_address: str,
    from_token: str,
    to_token: str,
    amount_raw: int,
    min_amount_out: int,
    gas_multiplier: float = 1.1,
) -> dict:
    """Execute a swap via Uniswap V2 / PancakeSwap V2 router."""
    router_addr, _ = _get_v2_router(chain)
    if not router_addr:
        raise ValueError(f"No V2 router for chain {chain}")

    w3 = get_w3(chain)
    config = CHAIN_CONFIG[chain]
    weth = config["weth"]
    checksum_wallet = Web3.to_checksum_address(wallet_address)
    deadline = w3.eth.get_block("latest")["timestamp"] + 300  # 5 min deadline

    router = w3.eth.contract(
        address=Web3.to_checksum_address(router_addr),
        abi=UNISWAP_V2_ROUTER_ABI,
    )

    is_from_native = from_token.lower() == NATIVE_TOKEN_ADDRESS.lower()
    is_to_native = to_token.lower() == NATIVE_TOKEN_ADDRESS.lower()

    if is_from_native:
        path = [Web3.to_checksum_address(weth), Web3.to_checksum_address(to_token)]
        tx_dict = router.functions.swapExactETHForTokens(
            min_amount_out, path, checksum_wallet, deadline,
        ).build_transaction({
            "from": checksum_wallet,
            "value": amount_raw,
        })
    elif is_to_native:
        path = [Web3.to_checksum_address(from_token), Web3.to_checksum_address(weth)]
        tx_dict = router.functions.swapExactTokensForETH(
            amount_raw, min_amount_out, path, checksum_wallet, deadline,
        ).build_transaction({
            "from": checksum_wallet,
        })
    else:
        path = [Web3.to_checksum_address(from_token), Web3.to_checksum_address(to_token)]
        tx_dict = router.functions.swapExactTokensForTokens(
            amount_raw, min_amount_out, path, checksum_wallet, deadline,
        ).build_transaction({
            "from": checksum_wallet,
        })

    return await estimate_and_send(chain, wallet_address, tx_dict, gas_multiplier)


# ── USD Value Estimation ─────────────────────────────────────────────────

async def estimate_usd_value(chain: str, token_address: str, amount_raw: int) -> float | None:
    """Estimate USD value of a token amount using Blockscout exchange rate.
    Returns None if price unavailable.
    """
    config = CHAIN_CONFIG.get(chain)
    if not config:
        return None
    blockscout = config.get("blockscout")
    if not blockscout:
        return None

    # Native token
    if token_address.lower() == NATIVE_TOKEN_ADDRESS.lower():
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{blockscout}/api/v2/stats")
                if resp.status_code == 200:
                    data = resp.json()
                    price = float(data.get("coin_price", 0))
                    decimals = config["decimals"]
                    amount = float(Decimal(amount_raw) / Decimal(10 ** decimals))
                    return round(amount * price, 2)
        except Exception:
            pass
        return None

    # ERC-20
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{blockscout}/api/v2/tokens/{token_address}")
            if resp.status_code == 200:
                data = resp.json()
                rate = data.get("exchange_rate")
                if rate:
                    decimals = int(data.get("decimals", 18))
                    amount = float(Decimal(amount_raw) / Decimal(10 ** decimals))
                    return round(amount * float(rate), 2)
    except Exception:
        pass
    return None
