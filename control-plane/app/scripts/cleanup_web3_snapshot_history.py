"""One-off cleanup for historical Web3 snapshot dropouts.

Rewrites bad portfolio snapshot rows in-place by carrying forward the last good
per-chain values when a short transient fetch failure produced a zero or missing
component in the stored breakdown.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from decimal import Decimal

from sqlalchemy import select

from app.database import async_session
from app.models.portfolio_snapshot import PortfolioSnapshot

_DIP_RATIO = 0.9
_RECOVERY_TOLERANCE = 0.18
_MAX_TRANSIENT_RUN_LENGTH = 8
_MAX_TRAILING_TRANSIENT_RUN_LENGTH = 2
_MIN_COMPONENT_TRANSIENT_DROP_USD = 40.0


def _to_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _values_close(a: float, b: float, tolerance: float = _RECOVERY_TOLERANCE) -> bool:
    baseline = max(abs(a), abs(b), 1.0)
    return abs(a - b) / baseline <= tolerance


def _find_repair_ranges(values: list[float]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []

    index = 1
    while index < len(values) - 1:
        previous = values[index - 1]
        current = values[index]
        if (
            previous <= 0
            or current >= previous * _DIP_RATIO
            or (previous - current) < _MIN_COMPONENT_TRANSIENT_DROP_USD
        ):
            index += 1
            continue

        run_start = index
        run_end = index
        while run_end < len(values):
            candidate = values[run_end]
            if candidate >= previous * _DIP_RATIO or (previous - candidate) < _MIN_COMPONENT_TRANSIENT_DROP_USD:
                break
            run_end += 1

        if run_end >= len(values):
            break

        next_value = values[run_end]
        run_length = run_end - run_start
        if (
            run_length <= _MAX_TRANSIENT_RUN_LENGTH
            and next_value > 0
            and _values_close(previous, next_value)
        ):
            ranges.append((run_start, run_end))

        index = max(run_end, index + 1)

    trail_start = len(values)
    while trail_start > 1:
        candidate_index = trail_start - 1
        previous = values[candidate_index - 1]
        candidate = values[candidate_index]
        if (
            previous <= 0
            or candidate >= previous * _DIP_RATIO
            or (previous - candidate) < _MIN_COMPONENT_TRANSIENT_DROP_USD
        ):
            break
        trail_start = candidate_index

    trailing_run_length = len(values) - trail_start
    if 0 < trailing_run_length <= _MAX_TRAILING_TRANSIENT_RUN_LENGTH:
        ranges.append((trail_start, len(values)))

    return ranges


def _row_total_usd(row: PortfolioSnapshot) -> float:
    breakdown = row.breakdown or {}
    return round(
        sum(_to_float((chain_data or {}).get("total_usd")) for chain_data in breakdown.values()),
        2,
    )


async def main() -> None:
    async with async_session() as db:
        result = await db.execute(
            select(PortfolioSnapshot).order_by(PortfolioSnapshot.wallet_id.asc(), PortfolioSnapshot.ts.asc())
        )
        rows = result.scalars().all()

        per_wallet: dict[str, list[PortfolioSnapshot]] = {}
        for row in rows:
            per_wallet.setdefault(str(row.wallet_id), []).append(row)

        updated_rows: set[tuple[str, str]] = set()
        updated_components = 0

        for wallet_id, wallet_rows in per_wallet.items():
            chain_ids = sorted(
                {
                    chain_id
                    for row in wallet_rows
                    for chain_id in (row.breakdown or {}).keys()
                }
            )
            if not chain_ids:
                continue

            for chain_id in chain_ids:
                chain_totals = [
                    _to_float(((row.breakdown or {}).get(chain_id) or {}).get("total_usd"))
                    for row in wallet_rows
                ]
                for start, end in _find_repair_ranges(chain_totals):
                    replacement = deepcopy((wallet_rows[start - 1].breakdown or {}).get(chain_id))
                    if not replacement:
                        continue
                    for index in range(start, end):
                        row = wallet_rows[index]
                        breakdown = dict(row.breakdown or {})
                        if breakdown.get(chain_id) == replacement:
                            continue
                        breakdown[chain_id] = deepcopy(replacement)
                        row.breakdown = breakdown
                        updated_rows.add((wallet_id, row.ts.isoformat()))
                        updated_components += 1

            for row in wallet_rows:
                new_total = _row_total_usd(row)
                current_total = _to_float(row.total_value_usd)
                if abs(current_total - new_total) > 0.005:
                    row.total_value_usd = Decimal(f"{new_total:.2f}")
                    updated_rows.add((wallet_id, row.ts.isoformat()))

        await db.commit()

    print(
        {
            "wallet_count": len(per_wallet),
            "updated_rows": len(updated_rows),
            "updated_components": updated_components,
        }
    )


if __name__ == "__main__":
    asyncio.run(main())