from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR


LOT_SHARE_MULTIPLIER = Decimal("2")
TEN_PCT = Decimal("0.10")
TWENTY_PCT = Decimal("0.20")
FORTY_PCT = Decimal("0.40")
EIGHTY_PCT = Decimal("0.80")
WHOLE_SHARE_THRESHOLD = Decimal("1.00")
UNDER5_ENTRY_PRICE_THRESHOLD = Decimal("5.00")
STANDARD_LADDER_PROFILE = "standard"
UNDER5_20_LADDER_PROFILE = "under5_20"
REF2023_UNDER5_LADDER_PROFILE = "ref2023_under5"


@dataclass(frozen=True)
class LadderLot:
    lot_index: int
    trigger_price: Decimal
    lot_shares: Decimal
    drop_pct: Decimal
    sizing_mode: str
    ladder_profile: str = STANDARD_LADDER_PROFILE


@dataclass(frozen=True)
class DueDoubleDownLot:
    lot_index: int
    trigger_price: Decimal
    lot_shares: Decimal
    ladder_profile: str = STANDARD_LADDER_PROFILE


def ladder_profile_for_entry_price(entry_price: Decimal) -> str:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if entry_price < UNDER5_ENTRY_PRICE_THRESHOLD:
        return UNDER5_20_LADDER_PROFILE
    return STANDARD_LADDER_PROFILE


def ladder_profile_for_open_lot_count(entry_price: Decimal, open_lot_count: int) -> str:
    if open_lot_count < 1:
        raise ValueError("open_lot_count must be positive")
    if open_lot_count == 1:
        return ladder_profile_for_entry_price(entry_price)
    return STANDARD_LADDER_PROFILE


def normalize_ladder_profile(ladder_profile: str | None) -> str:
    profile = (ladder_profile or STANDARD_LADDER_PROFILE).strip().lower()
    if profile == REF2023_UNDER5_LADDER_PROFILE:
        return UNDER5_20_LADDER_PROFILE
    if profile not in {STANDARD_LADDER_PROFILE, UNDER5_20_LADDER_PROFILE}:
        raise ValueError(f"unknown ladder_profile: {ladder_profile}")
    return profile


def drop_pct_for_next_lot(
    next_lot_index: int,
    *,
    ladder_profile: str = STANDARD_LADDER_PROFILE,
) -> Decimal:
    if next_lot_index < 2:
        raise ValueError("next_lot_index must be 2 or greater")
    profile = normalize_ladder_profile(ladder_profile)
    if profile == UNDER5_20_LADDER_PROFILE:
        if next_lot_index <= 11:
            return TWENTY_PCT
        return FORTY_PCT
    if next_lot_index <= 5:
        return TEN_PCT
    if next_lot_index <= 10:
        return TWENTY_PCT
    if next_lot_index <= 15:
        return FORTY_PCT
    return EIGHTY_PCT


def next_trigger_price(
    previous_trigger_price: Decimal,
    next_lot_index: int,
    *,
    ladder_profile: str = STANDARD_LADDER_PROFILE,
) -> Decimal:
    return previous_trigger_price * (
        Decimal("1") - drop_pct_for_next_lot(next_lot_index, ladder_profile=ladder_profile)
    )


def next_lot_shares(previous_lot_shares: Decimal) -> Decimal:
    return previous_lot_shares * LOT_SHARE_MULTIPLIER


def due_double_down_lots(
    *,
    current_lot_index: int,
    next_trigger: Decimal,
    next_shares: Decimal,
    buy_price: Decimal,
    max_lot_index: int = 100,
    ladder_profile: str = STANDARD_LADDER_PROFILE,
) -> list[DueDoubleDownLot]:
    if current_lot_index < 1:
        raise ValueError("current_lot_index must be positive")
    if next_trigger <= 0:
        raise ValueError("next_trigger must be positive")
    if next_shares <= 0:
        raise ValueError("next_shares must be positive")
    if buy_price <= 0:
        raise ValueError("buy_price must be positive")
    if max_lot_index <= current_lot_index:
        raise ValueError("max_lot_index must exceed current_lot_index")
    profile = normalize_ladder_profile(ladder_profile)

    lots: list[DueDoubleDownLot] = []
    lot_index = current_lot_index + 1
    trigger_price = next_trigger
    lot_shares = next_shares

    while lot_index <= max_lot_index and buy_price <= trigger_price:
        lots.append(
            DueDoubleDownLot(
                lot_index=lot_index,
                trigger_price=trigger_price,
                lot_shares=lot_shares,
                ladder_profile=profile,
            )
        )
        lot_index += 1
        if lot_index <= max_lot_index:
            trigger_price = next_trigger_price(trigger_price, lot_index, ladder_profile=profile)
            lot_shares = next_lot_shares(lot_shares)

    return lots


def combined_due_lot_shares(lots: list[DueDoubleDownLot]) -> Decimal:
    return sum((lot.lot_shares for lot in lots), Decimal("0"))


def integer_part_quantity(quantity: Decimal) -> Decimal:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    return quantity.to_integral_value(rounding=ROUND_FLOOR)


def lot_shares_for_target(price: Decimal, target_usd: Decimal) -> Decimal:
    if price <= 0:
        raise ValueError("price must be positive")
    if target_usd <= 0:
        raise ValueError("target_usd must be positive")
    if price < WHOLE_SHARE_THRESHOLD:
        shares = (target_usd / price).to_integral_value(rounding=ROUND_FLOOR)
        return max(shares, Decimal("1"))
    return target_usd / price


def sizing_mode_for_price(price: Decimal) -> str:
    if price < WHOLE_SHARE_THRESHOLD:
        return "whole_share_quantity"
    return "dollar_fractional"


def build_ladder(
    entry_price: Decimal,
    base_usd: Decimal,
    through_lot_index: int,
    *,
    ladder_profile: str | None = None,
) -> list[LadderLot]:
    if through_lot_index < 1:
        raise ValueError("through_lot_index must be 1 or greater")
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if base_usd <= 0:
        raise ValueError("base_usd must be positive")
    profile = normalize_ladder_profile(ladder_profile or ladder_profile_for_entry_price(entry_price))

    lots = [
        LadderLot(
            lot_index=1,
            trigger_price=entry_price,
            lot_shares=lot_shares_for_target(entry_price, base_usd),
            drop_pct=Decimal("0"),
            sizing_mode=sizing_mode_for_price(entry_price),
            ladder_profile=profile,
        )
    ]

    while len(lots) < through_lot_index:
        previous = lots[-1]
        next_index = previous.lot_index + 1
        lots.append(
            LadderLot(
                lot_index=next_index,
                trigger_price=next_trigger_price(
                    previous.trigger_price,
                    next_index,
                    ladder_profile=profile,
                ),
                lot_shares=next_lot_shares(previous.lot_shares),
                drop_pct=drop_pct_for_next_lot(next_index, ladder_profile=profile),
                sizing_mode=previous.sizing_mode,
                ladder_profile=profile,
            )
        )

    return lots
