from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


LOT_SHARE_MULTIPLIER = Decimal("2")
TEN_PCT = Decimal("0.10")
TWENTY_PCT = Decimal("0.20")
FORTY_PCT = Decimal("0.40")
EIGHTY_PCT = Decimal("0.80")


@dataclass(frozen=True)
class LadderLot:
    lot_index: int
    trigger_price: Decimal
    lot_shares: Decimal
    drop_pct: Decimal


def drop_pct_for_next_lot(next_lot_index: int) -> Decimal:
    if next_lot_index < 2:
        raise ValueError("next_lot_index must be 2 or greater")
    if next_lot_index <= 5:
        return TEN_PCT
    if next_lot_index <= 10:
        return TWENTY_PCT
    if next_lot_index <= 15:
        return FORTY_PCT
    return EIGHTY_PCT


def next_trigger_price(previous_trigger_price: Decimal, next_lot_index: int) -> Decimal:
    return previous_trigger_price * (Decimal("1") - drop_pct_for_next_lot(next_lot_index))


def next_lot_shares(previous_lot_shares: Decimal) -> Decimal:
    return previous_lot_shares * LOT_SHARE_MULTIPLIER


def build_ladder(entry_price: Decimal, base_usd: Decimal, through_lot_index: int) -> list[LadderLot]:
    if through_lot_index < 1:
        raise ValueError("through_lot_index must be 1 or greater")
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if base_usd <= 0:
        raise ValueError("base_usd must be positive")

    lots = [
        LadderLot(
            lot_index=1,
            trigger_price=entry_price,
            lot_shares=base_usd / entry_price,
            drop_pct=Decimal("0"),
        )
    ]

    while len(lots) < through_lot_index:
        previous = lots[-1]
        next_index = previous.lot_index + 1
        lots.append(
            LadderLot(
                lot_index=next_index,
                trigger_price=next_trigger_price(previous.trigger_price, next_index),
                lot_shares=next_lot_shares(previous.lot_shares),
                drop_pct=drop_pct_for_next_lot(next_index),
            )
        )

    return lots
