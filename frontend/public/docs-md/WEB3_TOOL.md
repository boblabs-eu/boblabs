# Bob Labs — Trading & DeFi Tools

## Overview

Bob Labs provides two agent-accessible tools for on-chain trading and DeFi market analysis on EVM-compatible blockchains. The system is designed for medium-term portfolio management (days/weeks/months) with full wallet management by agents when configured. Private keys are stored exclusively in environment variables and are **never** logged, returned via API, or persisted in the database.

| Tool | Purpose |
|------|---------|
| `trading` | Wallet management, token transfers, DEX swaps, position tracking |
| `defi_data` | Read-only DeFi market data: prices, TVL, yields, DEX pairs |

## Supported Chains

| Chain | Chain ID | Native Token | DEX Router | Explorer |
|-------|----------|-------------|------------|----------|
| Ethereum | 1 | ETH | Uniswap V2 / V3 | etherscan.io |
| Base | 8453 | ETH | Uniswap V2 / V3 | basescan.org |
| BNB Chain | 56 | BNB | PancakeSwap V2 | bscscan.com |

## Architecture

```
┌──────────────┐     ┌────────────────────────────────────────────────────────┐
│  Lab Agent   │────▶│  Control Plane                                         │
│              │     │                                                        │
│  Uses:       │     │  tool_trading.py  (15 actions)                         │
│  - trading   │     │  ├── _check_write_safety()  → ToolConfig limits        │
│  - defi_data │     │  ├── READ: list_wallets, wallet_balance, gas_price,    │
│              │     │  │  token_allowance, quote, list_positions,            │
│              │     │  │  trade_history, portfolio_pnl                       │
│              │     │  └── WRITE: send_native, send_token, approve_token,    │
│              │     │     swap, open_position, close_position                │
│              │     │                                                        │
│              │     │  tool_defi_data.py  (8 actions, read-only)             │
│              │     │  ├── CoinGecko: prices, token_search                   │
│              │     │  ├── DeFiLlama: protocol_tvl, chain_tvl, yields        │
│              │     │  ├── DEX Screener: dex_pair, dex_search                │
│              │     │  └── RPC: gas_tracker                                  │
│              │     │                                                        │
│              │     │  trading_service.py  (core engine)                     │
│              │     │  ├── Hot wallet signing (web3.py + eth-account)        │
│              │     │  ├── 1inch Fusion API v6  (swap aggregation)           │
│              │     │  ├── Uniswap V2 / PancakeSwap V2  (direct router)     │
│              │     │  └── Blockscout API  (USD estimation)                  │
│              │     │                                                        │
│              │     │  trading_repo.py  →  PostgreSQL                        │
│              │     │  ├── trading_positions                                 │
│              │     │  └── trade_history                                     │
└──────────────┘     └────────────────────────────────────────────────────────┘
                          │           │            │             │
                     Ethereum RPC   Base RPC    BNB RPC    External APIs
                                                           ├── CoinGecko
                                                           ├── DeFiLlama
                                                           ├── DEX Screener
                                                           ├── 1inch
                                                           └── Blockscout
```

## Setup

### 1. Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TRADING_PRIVATE_KEYS` | No | JSON array of hex private keys: `["0xabc…", "0xdef…"]` |
| `ONEINCH_API_KEY` | No | 1inch API key for swap aggregation (works without for basic usage) |

Add to the `.env` file used by `bob-api`:

```env
TRADING_PRIVATE_KEYS=["0xYOUR_PRIVATE_KEY_HEX"]
ONEINCH_API_KEY=your_1inch_api_key
```

> **Security**: Private keys are loaded into memory at startup and stored in a module-level dict keyed by address. They are never serialized, returned in API responses, or written to the database. The `list_wallets` action only returns addresses, never keys.

### 2. Tool Configuration

Configure safety limits via the Tool Configs API or the UI (Settings → Tool Configs → `trading`):

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `max_tx_usd` | number | `100` | Maximum USD value per transaction |
| `allowed_chains` | string[] | `["ethereum", "base", "bnb"]` | Chains the agent is permitted to transact on |
| `confirmation_mode` | string | `"confirm"` | `confirm` = preview-only (agent cannot execute), `autonomous` = agent executes directly |
| `gas_multiplier` | number | `1.1` | Multiplier applied to estimated gas (1.1 = 10% buffer) |
| `slippage_bps` | number | `50` | Slippage tolerance in basis points (50 = 0.5%) |

