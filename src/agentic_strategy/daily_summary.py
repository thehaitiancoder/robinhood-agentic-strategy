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
HISTORY_FIELDS = [
    "report_date",
    "generated_at",
    "account_value",
    "equity_value",
    "cash",
    "buying_power",
    "long_market_value",
    "gross_paper_gain",
    "gross_paper_loss",
    "net_paper_pl",
    "positions_up",
    "positions_down",
    "positions_flat",
    "realized_profit",
    "sell_proceeds",
    "sold_cost_basis",
    "realized_return_pct",
    "sell_count",
    "costed_sell_count",
    "winning_sells",
    "losing_sells",
    "uncosted_quantity",
    "average_hold_minutes",
    "median_hold_minutes",
    "profit_by_hour",
]


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
    history_csv: str | Path | None = None,
    history_markdown: str | Path | None = None,
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
    if history_markdown and not history_csv:
        raise ValueError("history_csv is required when history_markdown is provided")
    if history_csv:
        write_performance_history(summary=summary, history_csv=history_csv, history_markdown=history_markdown)


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


def write_performance_history(
    *,
    summary: dict[str, Any],
    history_csv: str | Path,
    history_markdown: str | Path | None = None,
) -> None:
    csv_path = Path(history_csv)
    rows = _read_history_rows(csv_path)
    rows_by_date = {row["report_date"]: row for row in rows if row.get("report_date")}
    current_row = _history_row(summary)
    rows_by_date[current_row["report_date"]] = current_row
    sorted_rows = [rows_by_date[key] for key in sorted(rows_by_date)]
    _write_history_csv(csv_path, sorted_rows)

    if history_markdown:
        markdown_path = Path(history_markdown)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_performance_history(sorted_rows), encoding="utf-8")


