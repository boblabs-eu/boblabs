"""Deep test for ``trading`` — sends a tiny ETH and a tiny USDC transfer on Base.

REQUIRED ENV:
    TRADING_TEST_TO_ADDR     — recipient. **Confirm this is a wallet you control.**
    TRADING_TEST_AMOUNT_ETH  (default: "0.00005")
    TRADING_TEST_AMOUNT_USDC (default: "0.05")
    BOB_ALLOW_DESTRUCTIVE=1  — explicit acknowledgement; missing => SKIPPED

PRECONDITIONS (script aborts otherwise):
    TRADING_PRIVATE_KEYS env on bob-api populated with at least one key.
    First hot wallet has > AMOUNT_ETH ETH and > AMOUNT_USDC USDC on Base.

This broadcasts two **real** transactions on Base mainnet. Real money.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, "/tmp/tools-deep")
from _harness import require_env, optional_env, make_executor, run_tool, passed, fail, skip, run  # noqa: E402

TOOL = "trading"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


async def main():
    if os.environ.get("BOB_ALLOW_DESTRUCTIVE") != "1":
        skip(TOOL, "set BOB_ALLOW_DESTRUCTIVE=1 to broadcast real txs on Base")
    to = require_env("TRADING_TEST_TO_ADDR")
    amount_eth = optional_env("TRADING_TEST_AMOUNT_ETH", "0.00005")
    amount_usdc = optional_env("TRADING_TEST_AMOUNT_USDC", "0.05")
    async with make_executor(timeout_sec=180) as (db, executor):
        # Resolve a wallet.
        wallets = await run_tool(executor, TOOL, {"action": "list_wallets"})
        if not wallets["success"]:
            fail(TOOL, f"list_wallets: {wallets['output'][:200]}")
        # Cheap parse: take the first 0x-prefixed token of length 42.
        wallet = ""
        for tok in wallets["output"].split():
            tok = tok.strip(",")
            if tok.startswith("0x") and len(tok) == 42:
                wallet = tok
                break
        if not wallet:
            fail(TOOL, f"no hot wallet found in: {wallets['output'][:200]}")
        # Native send.
        eth_send = await run_tool(executor, TOOL, {
            "action": "send_native", "chain": "base", "wallet": wallet,
            "to": to, "amount": amount_eth,
        })
        if not eth_send["success"]:
            fail(TOOL, f"send_native: {eth_send['output'][:200]}")
        # Token send (USDC).
        usdc_send = await run_tool(executor, TOOL, {
            "action": "send_token", "chain": "base", "wallet": wallet,
            "to": to, "token": USDC_BASE, "amount": amount_usdc,
        })
        if not usdc_send["success"]:
            fail(TOOL, f"send_token: {usdc_send['output'][:200]}")
        passed(TOOL, f"native {amount_eth} + USDC {amount_usdc} sent from {wallet[:10]}… to {to[:10]}…")


run(main())
