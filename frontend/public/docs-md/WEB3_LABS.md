# Bob Labs - Web3 Lab Blueprints

## Overview

This document tracks the Web3 lab blueprints added for Bob Labs.

There are six blueprints:

- Runnable now:
  - `templates/lab_examples/web3_wallet_monitor_runnable.lab.json`
  - `templates/lab_examples/web3_auto_trader_runnable.lab.json`
  - `templates/lab_examples/web3_liquidity_optimizer_runnable.lab.json`
- Future-state design:
  - `templates/lab_examples/web3_wallet_monitor_future.lab.json`
  - `templates/lab_examples/web3_auto_trader_future.lab.json`
  - `templates/lab_examples/web3_liquidity_optimizer_future.lab.json`

## What Is Runnable Today

### 1. Wallet Monitor Runnable

Purpose:
- Monitor loaded hot wallets.
- Inspect balances, recent activity, and open tracked positions.
- Classify market regime and highlight unusual volatility.
- Write operator advice without sending transactions.

Current tool surface used:
- `trading`
- `defi_data`
- `blockchain`
- `file_read`
- `file_write`
- `python_exec`
- `think`

### 2. Auto Trader Runnable

Purpose:
- Run a guarded spot-trading workflow on loaded hot wallets.
- Default to bounded-risk automation.
- Allow an aggressive stretch mode if the operator explicitly injects `AGGRESSIVE_10PCT_MODE`.

Current tool surface used:
- `trading`
- `defi_data`
- `file_read`
- `file_write`
- `think`

Important runtime guardrails baked into the prompts:
- Start in `confirmation_mode=confirm` for dry runs.
- Use only the default token universe declared in the blueprint context.
- One action maximum per run.
- Avoid approvals by default.

Critical caveat:
- `approve_token` currently executes immediately and is not gated by `confirmation_mode` in the current backend implementation. The runnable blueprint therefore blocks autonomous approval behavior unless the operator explicitly enables it.

### 3. Liquidity Optimizer Runnable

Purpose:
- Rank LP-style opportunities.
- Compare yield, chain strength, gas friction, and token risk.
- Produce a manual playbook for the operator.

Current tool surface used:
- `trading` read actions only
- `defi_data`
- `blockchain`
- `file_read`
- `file_write`
- `think`

Limitation:
- This version is advisory only. It does not open, rebalance, or close on-chain liquidity positions because no LP execution tool exists yet.

## What Is Not Runnable Yet

### Future Wallet Monitor

Blocked on:
- `web3_portfolio` tool for tracked-wallet balances, totals, history, and snapshots.
- `market_history` tool for structured price history and volatility metrics.

### Future Auto Trader

Blocked on:
- `web3_portfolio` for structured portfolio history and realized PnL.
- `market_history` for candles and signal data.
- `position_guard` for automated stop-loss, take-profit, and exposure checks.
- Structured trading outputs instead of prose-only quote and swap summaries.

### Future Liquidity Optimizer

Blocked on:
- `liquidity_manager` for LP discovery, open, close, rebalance, fee collection, and impermanent-loss estimation.
- `web3_portfolio` for tracked wallet exposure.
- `market_history` for pool and token volatility context.

## Validation Performed

The following validation was completed during implementation:

- All six new JSON files passed local syntax validation with `jq empty`.
- The local API responded successfully on `http://localhost:8888/health`.
- The live builtin-tools endpoint confirmed current exposure of:
  - `trading`
  - `defi_data`
  - `blockchain`

The following validation was not performed:

- Importing the blueprints into the live database.
- Running the labs end-to-end.
- On-chain dry runs.

## Tool Readiness Summary

Implemented and exposed to labs today:
- `trading`
- `defi_data`
- `blockchain`

Implemented outside the lab tool surface today:
- Web3 tracked-wallet snapshot and history APIs under `/api/v1/web3`

Not implemented as lab tools today:
- `web3_portfolio`
- `market_history`
- `position_guard`
- `liquidity_manager`

## Testing Notes

No automated test suite was found for the current Web3 lab tool chain.

What has been confirmed:
- Backend files for `trading`, `defi_data`, `blockchain`, and `web3_service` are free of static editor errors.
- The runtime API exposes the current Web3-related builtin tools.

What still needs real execution testing:
- Dry-running the runnable trader in `confirm` mode.
- Verifying wallet discovery from `TRADING_PRIVATE_KEYS`.
- Verifying quote and swap behavior per chain.
- Verifying that the advisory labs write coherent output files in practice.

## Recommended Next Step

Import and test the runnable blueprints first, in this order:

1. `web3_wallet_monitor_runnable.lab.json`
2. `web3_liquidity_optimizer_runnable.lab.json`
3. `web3_auto_trader_runnable.lab.json`

When testing the trader:
- Use a disposable hot wallet.
- Keep `confirmation_mode=confirm`.
- Keep `max_tx_usd` low.
- Do not enable autonomous approvals until the approval path is explicitly fixed or intentionally accepted.