Example API call:

```bash
curl -X PUT http://localhost:8000/api/v1/tool-configs/trading \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "max_tx_usd": 500,
      "allowed_chains": ["ethereum", "base"],
      "confirmation_mode": "autonomous",
      "gas_multiplier": 1.15,
      "slippage_bps": 100
    }
  }'
```

### 3. Lab Setup

Assign the `trading` and/or `defi_data` tools to a Lab. Use subtool permissions to restrict which actions are available:

```json
{
  "tools": ["trading", "defi_data"],
  "subtool_permissions": {
    "trading": ["list_wallets", "wallet_balance", "quote", "swap", "list_positions"],
    "defi_data": ["prices", "yields", "dex_pair"]
  }
}
```

If `subtool_permissions` is empty for a tool, all actions are allowed.

---

## Trading Tool

**Tool name:** `trading`

### Actions Reference

#### Read Actions

| Action | Description | Required Parameters | Optional Parameters |
|--------|-------------|--------------------|--------------------|
| `list_wallets` | List loaded hot wallet addresses | — | — |
| `wallet_balance` | Native + ERC-20 token balances (via Blockscout) | `wallet` | `chain` |
| `gas_price` | Current gas price in Gwei | — | `chain` |
| `token_allowance` | Check ERC-20 spending allowance | `wallet`, `token`, `spender` | `chain` |
| `quote` | Get swap quote (1inch + V2 router) | `from_token`, `to_token`, `amount` | `chain` |
| `list_positions` | View tracked positions | — | `wallet`, `limit` |
| `trade_history` | Recent executed trades | — | `wallet`, `limit` |
| `portfolio_pnl` | Aggregate P&L of open positions | — | — |

#### Write Actions

| Action | Description | Required Parameters | Optional Parameters |
|--------|-------------|--------------------|--------------------|
| `send_native` | Send ETH/BNB | `wallet`, `to`, `amount` | `chain` |
| `send_token` | Transfer ERC-20 tokens | `wallet`, `to`, `token`, `amount` | `chain` |
| `approve_token` | Approve DEX spending | `wallet`, `token`, `spender` | `chain`, `amount` (omit for unlimited) |
| `swap` | Execute DEX swap | `wallet`, `from_token`, `to_token`, `amount` | `chain` |
| `open_position` | Record a trading position | `wallet`, `token`, `amount` | `chain`, `token_symbol`, `entry_price`, `stop_loss`, `take_profit`, `notes` |
| `close_position` | Close an open position | `position_id` | `entry_price` (used as exit price) |

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `action` | string | **Required**. The action to execute |
| `chain` | string | Chain: `ethereum`, `base`, `bnb`. Default: `ethereum` |
| `wallet` | string | Wallet address (must be a loaded hot wallet for write actions) |
| `to` | string | Recipient address |
| `amount` | string | Human-readable amount (e.g. `"0.1"` for 0.1 ETH) |
| `token` | string | ERC-20 contract address |
| `from_token` | string | Source token address, or `"native"` for ETH/BNB |
| `to_token` | string | Destination token address, or `"native"` |
| `spender` | string | Spender address (for approvals) |
| `position_id` | string | Position UUID |
| `token_symbol` | string | Token ticker symbol |
| `entry_price` | string | Entry price in USD |
| `stop_loss` | string | Stop-loss price in USD |
| `take_profit` | string | Take-profit price in USD |
| `notes` | string | Free-text notes |
| `limit` | integer | Max results (default: 20) |

### Swap Execution Flow

```
Agent calls swap action
        │
        ▼
Safety check: _check_write_safety()
├── Chain in allowed_chains?
├── USD value ≤ max_tx_usd?     (via Blockscout estimate)
└── confirmation_mode == "confirm"?
        │                │
        │ (autonomous)   │ (confirm)
        ▼                ▼
  Execute swap     Return preview
        │           (no execution)
        ▼
  Try 1inch Fusion API
        │
        ├── Success → sign & send via estimate_and_send()
        │
        └── Failure → fallback to V2 router
                │
                ├── Uniswap V2 (Ethereum, Base)
                └── PancakeSwap V2 (BNB)
                        │
                        ▼
                  Get V2 quote → apply slippage → build tx → sign & send
                        │
                        ▼
                  Record in trade_history
```

