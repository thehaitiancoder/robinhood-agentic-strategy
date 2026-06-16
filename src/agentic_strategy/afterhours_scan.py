from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_FLOOR
from pathlib import Path
from typing import Any

from .ladder import next_lot_shares, next_trigger_price


ACTIVE_ORDER_STATES = {"new", "queued", "unconfirmed", "confirmed", "partially_filled"}
ZERO = Decimal("0")


@dataclass(frozen=True)
class AfterHoursDoubleDownCandidate:
    symbol: str
    ask: Decimal
    bid: Decimal
    last_non_reg: Decimal
    last_trade: Decimal
    buy_price: Decimal
    buy_price_basis: str
    base_price: Decimal
    base_shares: Decimal
    position_qty: Decimal
    completed_lot: int
    partial_next: Decimal
    due_lots: str
    due_qty: Decimal
    integer_qty: Decimal
    decimal_left: Decimal
    deepest_trigger: Decimal
    suggested_limit: Decimal
    active_buy_count: int
    active_buy_details: str
    est_cost: Decimal


@dataclass(frozen=True)
class AfterHoursSellCandidate:
    symbol: str
    whole_qty: Decimal
    decimal_left: Decimal
    sellable_qty: Decimal
    average_buy_price: Decimal
    bid: Decimal
    ask: Decimal
    last_non_reg: Decimal
    last_trade: Decimal
    sell_price: Decimal
    sell_price_basis: str
    return_pct: Decimal
    suggested_limit: Decimal
    active_sell_count: int
    active_sell_details: str
    est_proceeds: Decimal


@dataclass(frozen=True)
class AfterHoursScanReport:
    checked_positions: int
    whole_share_dd: list[AfterHoursDoubleDownCandidate]
    fractional_dd: list[AfterHoursDoubleDownCandidate]
    whole_share_sells: list[AfterHoursSellCandidate]
    not_due_count: int
    no_history: list[str]
    incomplete: list[dict[str, str]]


def scan_afterhours(
    *,
    positions_payload: dict[str, Any],
    orders_payload: dict[str, Any],
    active_orders_payload: dict[str, Any] | None = None,
    sell_return_threshold: Decimal = Decimal("10"),
) -> AfterHoursScanReport:
    positions = _positions(positions_payload)
    quotes = _quotes_by_symbol(positions_payload)
    orders = _orders(orders_payload)
    active_orders = _orders(active_orders_payload or {})

    position_by_symbol = {
        _symbol(position): position
        for position in positions
        if _symbol(position) and _decimal(position.get("quantity")) > ZERO and position.get("type") != "empty"
    }
    owned_symbols = set(position_by_symbol)
    orders_by_symbol = _filled_orders_by_symbol(orders, owned_symbols)
    active_buys, active_sells = _active_orders_by_side(active_orders)

    whole_share_dd: list[AfterHoursDoubleDownCandidate] = []
    fractional_dd: list[AfterHoursDoubleDownCandidate] = []
    whole_share_sells: list[AfterHoursSellCandidate] = []
    no_history: list[str] = []
    incomplete: list[dict[str, str]] = []
    not_due_count = 0

    for symbol, position in sorted(position_by_symbol.items()):
        quote = quotes.get(symbol, {})
        sell_candidate = _sell_candidate(
            symbol=symbol,
            position=position,
            quote=quote,
            active_sells=active_sells.get(symbol, []),
            sell_return_threshold=sell_return_threshold,
        )
        if sell_candidate is not None:
            whole_share_sells.append(sell_candidate)

        lots = _reconstruct_open_lots(orders_by_symbol.get(symbol, []))
        position_qty = _decimal(position.get("quantity"))
        if not lots:
            no_history.append(symbol)
            continue

        calculated_qty = sum((lot["qty"] for lot in lots), ZERO)
        if abs(calculated_qty - position_qty) > Decimal("0.000010"):
            incomplete.append(
                {
                    "symbol": symbol,
                    "position_qty": str(position_qty),
                    "calculated_qty": str(calculated_qty),
                }
            )
            continue

        dd_candidate = _double_down_candidate(
            symbol=symbol,
            position_qty=position_qty,
            lots=lots,
            quote=quote,
            active_buys=active_buys.get(symbol, []),
        )
        if dd_candidate is None:
            not_due_count += 1
            continue
        if dd_candidate.integer_qty >= Decimal("1"):
            whole_share_dd.append(dd_candidate)
        else:
            fractional_dd.append(dd_candidate)

    whole_share_dd.sort(key=lambda item: (item.active_buy_count > 0, -item.est_cost, item.symbol))
    fractional_dd.sort(key=lambda item: (-item.due_qty, item.symbol))
    whole_share_sells.sort(key=lambda item: (item.active_sell_count > 0, -item.return_pct, item.symbol))

    return AfterHoursScanReport(
        checked_positions=len(position_by_symbol),
        whole_share_dd=whole_share_dd,
        fractional_dd=fractional_dd,
        whole_share_sells=whole_share_sells,
        not_due_count=not_due_count,
        no_history=no_history,
        incomplete=incomplete,
    )


