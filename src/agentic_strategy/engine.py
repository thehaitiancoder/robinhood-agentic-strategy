from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Mapping

from .ladder import (
    DueDoubleDownLot,
    combined_due_lot_shares,
    due_double_down_lots,
    integer_part_quantity,
    lot_shares_for_target,
    sizing_mode_for_price,
)
from .models import (
    Decision,
    PortfolioSnapshot,
    PositionSnapshot,
    QuoteSnapshot,
    StrategyConfig,
    StrategyReport,
    UniverseEntry,
    ZERO,
)
from .symbol_policy import SymbolPolicy, is_open_allowed


def evaluate_strategy(
    portfolio: PortfolioSnapshot,
    positions: list[PositionSnapshot],
    quotes: list[QuoteSnapshot],
    universe: list[UniverseEntry],
    config: StrategyConfig | None = None,
    symbol_policies: Mapping[str, SymbolPolicy] | None = None,
) -> StrategyReport:
    """Evaluate the strategy from read-only snapshots.

    This function never places orders. It only emits decisions and rule blocks.
    """

    cfg = config or StrategyConfig()
    quote_by_symbol = {quote.symbol.upper(): quote for quote in quotes}
    position_by_symbol = {position.symbol.upper(): position for position in positions}
    universe_by_symbol = {entry.symbol.upper(): entry for entry in universe}

    cash_floor = portfolio.total_value * cfg.cash_buffer_pct
    disposable_cash = portfolio.buying_power - cash_floor
    if disposable_cash < ZERO:
        disposable_cash = ZERO

    decisions: list[Decision] = []
    due_double_downs: list[
        tuple[PositionSnapshot, QuoteSnapshot, Decimal, Decimal, list[DueDoubleDownLot]]
    ] = []
    sell_ready_symbols: set[str] = set()

    for position in sorted(positions, key=lambda item: item.symbol):
        symbol = position.symbol.upper()
        quote = quote_by_symbol.get(symbol)
        if quote is None:
            decisions.append(
                Decision(
                    action="block",
                    priority=90,
                    symbol=symbol,
                    reason="missing quote for owned position",
                )
            )
            continue

        sell_price = quote.sell_price
        if sell_price is None:
            decisions.append(
                Decision(
                    action="block",
                    priority=90,
                    symbol=symbol,
                    reason="missing sell-side price for owned position",
                )
            )
            continue

        market_value = sell_price * position.quantity
        return_pct = _return_pct(market_value, position.invested_cost)
        target_price = _target_sell_price(position, cfg)

        if return_pct >= cfg.profit_take_pct:
            sell_ready_symbols.add(symbol)
            decisions.append(
                Decision(
                    action="sell_target",
                    priority=1,
                    symbol=symbol,
                    reason="combined position return is at or above target",
                    metrics={
                        "return_pct": _str_pct(return_pct),
                        "sell_price": _money(sell_price),
                        "target_sell_price": _money(target_price),
                        "quantity": str(position.quantity),
                        "estimated_value": _money(market_value),
                    },
                )
            )
            continue

        buy_price = quote.buy_price
        if (
            buy_price is not None
            and position.next_trigger_price is not None
            and position.next_lot_shares is not None
            and buy_price <= position.next_trigger_price
        ):
            due_lots = due_double_down_lots(
                current_lot_index=position.current_lot_index,
                next_trigger=position.next_trigger_price,
                next_shares=position.next_lot_shares,
                buy_price=buy_price,
            )
            order_quantity = combined_due_lot_shares(due_lots)
            estimated_cost = buy_price * order_quantity
            due_double_downs.append((position, quote, buy_price, estimated_cost, due_lots))

    due_symbols = {position.symbol.upper() for position, _, _, _, _ in due_double_downs}
    reserved_cash = ZERO
    for position, quote, buy_price, estimated_cost, due_lots in sorted(
        due_double_downs,
        key=lambda item: _trigger_urgency(item[2], item[0].next_trigger_price),
        reverse=True,
    ):
        symbol = position.symbol.upper()
        if symbol in sell_ready_symbols:
            continue

        concentration = _post_trade_position_pct(
            portfolio=portfolio,
            position=position,
            quote=quote,
            estimated_cost=estimated_cost,
        )
        order_quantity = combined_due_lot_shares(due_lots)
        guard_trigger = due_lots[-1].trigger_price
        metrics = {
            "buy_price": _money(buy_price),
            "trigger_price": _money(position.next_trigger_price),
            "price_guard_trigger": _money(guard_trigger),
            "next_lot_shares": str(position.next_lot_shares),
            "due_lots": ",".join(str(lot.lot_index) for lot in due_lots),
            "combined_due_lot_count": str(len(due_lots)),
            "order_sizing": "exact_share_quantity",
            "order_quantity": str(order_quantity),
            "order_amount_source": "estimate_only_do_not_place_dd_by_dollar_amount",
            "fractional_reject_fallback": "retry_integer_part_when_at_least_1_share",
            "integer_part_quantity": str(integer_part_quantity(order_quantity)),
            "estimated_cost": _money(estimated_cost),
            "post_trade_position_pct": _str_pct(concentration),
        }

        if concentration > config_value(cfg.max_single_position_pct):
            decisions.append(
                Decision(
                    action="block_double_down",
                    priority=2,
                    symbol=symbol,
                    reason="double-down would exceed max single-position allocation",
                    metrics=metrics,
                )
            )
            continue

        if reserved_cash + estimated_cost > disposable_cash:
            decisions.append(
                Decision(
                    action="cash_short_double_down",
                    priority=2,
                    symbol=symbol,
                    reason="double-down is due but disposable cash is insufficient",
                    metrics=metrics | {"disposable_cash": _money(disposable_cash)},
                )
            )
            continue

        reserved_cash += estimated_cost
        decisions.append(
            Decision(
                action="double_down_ready",
                priority=2,
                symbol=symbol,
                reason="price reached the next ladder trigger",
                metrics=metrics | {"cash_reserved_after": _money(reserved_cash)},
            )
        )

    if due_symbols:
        decisions.extend(
            _emergency_sell_candidates(
                positions=positions,
                quote_by_symbol=quote_by_symbol,
                config=cfg,
                due_symbols=due_symbols,
            )
        )
        decisions.append(
            Decision(
                action="pause_new_positions",
                priority=3,
                symbol=None,
                reason="one or more owned positions are due for double-down",
                metrics={"due_symbols": sorted(due_symbols)},
            )
        )
    else:
        decisions.extend(
            _new_open_candidates(
                portfolio=portfolio,
                positions_by_symbol=position_by_symbol,
                quote_by_symbol=quote_by_symbol,
                universe_by_symbol=universe_by_symbol,
                config=cfg,
                disposable_cash=disposable_cash,
                symbol_policies=symbol_policies,
            )
        )

    decisions.sort(key=_decision_sort_key)
    counts = Counter(decision.action for decision in decisions)
    summary = {
        "portfolio_value": _money(portfolio.total_value),
        "buying_power": _money(portfolio.buying_power),
        "cash_floor": _money(cash_floor),
        "disposable_cash": _money(disposable_cash),
        "positions": len(positions),
        "quotes": len(quotes),
        "universe_symbols": len(universe),
        "decision_counts": dict(sorted(counts.items())),
    }
    return StrategyReport(summary=summary, decisions=decisions)


