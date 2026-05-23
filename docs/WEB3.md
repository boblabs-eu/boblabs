# Bob Labs — Web3 & Blockchain

## Overview

Bob Labs includes a Web3 module for cryptocurrency portfolio tracking, wallet monitoring, and on-chain data queries. The module provides both a frontend dashboard and agent-accessible tools.

## Features

| Feature | Description |
|---------|-------------|
| **Price Feeds** | Live BTC, ETH, BNB prices via CoinGecko |
| **Wallet Tracking** | Add/remove wallets, monitor balances across chains |
| **Portfolio Snapshots** | Historical portfolio value tracking with time-series charts |
| **Transaction History** | View recent transactions and token transfers per wallet per chain |
| **On-Chain Queries** | Agent tool for querying blockchain data (Ethereum, Base, Solana) |
| **Settings** | Configurable refresh intervals and data retention |

## Architecture

```
┌─────────────┐     ┌──────────────────────────────────────┐
│  Frontend    │────▶│  Control Plane (/api/v1/web3/)       │
│  Web3 Page   │     │                                      │
└─────────────┘     │  web3_service.py                     │
                     │  ├── get_crypto_prices() → CoinGecko │
                     │  ├── get_wallet_balances() → RPCs    │
                     │  ├── get_wallet_transactions() →     │
                     │  │   Blockscout                      │
                     │  ├── record_portfolio_snapshot()      │
                     │  └── cleanup_old_snapshots()          │
                     │                                      │
┌─────────────┐     │  blockchain tool (in Labs)            │
│  Lab Agent   │────▶│  ├── balance                         │
│              │     │  ├── transactions                    │
│              │     │  ├── token_transfers                 │
│              │     │  └── token_info                      │
└─────────────┘     └──────────────────────────────────────┘
```

## API Endpoints

All under `/api/v1/web3`:

### Prices & Portfolio

| Method | Path | Description |
|--------|------|-------------|
| GET | `/prices` | Live BTC, ETH, BNB prices from CoinGecko |
| GET | `/portfolio` | Total portfolio value across all wallets |
| GET | `/portfolio/history` | Portfolio value time-series (query: `wallet_id`, `hours`) |
| POST | `/portfolio/snapshot` | Manually trigger a portfolio snapshot |
| POST | `/portfolio/cleanup` | Trigger old snapshot cleanup/downsampling |

### Wallets

| Method | Path | Description |
|--------|------|-------------|
| GET | `/wallets` | List all tracked wallets |
| POST | `/wallets` | Add a wallet to track (`address`, `label`) |
| DELETE | `/wallets/{wallet_id}` | Remove a tracked wallet |
| GET | `/wallets/{wallet_id}/balances` | Native balances across all chains |
| GET | `/wallets/{wallet_id}/transactions` | Recent transactions (query: `chain`) |

### Settings

| Method | Path | Description |
|--------|------|-------------|
| GET | `/settings` | Get Web3 settings |
| PUT | `/settings` | Update settings (refresh_interval, retention) |

**Settings fields:**

| Field | Type | Description |
|-------|------|-------------|
| `refresh_interval` | int | Seconds between automatic price refreshes |
| `retention_full_hours` | int | Hours to keep full-resolution snapshots |
| `retention_step_hours` | int | Hours between downsampled snapshots after retention |

## Blockchain Tool

The `blockchain` builtin tool is available to Lab agents for on-chain queries:

```json
{
  "name": "blockchain",
  "arguments": {
    "action": "balance",
    "address": "0x...",
    "chain": "ethereum"
  }
}
```

### Actions

| Action | Description | Parameters |
|--------|-------------|------------|
| `balance` | Native + token balances | `address`, `chain` (opt) |
| `transactions` | Recent transactions | `address`, `chain` (opt), `limit` (opt) |
| `token_transfers` | ERC-20/SPL token transfers | `address`, `chain` (opt), `limit` (opt) |
| `token_info` | Token contract details | `address`, `chain` (opt) |

### Supported Chains

| Chain | Explorer API |
|-------|-------------|
| `ethereum` | Blockscout / Etherscan |
| `base` | Blockscout |
| `solana` | Solana RPC |

## Database Tables

| Table | Purpose |
|-------|---------|
| `wallets` | Tracked wallet addresses with labels and ACL |
| `web3_settings` | User-configurable settings (singleton) |
| `portfolio_snapshots` | Time-series portfolio value records |

## Related Documents

- [TOOLS_AND_SANDBOX.md](TOOLS_AND_SANDBOX.md) — Blockchain tool reference
- [ARCHITECTURE.md](ARCHITECTURE.md) — System architecture