### Transaction Signing

All write transactions go through `estimate_and_send()`:

1. Load hot wallet `Account` object by address
2. Fill nonce from chain
3. Estimate gas × `gas_multiplier`
4. Use EIP-1559 fee model if the chain supports it, otherwise legacy `gasPrice`
5. Simulate with `eth_call` (except native sends)
6. Sign with `eth-account` and broadcast via `eth_sendRawTransaction`
7. Return `tx_hash` + `explorer_url`

### Example Agent Interactions

**Check wallet balance:**
```json
{
  "name": "trading",
  "arguments": {
    "action": "wallet_balance",
    "wallet": "0x1234...abcd",
    "chain": "base"
  }
}
```

**Get swap quote:**
```json
{
  "name": "trading",
  "arguments": {
    "action": "quote",
    "from_token": "native",
    "to_token": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "amount": "0.5",
    "chain": "ethereum"
  }
}
```

**Execute swap (requires `autonomous` mode):**
```json
{
  "name": "trading",
  "arguments": {
    "action": "swap",
    "wallet": "0x1234...abcd",
    "from_token": "native",
    "to_token": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "amount": "0.1",
    "chain": "ethereum"
  }
}
```

**Open a position:**
```json
{
  "name": "trading",
  "arguments": {
    "action": "open_position",
    "wallet": "0x1234...abcd",
    "token": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "token_symbol": "USDC",
    "amount": "1000",
    "entry_price": "1.00",
    "stop_loss": "0.95",
    "take_profit": "1.10",
    "chain": "ethereum"
  }
}
```

---

## DeFi Data Tool

**Tool name:** `defi_data`

All actions are read-only. No API keys required — uses free tiers of CoinGecko, DeFiLlama, and DEX Screener. Results are cached in-memory (60s for prices, 300s for TVL/yields).

### Actions Reference

| Action | Description | Required Parameters | Optional Parameters |
|--------|-------------|--------------------|--------------------|
| `prices` | Token prices (CoinGecko) | — | `token_ids`, `contract` + `chain` |
| `token_search` | Find token by name/symbol | `query` | — |
| `protocol_tvl` | Protocol TVL breakdown (DeFiLlama) | `query` (protocol slug) | — |
| `chain_tvl` | Chain TVL rankings | — | `limit` |
| `yields` | DeFiLlama yield pool data | — | `chain`, `project`, `min_apy`, `min_tvl`, `limit` |
| `dex_pair` | DEX pair data (DEX Screener) | `contract` | `chain`, `limit` |
| `dex_search` | Search DEX pairs | `query` | `limit` |
| `gas_tracker` | Gas prices across all supported chains | — | — |

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `action` | string | **Required**. The action to execute |
| `token_ids` | string | Comma-separated CoinGecko IDs: `"bitcoin,ethereum,uniswap"` |
| `contract` | string | Token contract address |
| `chain` | string | Chain filter: `ethereum`, `base`, `bnb`, `bsc`, `arbitrum`, `polygon` |
| `query` | string | Search query or protocol slug (e.g. `"aave"`, `"uniswap-v3"`) |
| `project` | string | DeFiLlama project filter for yields |
| `min_apy` | string | Minimum APY filter (e.g. `"5.0"`) |
| `min_tvl` | string | Minimum TVL in USD (e.g. `"1000000"`) |
| `limit` | integer | Max results (default: 20, max: 50) |

### Data Sources