def report_to_json(report: AfterHoursScanReport) -> dict[str, Any]:
    return {
        "checked_positions": report.checked_positions,
        "whole_share_dd_count": len(report.whole_share_dd),
        "fractional_dd_count": len(report.fractional_dd),
        "whole_share_sell_count": len(report.whole_share_sells),
        "not_due_count": report.not_due_count,
        "no_history_count": len(report.no_history),
        "incomplete_count": len(report.incomplete),
        "whole_share_dd": [_json_row(item) for item in report.whole_share_dd],
        "fractional_dd": [_json_row(item) for item in report.fractional_dd],
        "whole_share_sells": [_json_row(item) for item in report.whole_share_sells],
        "no_history_sample": report.no_history[:25],
        "incomplete_sample": report.incomplete[:25],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan owned positions for after-hours whole-share DD and sell candidates."
    )
    parser.add_argument(
        "--positions-json",
        required=True,
        help="JSON output from `node scripts/rh_fast.mjs positions --with-quotes`.",
    )
    parser.add_argument(
        "--orders-json",
        required=True,
        help="JSON output from `node scripts/rh_fast.mjs orders --all`.",
    )
    parser.add_argument(
        "--active-orders-json",
        help="Optional JSON output from active `node scripts/rh_fast.mjs orders`.",
    )
    parser.add_argument("--output", required=True, help="Where to write the scan JSON report.")
    parser.add_argument("--sell-return-pct", default="10", help="Sell threshold percentage.")
    args = parser.parse_args()

    report = scan_afterhours(
        positions_payload=_read_json(args.positions_json),
        orders_payload=_read_json(args.orders_json),
        active_orders_payload=_read_json(args.active_orders_json) if args.active_orders_json else None,
        sell_return_threshold=Decimal(args.sell_return_pct),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = report_to_json(report)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in payload if key.endswith("_count") or key == "checked_positions"}))
    return 0


def _double_down_candidate(
    *,
    symbol: str,
    position_qty: Decimal,
    lots: list[dict[str, Any]],
    quote: dict[str, Any],
    active_buys: list[dict[str, Any]],
) -> AfterHoursDoubleDownCandidate | None:
    ask = _decimal(quote.get("ask") or quote.get("ask_price"))
    bid = _decimal(quote.get("bid") or quote.get("bid_price"))
    last_non_reg = _decimal(quote.get("last_non_reg") or quote.get("last_non_reg_trade_price"))
    last_trade = _decimal(quote.get("last_trade") or quote.get("last_trade_price") or quote.get("last"))
    buy_price = ask if ask > ZERO else (last_non_reg or last_trade)
    buy_price_basis = "ask" if ask > ZERO else "after_hours_last_fallback"
    if buy_price <= ZERO:
        return None

    base_price = lots[0]["price"]
    base_shares = lots[0]["qty"]
    if base_price <= ZERO or base_shares <= ZERO:
        return None

    completed_lot, partial_next = _current_ladder_progress(
        position_qty=position_qty,
        base_price=base_price,
        base_shares=base_shares,
    )
    due_lots = _due_lots(
        start_lot=completed_lot + 1,
        partial_next=partial_next,
        base_price=base_price,
        base_shares=base_shares,
        buy_price=buy_price,
    )
    if not due_lots:
        return None

    due_qty = sum((lot["remaining"] for lot in due_lots), ZERO)
    integer_qty = due_qty.to_integral_value(rounding=ROUND_FLOOR)
    decimal_left = due_qty - integer_qty
    deepest_trigger = due_lots[-1]["trigger"]
    suggested_limit = _limit_round(min(buy_price, deepest_trigger))

    return AfterHoursDoubleDownCandidate(
        symbol=symbol,
        ask=ask,
        bid=bid,
        last_non_reg=last_non_reg,
        last_trade=last_trade,
        buy_price=buy_price,
        buy_price_basis=buy_price_basis,
        base_price=base_price,
        base_shares=base_shares,
        position_qty=position_qty,
        completed_lot=completed_lot,
        partial_next=partial_next,
        due_lots=",".join(str(lot["lot_index"]) for lot in due_lots),
        due_qty=due_qty,
        integer_qty=integer_qty,
        decimal_left=decimal_left,
        deepest_trigger=deepest_trigger,
        suggested_limit=suggested_limit,
        active_buy_count=len(active_buys),
        active_buy_details=_active_details(active_buys),
        est_cost=integer_qty * suggested_limit,
    )