def render_performance_history(rows: list[dict[str, str]]) -> str:
    lines = [
        "# Robinhood Strategy Performance History",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
    ]

    if not rows:
        lines.extend(["No daily summaries have been recorded yet.", ""])
        return "\n".join(lines)

    first = rows[0]
    latest = rows[-1]
    cumulative_realized = sum((_decimal(row.get("realized_profit")) for row in rows), ZERO)
    account_change = _decimal(latest.get("account_value")) - _decimal(first.get("account_value"))

    lines.extend(
        [
            "## Latest Snapshot",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Dates tracked | {len(rows)} |",
            f"| Latest date | {latest.get('report_date', '')} |",
            f"| Account value | {_money(latest.get('account_value'))} |",
            f"| Cash | {_money(latest.get('cash'))} |",
            f"| Buying power | {_money(latest.get('buying_power'))} |",
            f"| Net paper P/L | {_money(latest.get('net_paper_pl'))} |",
            f"| Realized profit latest day | {_money(latest.get('realized_profit'))} |",
            f"| Cumulative realized profit tracked | {_money(cumulative_realized)} |",
            f"| Account value change since first tracked day | {_money(account_change)} |",
            f"| Latest profit by hour | {_format_history_profit_by_hour(latest.get('profit_by_hour', ''))} |",
            "",
            "## Daily Rows",
            "",
            "| Date | Account Value | Cash | Buying Power | Realized Profit | Net Paper P/L | Sells | Win/Loss | Avg Hold | Median Hold | Uncosted Qty |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )

    for row in rows:
        average_hold = _duration(_optional_decimal(row.get("average_hold_minutes")))
        median_hold = _duration(_optional_decimal(row.get("median_hold_minutes")))
        win_loss = _history_win_loss(row)
        lines.append(
            f"| {row.get('report_date', '')} | {_money(row.get('account_value'))} | "
            f"{_money(row.get('cash'))} | {_money(row.get('buying_power'))} | "
            f"{_money(row.get('realized_profit'))} | {_money(row.get('net_paper_pl'))} | "
            f"{row.get('sell_count', '')} | {win_loss} | "
            f"{average_hold} | {median_hold} | {_num(row.get('uncosted_quantity'))} |"
        )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This file is regenerated from `performance-history.csv`.",
            "- One row is kept per Pacific trading date; reruns replace that date instead of appending duplicates.",
            "- Values come from the 5 PM read-only daily summary job and Robinhood broker artifacts fetched during that run.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a daily Robinhood strategy performance summary.")
    parser.add_argument("--portfolio-json")
    parser.add_argument("--positions-json")
    parser.add_argument("--orders-json")
    parser.add_argument("--output-md")
    parser.add_argument("--cycles-csv")
    parser.add_argument("--output-json")
    parser.add_argument("--history-csv")
    parser.add_argument("--history-md")
    parser.add_argument("--summary-json-input", help="Existing daily-summary.json to seed/update history only.")
    parser.add_argument("--date", help="Pacific date YYYY-MM-DD. Defaults to today's PT date.")
    args = parser.parse_args()

    if args.summary_json_input:
        if not args.history_csv:
            parser.error("--history-csv is required with --summary-json-input")
        summary = _read_json(args.summary_json_input)
        write_performance_history(
            summary=summary,
            history_csv=args.history_csv,
            history_markdown=args.history_md,
        )
        print(
            json.dumps(
                {
                    "summary_json_input": args.summary_json_input,
                    "history_csv": args.history_csv,
                    "history_md": args.history_md,
                    "report_date": summary["report_date"],
                }
            )
        )
        return 0

    for flag, value in (
        ("--portfolio-json", args.portfolio_json),
        ("--positions-json", args.positions_json),
        ("--orders-json", args.orders_json),
        ("--output-md", args.output_md),
    ):
        if not value:
            parser.error(f"{flag} is required unless --summary-json-input is used")

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
        history_csv=args.history_csv,
        history_markdown=args.history_md,
    )
    print(
        json.dumps(
            {
                "output_md": args.output_md,
                "cycles_csv": args.cycles_csv,
                "output_json": args.output_json,
                "history_csv": args.history_csv,
                "history_md": args.history_md,
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
    portfolio_payload = payload.get("portfolio")
    data_payload = payload.get("data")
    if isinstance(portfolio_payload, dict):
        data = portfolio_payload
    elif isinstance(data_payload, dict):
        data = data_payload
    else:
        data = payload
    buying_power_payload = data.get("buying_power")
    buying_power = buying_power_payload if isinstance(buying_power_payload, dict) else {}
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


def _history_row(summary: dict[str, Any]) -> dict[str, str]:
    portfolio = summary["portfolio"]
    paper = summary["paper"]
    totals = summary["totals"]
    realized_return_pct = totals.get("realized_return_pct")
    average_hold_minutes = totals.get("average_hold_minutes")
    median_hold_minutes = totals.get("median_hold_minutes")
    return {
        "report_date": str(summary["report_date"]),
        "generated_at": str(summary["generated_at"]),
        "account_value": str(portfolio.get("total_value", ZERO)),
        "equity_value": str(portfolio.get("equity_value", ZERO)),
        "cash": str(portfolio.get("cash", ZERO)),
        "buying_power": str(portfolio.get("buying_power", ZERO)),
        "long_market_value": str(_paper_value(paper, "long_market_value")),
        "gross_paper_gain": str(_paper_value(paper, "gross_paper_gain")),
        "gross_paper_loss": str(_paper_value(paper, "gross_paper_loss")),
        "net_paper_pl": str(_paper_value(paper, "net_paper_gain")),
        "positions_up": str(_paper_value(paper, "positions_up")),
        "positions_down": str(_paper_value(paper, "positions_down")),
        "positions_flat": str(_paper_value(paper, "positions_flat")),
        "realized_profit": str(totals.get("realized_profit", ZERO)),
        "sell_proceeds": str(totals.get("sell_proceeds", ZERO)),
        "sold_cost_basis": str(totals.get("sold_cost_basis", ZERO)),
        "realized_return_pct": str(realized_return_pct) if realized_return_pct not in (None, "") else "",
        "sell_count": str(totals.get("sell_count", 0)),
        "costed_sell_count": str(totals.get("costed_sell_count", 0)),
        "winning_sells": str(totals.get("winning_sells", 0)),
        "losing_sells": str(totals.get("losing_sells", 0)),
        "uncosted_quantity": str(totals.get("uncosted_quantity", ZERO)),
        "average_hold_minutes": str(average_hold_minutes) if average_hold_minutes not in (None, "") else "",
        "median_hold_minutes": str(median_hold_minutes) if median_hold_minutes not in (None, "") else "",
        "profit_by_hour": _history_profit_by_hour(summary["hourly"]),
    }


def _paper_value(paper: PaperSummary | dict[str, Any], key: str) -> Any:
    if isinstance(paper, PaperSummary):
        return getattr(paper, key)
    return paper.get(key, ZERO)


def _history_profit_by_hour(hourly: dict[str, dict[str, Decimal | int]]) -> str:
    return ";".join(f"{hour}={row['profit']}" for hour, row in sorted(hourly.items()))


def _read_history_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [
            {field: str(row.get(field, "")) for field in HISTORY_FIELDS}
            for row in reader
            if row.get("report_date")
        ]


def _write_history_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in HISTORY_FIELDS})


def _format_history_profit_by_hour(value: str) -> str:
    parts = []
    for item in value.split(";"):
        if not item or "=" not in item:
            continue
        hour, profit = item.split("=", 1)
        parts.append(f"{hour} {_money(profit)}")
    return ", ".join(parts)


def _history_win_loss(row: dict[str, str]) -> str:
    wins = row.get("winning_sells", "")
    losses = row.get("losing_sells", "")
    if not wins and not losses:
        return "n/a"
    return f"{wins}/{losses}"


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


def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return _decimal(value)


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
    if minutes >= Decimal("1440"):
        total_minutes = int(minutes.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        days, remaining_minutes = divmod(total_minutes, 1440)
        hours, minute_remainder = divmod(remaining_minutes, 60)
        return f"{days}d {hours}h {minute_remainder}m"
    hours = minutes / Decimal("60")
    return f"{hours.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)} hr"


def _dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return _as_pt(value).strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    raise SystemExit(main())
