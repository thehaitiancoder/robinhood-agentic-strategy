from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import median
from typing import Any


UTC = timezone.utc
ZERO = Decimal("0")


@dataclass
class Lot:
    quantity: Decimal
    price: Decimal
    timestamp: datetime
    order_id: str


@dataclass
class SellCycle:
    order_id: str
    symbol: str
    sold_at: datetime
    quantity: Decimal
    proceeds: Decimal
    cost_basis: Decimal
    realized_gain: Decimal
    first_buy_at: datetime | None
    weighted_hold_minutes: Decimal | None
    uncosted_quantity: Decimal

    @property
    def return_pct(self) -> Decimal | None:
        if self.cost_basis <= ZERO:
            return None
        return (self.realized_gain / self.cost_basis) * Decimal("100")


@dataclass(frozen=True)
class PaperSummary:
    gross_paper_gain: Decimal
    gross_paper_loss: Decimal
    net_paper_gain: Decimal
    long_market_value: Decimal
    positions_up: int
    positions_down: int
    positions_flat: int


def build_daily_summary(
    *,
    portfolio_payload: dict[str, Any],
    positions_payload: dict[str, Any],
    orders_payload: dict[str, Any],
    report_date: str | None = None,
) -> dict[str, Any]:
    report_day = _report_day(report_date)
    paper = _paper_summary(positions_payload)
    cycles = _sell_cycles(orders_payload, report_day=report_day)
    hourly = _hourly_profit(cycles)

    costed_cycles = [cycle for cycle in cycles if cycle.cost_basis > ZERO]
    total_realized = sum((cycle.realized_gain for cycle in costed_cycles), ZERO)
    total_proceeds = sum((cycle.proceeds for cycle in cycles), ZERO)
    total_cost = sum((cycle.cost_basis for cycle in costed_cycles), ZERO)
    uncosted_qty = sum((cycle.uncosted_quantity for cycle in cycles), ZERO)
    hold_minutes = [
        cycle.weighted_hold_minutes for cycle in costed_cycles if cycle.weighted_hold_minutes is not None
    ]

    portfolio = _portfolio(portfolio_payload)
    return {
        "report_date": report_day,
        "generated_at": datetime.now(UTC).isoformat(),
        "portfolio": portfolio,
        "paper": paper,
        "cycles": cycles,
        "hourly": hourly,
        "totals": {
            "realized_profit": total_realized,
            "sell_proceeds": total_proceeds,
            "sold_cost_basis": total_cost,
            "realized_return_pct": (total_realized / total_cost * Decimal("100")) if total_cost > ZERO else None,
            "sell_count": len(cycles),
            "costed_sell_count": len(costed_cycles),
            "uncosted_quantity": uncosted_qty,
            "winning_sells": sum(1 for cycle in costed_cycles if cycle.realized_gain > ZERO),
            "losing_sells": sum(1 for cycle in costed_cycles if cycle.realized_gain < ZERO),
            "average_hold_minutes": (sum(hold_minutes, ZERO) / Decimal(len(hold_minutes))) if hold_minutes else None,
            "median_hold_minutes": Decimal(str(median(hold_minutes))) if hold_minutes else None,
        },
    }