def _sell_candidate(
    *,
    symbol: str,
    position: dict[str, Any],
    quote: dict[str, Any],
    active_sells: list[dict[str, Any]],
    sell_return_threshold: Decimal,
) -> AfterHoursSellCandidate | None:
    sellable_qty = _decimal(position.get("shares_available_for_sells") or position.get("quantity"))
    whole_qty = sellable_qty.to_integral_value(rounding=ROUND_FLOOR)
    if whole_qty < Decimal("1"):
        return None

    average_buy = _decimal(position.get("average_buy_price"))
    if average_buy <= ZERO:
        return None

    bid = _decimal(quote.get("bid") or quote.get("bid_price"))
    ask = _decimal(quote.get("ask") or quote.get("ask_price"))
    last_non_reg = _decimal(quote.get("last_non_reg") or quote.get("last_non_reg_trade_price"))
    last_trade = _decimal(quote.get("last_trade") or quote.get("last_trade_price") or quote.get("last"))
    sell_price = bid if bid > ZERO else (last_non_reg or last_trade)
    sell_price_basis = "bid" if bid > ZERO else "after_hours_last_fallback"
    if sell_price <= ZERO:
        return None

    return_pct = ((sell_price - average_buy) / average_buy) * Decimal("100")
    if return_pct < sell_return_threshold:
        return None

    return AfterHoursSellCandidate(
        symbol=symbol,
        whole_qty=whole_qty,
        decimal_left=sellable_qty - whole_qty,
        sellable_qty=sellable_qty,
        average_buy_price=average_buy,
        bid=bid,
        ask=ask,
        last_non_reg=last_non_reg,
        last_trade=last_trade,
        sell_price=sell_price,
        sell_price_basis=sell_price_basis,
        return_pct=return_pct,
        suggested_limit=_limit_round(sell_price),
        active_sell_count=len(active_sells),
        active_sell_details=_active_details(active_sells),
        est_proceeds=whole_qty * sell_price,
    )


def _current_ladder_progress(
    *,
    position_qty: Decimal,
    base_price: Decimal,
    base_shares: Decimal,
) -> tuple[int, Decimal]:
    cumulative = ZERO
    completed_lot = 0
    partial_next = ZERO
    trigger = base_price
    shares = base_shares
    for lot_index in range(1, 80):
        if lot_index == 1:
            trigger = base_price
            shares = base_shares
        elif lot_index == 2:
            trigger = next_trigger_price(base_price, 2)
            shares = next_lot_shares(base_shares)
        else:
            trigger = next_trigger_price(trigger, lot_index)
            shares = next_lot_shares(shares)
        if position_qty + Decimal("0.000001") >= cumulative + shares:
            cumulative += shares
            completed_lot = lot_index
            partial_next = ZERO
        else:
            partial_next = max(position_qty - cumulative, ZERO)
            break
    return completed_lot, partial_next


def _due_lots(
    *,
    start_lot: int,
    partial_next: Decimal,
    base_price: Decimal,
    base_shares: Decimal,
    buy_price: Decimal,
) -> list[dict[str, Decimal | int]]:
    due: list[dict[str, Decimal | int]] = []
    trigger = base_price
    shares = base_shares
    for lot_index in range(2, 80):
        if lot_index == 2:
            trigger = next_trigger_price(base_price, 2)
            shares = next_lot_shares(base_shares)
        else:
            trigger = next_trigger_price(trigger, lot_index)
            shares = next_lot_shares(shares)
        if lot_index < start_lot:
            continue
        if buy_price > trigger:
            break
        remaining = shares
        if lot_index == start_lot and partial_next > ZERO:
            remaining = max(shares - partial_next, ZERO)
        if remaining > ZERO:
            due.append({"lot_index": lot_index, "trigger": trigger, "shares": shares, "remaining": remaining})
    return due