| Source | Actions | Rate Limiting | Notes |
|--------|---------|--------------|-------|
| [CoinGecko](https://www.coingecko.com/en/api) | `prices`, `token_search` | Free tier ~30 req/min | Supports price by ID or contract address |
| [DeFiLlama](https://defillama.com/docs/api) | `protocol_tvl`, `chain_tvl`, `yields` | No key needed | TVL, yield pools, protocol data |
| [DEX Screener](https://docs.dexscreener.com/) | `dex_pair`, `dex_search` | No key needed | Real-time DEX pair data with price changes |
| RPC Nodes | `gas_tracker` | N/A | Direct `eth_gasPrice` calls to chain RPCs |

### Example Agent Interactions

**Get BTC/ETH prices:**
```json
{
  "name": "defi_data",
  "arguments": {
    "action": "prices",
    "token_ids": "bitcoin,ethereum,binancecoin"
  }
}
```

**Search for a token:**
```json
{
  "name": "defi_data",
  "arguments": {
    "action": "token_search",
    "query": "pepe"
  }
}
```

**Find high-yield pools on Base:**
```json
{
  "name": "defi_data",
  "arguments": {
    "action": "yields",
    "chain": "base",
    "min_apy": "10",
    "min_tvl": "500000",
    "limit": 10
  }
}
```

**Check protocol TVL:**
```json
{
  "name": "defi_data",
  "arguments": {
    "action": "protocol_tvl",
    "query": "aave-v3"
  }
}
```

**Get DEX pair data:**
```json
{
  "name": "defi_data",
  "arguments": {
    "action": "dex_pair",
    "contract": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "chain": "ethereum"
  }
}
```

---

## Safety Model

### Transaction Guards

All write actions in the `trading` tool pass through `_check_write_safety()`:

| Guard | Description |
|-------|-------------|
| **Chain allowlist** | Transaction rejected if the chain is not in `allowed_chains` |
| **USD value limit** | Transaction rejected if estimated USD value exceeds `max_tx_usd` |
| **Confirmation mode** | In `confirm` mode, write actions return a preview (no execution). In `autonomous` mode, execution proceeds |
| **Subtool permissions** | Labs can restrict which actions are available to the agent |
| **Hot wallet required** | Write actions fail if the specified wallet address has no loaded private key |

### Confirmation Mode

| Mode | Behavior |
|------|----------|
| `confirm` (default) | Write actions return a formatted preview with amounts, USD estimates, and addresses. No on-chain transaction is sent. The agent must inform the user. |
| `autonomous` | Write actions execute after passing safety checks. Transactions are signed and broadcast. |

> **Recommendation**: Start with `confirm` mode. Switch to `autonomous` per-lab only after validating that the agent's behavior is correct and limits are properly set.

### USD Estimation

USD values are estimated via [Blockscout](https://blockscout.com/) APIs:
- **Native tokens**: fetched from `/api/v2/stats` (coin_price field)
- **ERC-20 tokens**: fetched from `/api/v2/tokens/{address}` (exchange_rate field)

If Blockscout cannot provide a price, `usd_value` is `None` and the `max_tx_usd` check is skipped.

---

## Database Schema

### `trading_positions`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `wallet_address` | VARCHAR(42) | Wallet that holds the position |
| `chain` | VARCHAR(20) | Chain name |
| `token_address` | VARCHAR(42) | Token contract address |
| `token_symbol` | VARCHAR(20) | Token ticker |
| `amount` | DOUBLE PRECISION | Token amount |
| `entry_price_usd` | DOUBLE PRECISION | Entry price per unit in USD |
| `entry_tx_hash` | VARCHAR(66) | Transaction hash of the entry |
| `entry_at` | TIMESTAMPTZ | Timestamp of position opening |
| `exit_price_usd` | DOUBLE PRECISION | Exit price per unit in USD |
| `exit_tx_hash` | VARCHAR(66) | Transaction hash of the exit |
| `exit_at` | TIMESTAMPTZ | Timestamp of position closing |
| `status` | VARCHAR(20) | `open`, `closed`, or `stopped` |
| `stop_loss_usd` | DOUBLE PRECISION | Stop-loss trigger price |
| `take_profit_usd` | DOUBLE PRECISION | Take-profit trigger price |
| `notes` | TEXT | Free-text notes |
| `lab_id` | UUID | Lab that opened the position |

**Indexes:** `wallet_address`, `chain`, `status`, `lab_id`

### `trade_history`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `wallet_address` | VARCHAR(42) | Wallet that executed the trade |
| `chain` | VARCHAR(20) | Chain name |
| `tx_hash` | VARCHAR(66) | Transaction hash |
| `tx_type` | VARCHAR(20) | `swap`, `send`, `receive`, `approve` |
| `from_token` | VARCHAR(42) | Source token address |
| `from_token_symbol` | VARCHAR(20) | Source token symbol |
| `from_amount` | VARCHAR(78) | Amount sent (string for precision) |
| `to_token` | VARCHAR(42) | Destination token address |
| `to_token_symbol` | VARCHAR(20) | Destination token symbol |
| `to_amount` | VARCHAR(78) | Amount received |
| `gas_used` | INTEGER | Gas units consumed |
| `gas_price_gwei` | DOUBLE PRECISION | Gas price at execution |
| `value_usd` | DOUBLE PRECISION | Estimated USD value of the trade |
| `timestamp` | TIMESTAMPTZ | Execution timestamp |
| `position_id` | UUID | Linked position (if any) |
| `lab_id` | UUID | Lab that executed the trade |

**Indexes:** `wallet_address`, `lab_id`, `timestamp DESC`

**Migration:** `023_trading.sql`

---

## DEX Integration

### 1inch Fusion API (Aggregator)

Used as the primary swap route. The aggregator finds the best price across multiple DEXes and liquidity sources.

- **Endpoint:** `https://api.1inch.dev/swap/v6.0/{chainId}/`
- **Auth:** Optional `ONEINCH_API_KEY` Bearer token
- **Quote:** `GET /quote` — returns best price without building a transaction
- **Swap:** `GET /swap` — returns a signed calldata transaction ready to broadcast

### Uniswap V2 / PancakeSwap V2 (Fallback)

If the 1inch API is unavailable or returns an error, swaps fall back to direct router calls:

| Chain | Router | Address |
|-------|--------|---------|
| Ethereum | Uniswap V2 | `0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D` |
| Base | Uniswap V2 | `0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24` |
| BNB | PancakeSwap V2 | `0x10ED43C718714eb63d5aA57B78B54704E256024E` |

Router methods used:
- `getAmountsOut` — quote
- `swapExactETHForTokens` — native → token
- `swapExactTokensForETH` — token → native
- `swapExactTokensForTokens` — token → token

Deadline: 5 minutes from current block timestamp.

### Uniswap V3 (Prepared, Not Yet Active)

V3 router ABIs and NonfungiblePositionManager addresses are stored in `CHAIN_CONFIG` for future LP position management:

| Chain | V3 Router | NFT Position Manager |
|-------|-----------|---------------------|
| Ethereum | `0xE592427A0AEce92De3Edee1F18E0157C05861564` | `0xC36442b4a4522E871399CD717aBDD847Ab11FE88` |
| Base | `0x2626664c2603336E57B271c5C0b26F421741e481` | `0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1` |
| BNB | — | `0x46A15B0b27311cedF172AB29E4f4766fbE7F4364` (PancakeSwap V3) |

---

## File Reference

| File | Purpose |
|------|---------|
| `control-plane/app/services/trading_service.py` | Core engine: wallet loading, chain config, gas, balances, tx signing, 1inch integration, V2 router calls, USD estimation |
| `control-plane/app/services/tools/tool_trading.py` | Agent-facing trading tool: 15 actions, safety checks, confirmation mode |
| `control-plane/app/services/tools/tool_defi_data.py` | Agent-facing DeFi data tool: 8 actions, CoinGecko/DeFiLlama/DEX Screener |
| `control-plane/app/models/trading.py` | SQLAlchemy ORM models: `TradingPosition`, `TradeHistory` |
| `control-plane/app/repositories/trading_repo.py` | Data access: open/close positions, record trades, query history |
| `control-plane/app/migrations/init.sql` | Consolidated schema: trading tables and indexes |
| `control-plane/app/api/routes/tool_configs.py` | Tool config schema: `trading` entry with safety parameters |
| `control-plane/requirements.txt` | Dependencies: `web3>=7.0`, `eth-account>=0.13.0` |

## Related Documents

- [WEB3.md](WEB3.md) — Wallet tracking, portfolio snapshots, `blockchain` read-only tool
- [TOOLS_AND_SANDBOX.md](TOOLS_AND_SANDBOX.md) — All built-in tools reference
- [LABS.md](LABS.md) — Lab system: tool assignment, subtool permissions
- [CONFIGURATION.md](CONFIGURATION.md) — Environment variables
- [API_REFERENCE.md](API_REFERENCE.md) — REST endpoint listing