def _new_open_candidates(
    *,
    portfolio: PortfolioSnapshot,
    positions_by_symbol: dict[str, PositionSnapshot],
    quote_by_symbol: dict[str, QuoteSnapshot],
    universe_by_symbol: dict[str, UniverseEntry],
    config: StrategyConfig,
    disposable_cash: Decimal,
    symbol_policies: Mapping[str, SymbolPolicy] | None,
) -> list[Decision]:
    decisions: list[Decision] = []
    selected = 0
    spend_after_candidates = ZERO

    for symbol in sorted(universe_by_symbol):
        if selected >= config.max_new_open_candidates:
            break
        if symbol in positions_by_symbol:
            continue

        entry = universe_by_symbol[symbol]
        if not entry.active:
            continue
        if not entry.tradable:
            continue
        if not is_open_allowed(symbol, symbol_policies):
            continue

        quote = quote_by_symbol.get(symbol)
        if quote is None or quote.buy_price is None:
            continue

        buy_price = quote.buy_price
        sizing_mode = sizing_mode_for_price(buy_price)
        if sizing_mode == "dollar_fractional" and not entry.fractional_eligible:
            continue

        estimated_quantity = lot_shares_for_target(buy_price, config.open_base_usd)
        estimated_cost = estimated_quantity * buy_price
        if spend_after_candidates + estimated_cost > disposable_cash:
            decisions.append(
                Decision(
                    action="block_new_open",
                    priority=8,
                    symbol=symbol,
                    reason="cash buffer would be breached by additional openings",
                    metrics={
                        "open_base_usd": _money(config.open_base_usd),
                        "disposable_cash": _money(disposable_cash),
                    },
                )
            )
            break

        post_position_pct = estimated_cost / portfolio.total_value if portfolio.total_value else Decimal("1")
        if post_position_pct > config.max_single_position_pct:
            decisions.append(
                Decision(
                    action="block_new_open",
                    priority=8,
                    symbol=symbol,
                    reason="new position would exceed max single-position allocation",
                    metrics={"post_trade_position_pct": _str_pct(post_position_pct)},
                )
            )
            continue

        spend_after_candidates += estimated_cost
        selected += 1
        decisions.append(
            Decision(
                action="new_open_candidate",
                priority=5,
                symbol=symbol,
                reason="eligible unowned symbol and no double-downs are due",
                metrics={
                    "buy_price": _money(buy_price),
                    "open_base_usd": _money(config.open_base_usd),
                    "estimated_quantity": str(estimated_quantity),
                    "estimated_cost": _money(estimated_cost),
                    "sizing_mode": sizing_mode,
                    "cash_reserved_after": _money(spend_after_candidates),
                },
            )
        )

    return decisions