def _reconstruct_open_lots(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lots: deque[dict[str, Any]] = deque()
    for order in sorted(orders, key=_event_time):
        side = str(order.get("side") or "").lower()
        quantity = _decimal(order.get("cumulative_quantity") or order.get("quantity"))
        if side == "buy":
            average_price = _decimal(order.get("average_price") or order.get("price"))
            executions = order.get("executions") or []
            if executions:
                for execution in executions:
                    execution_qty = _decimal(execution.get("quantity"))
                    if execution_qty > ZERO:
                        lots.append(
                            {
                                "qty": execution_qty,
                                "price": _decimal(execution.get("price") or average_price),
                                "order_id": order.get("id"),
                                "time": execution.get("timestamp") or _event_time(order),
                            }
                        )
            elif quantity > ZERO:
                lots.append(
                    {
                        "qty": quantity,
                        "price": average_price,
                        "order_id": order.get("id"),
                        "time": _event_time(order),
                    }
                )
        elif side == "sell":
            left = quantity
            while left > ZERO and lots:
                if lots[0]["qty"] <= left + Decimal("0.0000005"):
                    left -= lots[0]["qty"]
                    lots.popleft()
                else:
                    lots[0]["qty"] -= left
                    left = ZERO
    return list(lots)


def _filled_orders_by_symbol(
    orders: list[dict[str, Any]],
    owned_symbols: set[str],
) -> dict[str, list[dict[str, Any]]]:
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for order in orders:
        symbol = _symbol(order)
        if (
            symbol in owned_symbols
            and str(order.get("state") or "").lower() == "filled"
            and str(order.get("side") or "").lower() in {"buy", "sell"}
        ):
            by_symbol[symbol].append(order)
    return by_symbol


def _active_orders_by_side(
    orders: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    buys: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sells: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for order in orders:
        state = str(order.get("state") or "").lower()
        if state not in ACTIVE_ORDER_STATES:
            continue
        symbol = _symbol(order)
        if not symbol:
            continue
        side = str(order.get("side") or "").lower()
        if side == "buy":
            buys[symbol].append(order)
        elif side == "sell":
            sells[symbol].append(order)
    return buys, sells


def _positions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("positions"), list):
        return [item for item in payload["positions"] if isinstance(item, dict)]
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    positions = data.get("positions") if isinstance(data, dict) else None
    return [item for item in positions if isinstance(item, dict)] if isinstance(positions, list) else []


def _quotes_by_symbol(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    quotes: dict[str, dict[str, Any]] = {}
    if isinstance(payload.get("quotes"), list):
        for quote in payload["quotes"]:
            symbol = _symbol(quote)
            if symbol:
                quotes[symbol] = quote
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    results = data.get("results") if isinstance(data, dict) else None
    if isinstance(results, list):
        for row in results:
            quote = row.get("quote", row) if isinstance(row, dict) else {}
            symbol = _symbol(quote)
            if symbol:
                quotes[symbol] = quote
    return quotes


def _orders(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("orders"), list):
        return [item for item in payload["orders"] if isinstance(item, dict)]
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    orders = data.get("orders") if isinstance(data, dict) else None
    return [item for item in orders if isinstance(item, dict)] if isinstance(orders, list) else []


def _symbol(row: dict[str, Any]) -> str:
    return str(row.get("symbol") or "").strip().upper()


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return ZERO
    return Decimal(str(value))


def _event_time(order: dict[str, Any]) -> str:
    return str(order.get("last_transaction_at") or order.get("created_at") or "")


def _limit_round(price: Decimal) -> Decimal:
    if price < Decimal("1"):
        return price.quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    return price.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _active_details(orders: list[dict[str, Any]]) -> str:
    return ";".join(
        f"{order.get('quantity')}@{order.get('price')} {order.get('state')}" for order in orders
    )


def _json_row(item: Any) -> dict[str, Any]:
    row = asdict(item)
    return {key: str(value) if isinstance(value, Decimal) else value for key, value in row.items()}


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