def write_daily_summary(
    *,
    summary: dict[str, Any],
    markdown_output: str | Path,
    cycles_csv: str | Path | None = None,
    json_output: str | Path | None = None,
) -> None:
    markdown_path = Path(markdown_output)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(summary), encoding="utf-8")

    if cycles_csv:
        _write_cycles_csv(Path(cycles_csv), summary["cycles"])
    if json_output:
        payload = _summary_json(summary)
        output = Path(json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def render_markdown(summary: dict[str, Any]) -> str:
    portfolio = summary["portfolio"]
    paper: PaperSummary = summary["paper"]
    totals = summary["totals"]
    cycles: list[SellCycle] = summary["cycles"]
    hourly = summary["hourly"]

    lines = [
        f"# Robinhood Strategy Daily Summary - {summary['report_date']} PT",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "## Account Snapshot",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Account value | {_money(portfolio.get('total_value'))} |",
        f"| Equity value | {_money(portfolio.get('equity_value'))} |",
        f"| Cash | {_money(portfolio.get('cash'))} |",
        f"| Buying power | {_money(portfolio.get('buying_power'))} |",
        "",
        "## Paper P/L",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Gross paper gain | {_money(paper.gross_paper_gain)} |",
        f"| Gross paper loss | {_money(paper.gross_paper_loss)} |",
        f"| Net paper P/L | {_money(paper.net_paper_gain)} |",
        f"| Long market value | {_money(paper.long_market_value)} |",
        f"| Positions up / down / flat | {paper.positions_up} / {paper.positions_down} / {paper.positions_flat} |",
        "",
        "## Realized Today",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Realized profit | {_money(totals['realized_profit'])} |",
        f"| Sell proceeds | {_money(totals['sell_proceeds'])} |",
        f"| Sold cost basis | {_money(totals['sold_cost_basis'])} |",
        f"| Realized return | {_pct(totals['realized_return_pct'])} |",
        f"| Sell cycles | {totals['sell_count']} |",
        f"| Winning / losing sells | {totals['winning_sells']} / {totals['losing_sells']} |",
        f"| Avg hold time | {_duration(totals['average_hold_minutes'])} |",
        f"| Median hold time | {_duration(totals['median_hold_minutes'])} |",
        f"| Uncosted sold quantity | {_num(totals['uncosted_quantity'])} |",
        "",
        "## Profit By Hour",
        "",
        "| PT Hour | Sells | Proceeds | Cost | Profit | Return |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]

    if not hourly:
        lines.append("| None | 0 | $0.00 | $0.00 | $0.00 |  |")
    else:
        for hour, row in sorted(hourly.items()):
            return_pct = (row["profit"] / row["cost"] * Decimal("100")) if row["cost"] > ZERO else None
            lines.append(
                f"| {hour}:00 | {row['count']} | {_money(row['proceeds'])} | "
                f"{_money(row['cost'])} | {_money(row['profit'])} | {_pct(return_pct)} |"
            )

    lines.extend(
        [
            "",
            "## Sell Cycles",
            "",
            "| Sold At PT | Symbol | Qty | Proceeds | Cost | Profit | Return | First Buy PT | Hold Time |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
        ]
    )
    if not cycles:
        lines.append("| None |  |  |  |  |  |  |  |  |")
    else:
        for cycle in sorted(cycles, key=lambda item: item.sold_at):
            lines.append(
                f"| {_dt(cycle.sold_at)} | {cycle.symbol} | {_num(cycle.quantity)} | "
                f"{_money(cycle.proceeds)} | {_money(cycle.cost_basis)} | {_money(cycle.realized_gain)} | "
                f"{_pct(cycle.return_pct)} | {_dt(cycle.first_buy_at)} | {_duration(cycle.weighted_hold_minutes)} |"
            )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Paper P/L uses the latest broker quote in this order: after-hours last, regular last, bid, ask, close.",
            "- Realized profit uses FIFO cost reconstruction from filled equity orders.",
            "- If uncosted sold quantity is nonzero, the broker order history provided to the run was insufficient for those shares.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a daily Robinhood strategy performance summary.")
    parser.add_argument("--portfolio-json", required=True)
    parser.add_argument("--positions-json", required=True)
    parser.add_argument("--orders-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--cycles-csv")
    parser.add_argument("--output-json")
    parser.add_argument("--date", help="Pacific date YYYY-MM-DD. Defaults to today's PT date.")
    args = parser.parse_args()

    summary = build_daily_summary(
        portfolio_payload=_read_json(args.portfolio_json),
        positions_payload=_read_json(args.positions_json),
        orders_payload=_read_json(args.orders_json),
        report_date=args.date,
    )
    write_daily_summary(
        summary=summary,
        markdown_output=args.output_md,
        cycles_csv=args.cycles_csv,
        json_output=args.output_json,
    )
    print(
        json.dumps(
            {
                "output_md": args.output_md,
                "cycles_csv": args.cycles_csv,
                "output_json": args.output_json,
                "report_date": summary["report_date"],
                "sell_count": summary["totals"]["sell_count"],
                "realized_profit": str(summary["totals"]["realized_profit"]),
                "net_paper_pl": str(summary["paper"].net_paper_gain),
            }
        )
    )
    return 0


def _sell_cycles(orders_payload: dict[str, Any], *, report_day: str) -> list[SellCycle]:
    lots_by_symbol: dict[str, deque[Lot]] = defaultdict(deque)
    cycles_by_order: dict[str, SellCycle] = {}

    for event in sorted(_execution_events(orders_payload), key=lambda item: (item["timestamp"], item["side"] == "sell")):
        symbol = event["symbol"]
        quantity = event["quantity"]
        price = event["price"]
        timestamp = event["timestamp"]
        if event["side"] == "buy":
            lots_by_symbol[symbol].append(
                Lot(quantity=quantity, price=price, timestamp=timestamp, order_id=event["order_id"])
            )
            continue

        proceeds = quantity * price
        left = quantity
        cost = ZERO
        hold_weighted = ZERO
        costed_quantity = ZERO
        first_buy_at: datetime | None = None
        lots = lots_by_symbol[symbol]
        while left > ZERO and lots:
            lot = lots[0]
            consumed = min(left, lot.quantity)
            cost += consumed * lot.price
            hold_minutes = Decimal(str((timestamp - lot.timestamp).total_seconds() / 60))
            hold_weighted += consumed * hold_minutes
            costed_quantity += consumed
            first_buy_at = lot.timestamp if first_buy_at is None else min(first_buy_at, lot.timestamp)
            lot.quantity -= consumed
            left -= consumed
            if lot.quantity <= Decimal("0.0000005"):
                lots.popleft()

        if _pt_date(timestamp) != report_day:
            continue

        order_id = event["order_id"]
        existing = cycles_by_order.get(order_id)
        weighted_hold_minutes = (hold_weighted / costed_quantity) if costed_quantity > ZERO else None
        if existing is None:
            cycles_by_order[order_id] = SellCycle(
                order_id=order_id,
                symbol=symbol,
                sold_at=timestamp,
                quantity=quantity,
                proceeds=proceeds,
                cost_basis=cost,
                realized_gain=proceeds - cost if cost > ZERO else ZERO,
                first_buy_at=first_buy_at,
                weighted_hold_minutes=weighted_hold_minutes,
                uncosted_quantity=left,
            )
        else:
            combined_qty = existing.quantity + quantity
            combined_hold = _combine_weighted_hold(
                existing.weighted_hold_minutes,
                existing.quantity - existing.uncosted_quantity,
                weighted_hold_minutes,
                costed_quantity,
            )
            existing.quantity = combined_qty
            existing.proceeds += proceeds
            existing.cost_basis += cost
            existing.realized_gain = existing.proceeds - existing.cost_basis if existing.cost_basis > ZERO else ZERO
            existing.uncosted_quantity += left
            existing.first_buy_at = _min_dt(existing.first_buy_at, first_buy_at)
            existing.weighted_hold_minutes = combined_hold
            existing.sold_at = min(existing.sold_at, timestamp)

    return list(cycles_by_order.values())


def _execution_events(orders_payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for order in _orders(orders_payload):
        if str(order.get("state") or "").lower() != "filled":
            continue
        side = str(order.get("side") or "").lower()
        if side not in {"buy", "sell"}:
            continue
        symbol = str(order.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        executions = order.get("executions") or []
        if executions:
            for execution in executions:
                quantity = _decimal(execution.get("quantity"))
                price = _decimal(execution.get("price") or order.get("average_price") or order.get("price"))
                timestamp = _parse_dt(execution.get("timestamp") or order.get("last_transaction_at"))
                if quantity > ZERO and price > ZERO and timestamp:
                    events.append(
                        {
                            "order_id": str(order.get("id") or ""),
                            "symbol": symbol,
                            "side": side,
                            "quantity": quantity,
                            "price": price,
                            "timestamp": timestamp,
                        }
                    )
            continue
        quantity = _decimal(order.get("cumulative_quantity") or order.get("quantity"))
        price = _decimal(order.get("average_price") or order.get("price"))
        timestamp = _parse_dt(order.get("last_transaction_at") or order.get("created_at"))
        if quantity > ZERO and price > ZERO and timestamp:
            events.append(
                {
                    "order_id": str(order.get("id") or ""),
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "price": price,
                    "timestamp": timestamp,
                }
            )
    return events


def _paper_summary(positions_payload: dict[str, Any]) -> PaperSummary:
    quotes = _quotes_by_symbol(positions_payload)
    gross_gain = ZERO
    gross_loss = ZERO
    market_value = ZERO
    up = down = flat = 0
    for position in _positions(positions_payload):
        quantity = _decimal(position.get("quantity"))
        average_buy = _decimal(position.get("average_buy_price"))
        if quantity <= ZERO or average_buy <= ZERO:
            continue
        quote = quotes.get(_symbol(position), {})
        mark = _mark_price(quote)
        if mark <= ZERO:
            continue
        value = quantity * mark
        cost = quantity * average_buy
        pnl = value - cost
        market_value += value
        if pnl > ZERO:
            gross_gain += pnl
            up += 1
        elif pnl < ZERO:
            gross_loss += pnl
            down += 1
        else:
            flat += 1
    return PaperSummary(
        gross_paper_gain=gross_gain,
        gross_paper_loss=gross_loss,
        net_paper_gain=gross_gain + gross_loss,
        long_market_value=market_value,
        positions_up=up,
        positions_down=down,
        positions_flat=flat,
    )


def _hourly_profit(cycles: list[SellCycle]) -> dict[str, dict[str, Decimal | int]]:
    hourly: dict[str, dict[str, Decimal | int]] = {}
    for cycle in cycles:
        hour = f"{_as_pt(cycle.sold_at).hour:02d}"
        row = hourly.setdefault(hour, {"count": 0, "proceeds": ZERO, "cost": ZERO, "profit": ZERO})
        row["count"] = int(row["count"]) + 1
        row["proceeds"] = row["proceeds"] + cycle.proceeds
        row["cost"] = row["cost"] + cycle.cost_basis
        row["profit"] = row["profit"] + cycle.realized_gain
    return hourly


def _portfolio(payload: dict[str, Any]) -> dict[str, Decimal]:
    data = payload.get("portfolio") if isinstance(payload.get("portfolio"), dict) else payload.get("data", payload)
    buying_power = data.get("buying_power") if isinstance(data.get("buying_power"), dict) else {}
    return {
        "total_value": _decimal(data.get("total_value")),
        "equity_value": _decimal(data.get("equity_value")),
        "cash": _decimal(data.get("cash")),
        "buying_power": _decimal(buying_power.get("buying_power") or data.get("buying_power")),
    }


def _positions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("positions"), list):
        return [item for item in payload["positions"] if isinstance(item, dict)]
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    positions = data.get("positions") if isinstance(data, dict) else None
    return [item for item in positions if isinstance(item, dict)] if isinstance(positions, list) else []


def _orders(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("orders"), list):
        return [item for item in payload["orders"] if isinstance(item, dict)]
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    orders = data.get("orders") if isinstance(data, dict) else None
    return [item for item in orders if isinstance(item, dict)] if isinstance(orders, list) else []


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


def _mark_price(quote: dict[str, Any]) -> Decimal:
    for key in ("last_non_reg", "last_non_reg_trade_price", "last_trade", "last_trade_price", "last", "bid", "ask", "close"):
        price = _decimal(quote.get(key))
        if price > ZERO:
            return price
    return ZERO


def _summary_json(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_date": summary["report_date"],
        "generated_at": summary["generated_at"],
        "portfolio": {key: str(value) for key, value in summary["portfolio"].items()},
        "paper": {key: str(value) for key, value in summary["paper"].__dict__.items()},
        "totals": {
            key: str(value) if isinstance(value, Decimal) else value for key, value in summary["totals"].items()
        },
        "hourly": {
            hour: {key: str(value) if isinstance(value, Decimal) else value for key, value in row.items()}
            for hour, row in summary["hourly"].items()
        },
        "cycles": [_cycle_json(cycle) for cycle in summary["cycles"]],
    }


def _cycle_json(cycle: SellCycle) -> dict[str, str]:
    return {
        "order_id": cycle.order_id,
        "symbol": cycle.symbol,
        "sold_at": cycle.sold_at.isoformat(),
        "quantity": str(cycle.quantity),
        "proceeds": str(cycle.proceeds),
        "cost_basis": str(cycle.cost_basis),
        "realized_gain": str(cycle.realized_gain),
        "return_pct": str(cycle.return_pct) if cycle.return_pct is not None else "",
        "first_buy_at": cycle.first_buy_at.isoformat() if cycle.first_buy_at else "",
        "weighted_hold_minutes": str(cycle.weighted_hold_minutes or ""),
        "uncosted_quantity": str(cycle.uncosted_quantity),
    }


def _write_cycles_csv(path: Path, cycles: list[SellCycle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sold_at_pt",
                "symbol",
                "quantity",
                "proceeds",
                "cost_basis",
                "realized_gain",
                "return_pct",
                "first_buy_at_pt",
                "weighted_hold_minutes",
                "uncosted_quantity",
                "order_id",
            ],
        )
        writer.writeheader()
        for cycle in sorted(cycles, key=lambda item: item.sold_at):
            writer.writerow(
                {
                    "sold_at_pt": _dt(cycle.sold_at),
                    "symbol": cycle.symbol,
                    "quantity": str(cycle.quantity),
                    "proceeds": str(cycle.proceeds),
                    "cost_basis": str(cycle.cost_basis),
                    "realized_gain": str(cycle.realized_gain),
                    "return_pct": str(cycle.return_pct or ""),
                    "first_buy_at_pt": _dt(cycle.first_buy_at),
                    "weighted_hold_minutes": str(cycle.weighted_hold_minutes or ""),
                    "uncosted_quantity": str(cycle.uncosted_quantity),
                    "order_id": cycle.order_id,
                }
            )


def _combine_weighted_hold(
    left_hold: Decimal | None,
    left_quantity: Decimal,
    right_hold: Decimal | None,
    right_quantity: Decimal,
) -> Decimal | None:
    total_quantity = left_quantity + right_quantity
    if total_quantity <= ZERO:
        return None
    left = (left_hold or ZERO) * left_quantity
    right = (right_hold or ZERO) * right_quantity
    return (left + right) / total_quantity


def _report_day(value: str | None) -> str:
    if value:
        return value
    return _as_pt(datetime.now(UTC)).date().isoformat()


def _pt_date(value: datetime) -> str:
    return _as_pt(value).date().isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _as_pt(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    utc_value = value.astimezone(UTC)
    return (utc_value + _pacific_utc_offset(utc_value)).replace(tzinfo=None)


def _pacific_utc_offset(utc_value: datetime) -> timedelta:
    if _pacific_is_dst(utc_value):
        return timedelta(hours=-7)
    return timedelta(hours=-8)


def _pacific_is_dst(utc_value: datetime) -> bool:
    year = utc_value.year
    normalized = utc_value.replace(tzinfo=UTC)
    return _dst_start_utc(year) <= normalized < _dst_end_utc(year)


def _dst_start_utc(year: int) -> datetime:
    return datetime(year, 3, _nth_weekday_of_month(year, 3, 6, 2), 10, tzinfo=UTC)


def _dst_end_utc(year: int) -> datetime:
    return datetime(year, 11, _nth_weekday_of_month(year, 11, 6, 1), 9, tzinfo=UTC)


def _nth_weekday_of_month(year: int, month: int, weekday: int, occurrence: int) -> int:
    first = datetime(year, month, 1)
    days_until_weekday = (weekday - first.weekday()) % 7
    return 1 + days_until_weekday + ((occurrence - 1) * 7)


def _min_dt(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return ZERO
    return Decimal(str(value))


def _symbol(row: dict[str, Any]) -> str:
    return str(row.get("symbol") or "").strip().upper()


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _money(value: Any) -> str:
    if value is None:
        return ""
    amount = _decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if amount < ZERO else ""
    return f"{sign}${abs(amount):,.2f}"


def _pct(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%"


def _num(value: Any) -> str:
    return str(_decimal(value).normalize()) if value not in (None, "") else ""


def _duration(minutes: Decimal | None) -> str:
    if minutes is None:
        return ""
    if minutes < Decimal("60"):
        return f"{minutes.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)} min"
    hours = minutes / Decimal("60")
    return f"{hours.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)} hr"


def _dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return _as_pt(value).strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    raise SystemExit(main())
