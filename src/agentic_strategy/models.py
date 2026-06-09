from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


ZERO = Decimal("0")


@dataclass(frozen=True)
class StrategyConfig:
    cash_buffer_pct: Decimal = Decimal("0.10")
    max_single_position_pct: Decimal = Decimal("0.10")
    profit_take_pct: Decimal = Decimal("0.10")
    emergency_sell_min_return_pct: Decimal = Decimal("0.00")
    open_base_usd: Decimal = Decimal("1.00")
    max_new_open_candidates: int = 25


@dataclass(frozen=True)
class PortfolioSnapshot:
    total_value: Decimal
    buying_power: Decimal
    cash: Decimal | None = None

    @property
    def cash_value(self) -> Decimal:
        return self.cash if self.cash is not None else self.buying_power


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    quantity: Decimal
    invested_cost: Decimal
    current_lot_index: int = 1
    next_trigger_price: Decimal | None = None
    next_lot_shares: Decimal | None = None

    @property
    def average_cost(self) -> Decimal:
        if self.quantity == ZERO:
            return ZERO
        return self.invested_cost / self.quantity


@dataclass(frozen=True)
class QuoteSnapshot:
    symbol: str
    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    last_price: Decimal | None = None
    updated_at: str | None = None

    @property
    def sell_price(self) -> Decimal | None:
        return self.bid_price if self.bid_price is not None else self.last_price

    @property
    def buy_price(self) -> Decimal | None:
        return self.ask_price if self.ask_price is not None else self.last_price


@dataclass(frozen=True)
class UniverseEntry:
    symbol: str
    name: str = ""
    asset_type: str = "stock"
    tradable: bool = True
    fractional_eligible: bool = True
    active: bool = True


@dataclass(frozen=True)
class Decision:
    action: str
    priority: int
    symbol: str | None
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyReport:
    summary: dict[str, Any]
    decisions: list[Decision]