def _emergency_sell_candidates(
    *,
    positions: list[PositionSnapshot],
    quote_by_symbol: dict[str, QuoteSnapshot],
    config: StrategyConfig,
    due_symbols: set[str],
) -> list[Decision]:
    candidates: list[Decision] = []
    for position in positions:
        symbol = position.symbol.upper()
        if symbol in due_symbols:
            continue

        quote = quote_by_symbol.get(symbol)
        if quote is None or quote.sell_price is None:
            continue

        market_value = quote.sell_price * position.quantity
        return_pct = _return_pct(market_value, position.invested_cost)
        if config.emergency_sell_min_return_pct <= return_pct < config.profit_take_pct:
            candidates.append(
                Decision(
                    action="emergency_green_sell_candidate",
                    priority=4,
                    symbol=symbol,
                    reason="green position can be sold below target if cash is needed for double-downs",
                    metrics={
                        "return_pct": _str_pct(return_pct),
                        "estimated_value": _money(market_value),
                    },
                )
            )

    return sorted(
        candidates,
        key=lambda decision: Decimal(str(decision.metrics["return_pct"]).rstrip("%")),
        reverse=True,
    )


def _decision_sort_key(decision: Decision) -> tuple[int, Decimal, str, str]:
    secondary = ZERO
    if decision.action == "emergency_green_sell_candidate":
        secondary = -_pct_metric_value(decision, "return_pct")
    return (decision.priority, secondary, decision.symbol or "", decision.action)


def _pct_metric_value(decision: Decision, key: str) -> Decimal:
    value = decision.metrics.get(key)
    if value is None:
        return ZERO
    return Decimal(str(value).rstrip("%"))


def _return_pct(market_value: Decimal, invested_cost: Decimal) -> Decimal:
    if invested_cost == ZERO:
        return ZERO
    return (market_value - invested_cost) / invested_cost


def _target_sell_price(position: PositionSnapshot, config: StrategyConfig) -> Decimal:
    if position.quantity == ZERO:
        return ZERO
    return (position.invested_cost * (Decimal("1") + config.profit_take_pct)) / position.quantity


def _post_trade_position_pct(
    *,
    portfolio: PortfolioSnapshot,
    position: PositionSnapshot,
    quote: QuoteSnapshot,
    estimated_cost: Decimal,
) -> Decimal:
    mark = quote.sell_price or quote.buy_price
    if mark is None or portfolio.total_value == ZERO:
        return Decimal("1")
    post_trade_value = (mark * position.quantity) + estimated_cost
    return post_trade_value / portfolio.total_value


def _trigger_urgency(buy_price: Decimal, trigger_price: Decimal | None) -> Decimal:
    if trigger_price is None or trigger_price == ZERO:
        return ZERO
    return (trigger_price - buy_price) / trigger_price


def _money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.0001")))


def _str_pct(value: Decimal) -> str:
    return f"{(value * Decimal('100')).quantize(Decimal('0.0001'))}%"


def config_value(value: Decimal) -> Decimal:
    return value
