"""Read-only tracked-wallet portfolio tool for labs."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from app.repositories.web3_repo import LabWeb3AccessRepository
from app.services.web3_service import (
    get_portfolio_history,
    get_wallet_balances,
    get_wallet_record,
    get_wallet_token_transfers,
    get_wallet_transactions,
)

if TYPE_CHECKING:
    from app.services.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)

TOOLS = {
    "web3_portfolio": {
        "description": (
            "Read-only tracked-wallet portfolio tool for labs. "
            "Actions: list_addresses, wallet_balances, wallet_transactions, portfolio_total, portfolio_history. "
            "Returns structured JSON so advisory agents can reason over tracked addresses without private keys."
        ),
        "parameters": {
            "action": {
                "type": "string",
                "description": "Action: list_addresses, wallet_balances, wallet_transactions, portfolio_total, portfolio_history",
                "required": True,
            },
            "wallet_id": {
                "type": "string",
                "description": "Tracked wallet UUID from list_addresses",
                "required": False,
            },
            "chain": {
                "type": "string",
                "description": "Optional chain filter for wallet_transactions: ethereum, base, bnb",
                "required": False,
            },
            "hours": {
                "type": "integer",
                "description": "History window for portfolio_history (default 24, max 8760)",
                "required": False,
            },
        },
    },
}


def _json_output(payload: dict) -> dict:
    return {"success": True, "output": json.dumps(payload, indent=2, sort_keys=True)}


async def _get_allowed_wallets(executor) -> list[dict]:
    rows = await LabWeb3AccessRepository(executor.db).get_by_lab(executor.lab_id)
    return [
        {
            "wallet_id": str(wallet.id),
            "address": wallet.address,
            "label": wallet.label,
        }
        for _, wallet in rows
    ]


async def _resolve_lab_wallet(executor, wallet_id: str):
    allowed_ids = set(await LabWeb3AccessRepository(executor.db).list_wallet_ids(executor.lab_id))
    wallet = await get_wallet_record(executor.db, wallet_id)
    if wallet is None:
        raise ValueError(f"Tracked wallet {wallet_id} not found")
    if wallet.id not in allowed_ids:
        raise ValueError(f"Tracked wallet {wallet_id} is not granted to this lab")
    return wallet


async def web3_portfolio(executor: ToolExecutor, args: dict) -> dict:
    action = (args.get("action") or "").strip().lower()
    if not action:
        return {"success": False, "output": "web3_portfolio requires 'action'"}

    allowed = executor._subtool_permissions.get("web3_portfolio", [])
    if allowed and action not in allowed:
        return {
            "success": False,
            "output": f"Action '{action}' not permitted. Allowed: {', '.join(allowed)}",
        }

    try:
        if action == "list_addresses":
            addresses = await _get_allowed_wallets(executor)
            return _json_output({"addresses": addresses, "count": len(addresses)})

        if action == "wallet_balances":
            wallet_id = (args.get("wallet_id") or "").strip()
            if not wallet_id:
                return {"success": False, "output": "wallet_balances requires 'wallet_id'"}
            wallet = await _resolve_lab_wallet(executor, wallet_id)
            balances = await get_wallet_balances(wallet.address)
            return _json_output(
                {
                    "wallet_id": str(wallet.id),
                    "address": wallet.address,
                    "label": wallet.label,
                    "chains": balances,
                }
            )

        if action == "wallet_transactions":
            wallet_id = (args.get("wallet_id") or "").strip()
            if not wallet_id:
                return {"success": False, "output": "wallet_transactions requires 'wallet_id'"}
            wallet = await _resolve_lab_wallet(executor, wallet_id)
            chain = (args.get("chain") or "ethereum").strip().lower()
            transactions = await get_wallet_transactions(wallet.address, chain)
            transfers = await get_wallet_token_transfers(wallet.address, chain)
            return _json_output(
                {
                    "wallet_id": str(wallet.id),
                    "address": wallet.address,
                    "label": wallet.label,
                    "chain": chain,
                    "transactions": transactions,
                    "token_transfers": transfers,
                }
            )

        if action == "portfolio_total":
            allowed_wallets = await _get_allowed_wallets(executor)
            wallet_rows = []
            total = 0.0
            for wallet_meta in allowed_wallets:
                balances = await get_wallet_balances(wallet_meta["address"])
                wallet_total = round(
                    sum(
                        (chain_data.get("total_value_usd") or 0) for chain_data in balances.values()
                    ),
                    2,
                )
                total += wallet_total
                wallet_rows.append(
                    {
                        "wallet_id": wallet_meta["wallet_id"],
                        "address": wallet_meta["address"],
                        "label": wallet_meta["label"],
                        "total_value_usd": wallet_total,
                    }
                )
            return _json_output(
                {
                    "wallet_count": len(wallet_rows),
                    "total_value_usd": round(total, 2),
                    "wallets": wallet_rows,
                }
            )

        if action == "portfolio_history":
            hours = min(max(int(args.get("hours") or 24), 1), 8760)
            wallet_id = (args.get("wallet_id") or "").strip() or None
            if wallet_id:
                wallet = await _resolve_lab_wallet(executor, wallet_id)
                history = await get_portfolio_history(
                    executor.db,
                    wallet_id=str(wallet.id),
                    hours=hours,
                )
            else:
                allowed_ids = await LabWeb3AccessRepository(executor.db).list_wallet_ids(
                    executor.lab_id
                )
                allowed_id_strs = {str(wallet_id) for wallet_id in allowed_ids}
                history = []
                for row in await get_portfolio_history(executor.db, hours=hours):
                    wallets = {
                        wallet_key: wallet_data
                        for wallet_key, wallet_data in row.get("wallets", {}).items()
                        if wallet_key in allowed_id_strs
                    }
                    if wallets:
                        history.append(
                            {
                                "ts": row.get("ts"),
                                "total_value_usd": round(
                                    sum(
                                        (wallet_data or {}).get("value", 0)
                                        for wallet_data in wallets.values()
                                    ),
                                    2,
                                ),
                                "wallets": wallets,
                            }
                        )
            return _json_output(
                {
                    "hours": hours,
                    "wallet_id": wallet_id,
                    "history": history,
                }
            )

        return {"success": False, "output": f"Unknown action: {action}"}
    except ValueError as exc:
        return {"success": False, "output": str(exc)}
    except Exception as exc:
        logger.exception("web3_portfolio error: %s", exc)
        return {"success": False, "output": f"web3_portfolio error: {exc}"}


HANDLERS = {
    "web3_portfolio": web3_portfolio,
}
