"""D03 — wei-integer ↔ decimal helpers.

Trading rows store on-chain amounts as integers in the token's smallest
unit (wei for 18-decimal tokens, satoshi for BTC, the micro-unit for
6-decimal stables). The integer is paired with the token's ``decimals``
metadata on the same row, so display code can faithfully render the
human-readable value via :func:`from_raw`.

The previous storage shape used Python floats for these columns —
``Float`` columns in SQLAlchemy + ``REAL`` in Postgres. Floats are
lossy by definition: ``Decimal('0.1') + Decimal('0.2')`` rounds to
``0.30000000000000004`` once it round-trips through a float column,
which is a non-starter for any column an auditor might later compare
against an on-chain log.

Reference decimals (extend ``KNOWN_TOKEN_DECIMALS`` as new tokens land):

  ETH / BNB / Base ETH / MATIC / DAI / most ERC-20  — 18
  BTC / WBTC                                        — 8
  USDC / USDT / USDC.e                              — 6

USD prices keep ``Numeric(38, 18)`` storage (no wei semantics) because
they're bounded and the Decimal arithmetic is fine in Postgres.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final, Union

NumberLike = Union[Decimal, int, str]

# Common defaults — extend as new tokens are added. The default fallback
# is 18 (the "if you don't know, assume ERC-20" convention).
KNOWN_TOKEN_DECIMALS: Final[dict[str, int]] = {
    "ETH": 18,
    "WETH": 18,
    "BNB": 18,
    "WBNB": 18,
    "MATIC": 18,
    "DAI": 18,
    "BTC": 8,
    "WBTC": 8,
    "USDC": 6,
    "USDT": 6,
    "USDC.E": 6,
}
DEFAULT_TOKEN_DECIMALS: Final[int] = 18


def _check_decimals(decimals: int) -> None:
    if decimals < 0:
        raise ValueError(f"decimals must be non-negative, got {decimals}")
    # 78 fits 2**256-1; anything beyond is meaningless on EVM-style chains.
    if decimals > 78:
        raise ValueError(f"decimals must be ≤ 78, got {decimals}")


def to_raw(amount: NumberLike, decimals: int) -> int:
    """Convert a human-readable amount to its on-chain integer.

    >>> to_raw(Decimal("1.5"), 18)
    1500000000000000000
    >>> to_raw("1", 8)
    100000000
    """
    _check_decimals(decimals)
    scaled = Decimal(amount) * (Decimal(10) ** decimals)
    return int(scaled.to_integral_value())


def from_raw(raw: NumberLike, decimals: int) -> Decimal:
    """Convert an on-chain integer back to a human-readable Decimal.

    >>> from_raw(1500000000000000000, 18)
    Decimal('1.5')
    >>> from_raw(100000000, 8)
    Decimal('1')
    """
    _check_decimals(decimals)
    return Decimal(raw) / (Decimal(10) ** decimals)


def decimals_for(symbol: str | None) -> int:
    """Look up a known symbol's decimals or fall back to 18.

    Case-insensitive. Unknown symbols return the safe ERC-20 default.
    """
    if not symbol:
        return DEFAULT_TOKEN_DECIMALS
    return KNOWN_TOKEN_DECIMALS.get(symbol.upper(), DEFAULT_TOKEN_DECIMALS)
