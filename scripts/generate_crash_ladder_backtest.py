from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, getcontext
from pathlib import Path
from typing import Iterable


getcontext().prec = 28

DEFAULT_START = date(2025, 6, 21)
DEFAULT_END = date(2026, 6, 21)
DEFAULT_BASE_USD = Decimal("1")
DEFAULT_ANNUAL_RETURN = Decimal("0.20")

SEED_SYMBOLS = ["MLTX", "RZLT", "REPL", "KRRO", "CMPX", "ZBIO", "JANX", "LRN", "ARCT", "AGL"]

CSV_FIELDS = [
    "symbol",
    "name",
    "universe_active",
    "universe_tradable",
    "universe_fractional_eligible",
    "source",
    "analysis_status",
    "error",
    "event_date",
    "event_prev_close",
    "event_open",
    "event_high",
    "event_low",
    "event_close",
    "event_close_drop_pct",
    "event_low_drop_pct",
    "trough_date",
    "trough_low",
    "trough_close",
    "trough_days_after_event",
    "base_usd",
    "base_entry_price",
    "base_entry_date",
    "base_lot_shares",
    "lots_bought",
    "deepest_lot_index",
    "deepest_lot_trigger_price",
    "deepest_lot_shares",
    "total_shares",
    "total_invested",
    "avg_cost_break_even_price",
    "ten_pct_gain_price",
    "break_even_date",
    "break_even_high",
    "days_trough_to_break_even",
    "ten_pct_date",
    "ten_pct_high",
    "days_trough_to_ten_pct",
    "latest_price_date",
    "latest_price",
    "hold_value_today",
    "hold_profit_today",
    "hold_return_pct_today",
    "ten_pct_sell_proceeds",
    "reinvest_annual_return_pct",
    "reinvest_days_after_ten_pct",
    "sell_10_reinvest_value_today",
    "sell_10_reinvest_profit_today",
    "sell_10_reinvest_return_pct_today",
    "sell_10_reinvest_delta_vs_hold",
    "data_start",
    "data_end",
    "bars_count",
]


@dataclass(frozen=True)
class Bar:
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class LadderLot:
    index: int
    trigger: Decimal
    shares: Decimal


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a CSV backtest for $1 base buys through crash-ladder DDs."
    )
    parser.add_argument("--universe", default="data/universe.csv")
    parser.add_argument("--output", default="data/runtime/crash-ladder-backtest.csv")
    parser.add_argument("--start-date", default=DEFAULT_START.isoformat())
    parser.add_argument("--end-date", default=DEFAULT_END.isoformat())
    parser.add_argument("--base-usd", default=str(DEFAULT_BASE_USD))
    parser.add_argument("--annual-return", default=str(DEFAULT_ANNUAL_RETURN))
    parser.add_argument("--seed", action="store_true", help="Write the fixed 10 crash-study symbols first.")
    parser.add_argument("--append", action="store_true", help="Append rows to an existing output file.")
    parser.add_argument("--limit", type=int, default=0, help="Number of universe symbols to add after exclusions.")
    parser.add_argument(
        "--symbol",
        action="append",
        default=[],
        help="Explicit symbol to analyze. Can be passed multiple times.",
    )
    parser.add_argument("--pause-seconds", type=float, default=0.25)
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)
    base_usd = Decimal(args.base_usd)
    annual_return = Decimal(args.annual_return)
    universe_rows = read_universe(Path(args.universe))

    output_path = Path(args.output)
    existing_symbols = read_existing_symbols(output_path) if args.append else set()

    symbols: list[str] = []
    if args.seed:
        symbols.extend(SEED_SYMBOLS)
    symbols.extend(normalize_symbol(symbol) for symbol in args.symbol)

    if args.limit:
        for row in universe_rows:
            symbol = normalize_symbol(row.get("symbol", ""))
            if not symbol or symbol in symbols or symbol in existing_symbols:
                continue
            if text_bool(row.get("active")) is False or text_bool(row.get("tradable")) is False:
                continue
            symbols.append(symbol)
            if len([item for item in symbols if item not in SEED_SYMBOLS]) >= args.limit:
                break

    symbols = dedupe(symbols)
    if args.append:
        symbols = [symbol for symbol in symbols if symbol not in existing_symbols]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not args.append or not output_path.exists()
    mode = "a" if args.append else "w"
    with output_path.open(mode, newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        for index, symbol in enumerate(symbols, start=1):
            universe = universe_rows_by_symbol(universe_rows).get(symbol, {})
            try:
                bars = fetch_yahoo_daily_bars(symbol, start_date=start_date, end_date=end_date)
                row = analyze_symbol(
                    symbol=symbol,
                    universe=universe,
                    bars=bars,
                    base_usd=base_usd,
                    annual_return=annual_return,
                    data_start=start_date,
                    data_end=end_date,
                )
            except Exception as error:  # Keep a row so failures are visible in Excel.
                row = empty_error_row(symbol, universe, start_date, end_date, error)
            writer.writerow(row)
            handle.flush()
            print(f"{index}/{len(symbols)} wrote {symbol}: {row['analysis_status']}")
            if args.pause_seconds:
                time.sleep(args.pause_seconds)

    print(f"wrote {len(symbols)} rows to {output_path}")
    return 0


def read_universe(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def universe_rows_by_symbol(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {normalize_symbol(row.get("symbol", "")): row for row in rows if normalize_symbol(row.get("symbol", ""))}


def read_existing_symbols(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as handle:
        return {normalize_symbol(row.get("symbol", "")) for row in csv.DictReader(handle)}


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def dedupe(symbols: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for symbol in symbols:
        if symbol and symbol not in seen:
            seen.add(symbol)
            result.append(symbol)
    return result


def text_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def yahoo_symbol(symbol: str) -> str:
    return symbol.replace(".", "-")


def fetch_yahoo_daily_bars(symbol: str, *, start_date: date, end_date: date) -> list[Bar]:
    period1 = int(datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    period2 = int(datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{urllib.parse.quote(yahoo_symbol(symbol))}"
        f"?period1={period1}&period2={period2}&interval=1d&events=history&includeAdjustedClose=false"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "codex-crash-ladder-backtest/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)

    error = payload.get("chart", {}).get("error")
    if error:
        raise RuntimeError(f"Yahoo error: {error}")
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError("Yahoo returned no chart result")
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    bars: list[Bar] = []
    for timestamp, open_, high, low, close in zip(
        timestamps,
        quote.get("open") or [],
        quote.get("high") or [],
        quote.get("low") or [],
        quote.get("close") or [],
    ):
        if open_ is None or high is None or low is None or close is None:
            continue
        bars.append(
            Bar(
                day=datetime.fromtimestamp(timestamp, timezone.utc).date(),
                open=Decimal(str(open_)),
                high=Decimal(str(high)),
                low=Decimal(str(low)),
                close=Decimal(str(close)),
            )
        )
    if len(bars) < 2:
        raise RuntimeError("Yahoo returned fewer than two usable bars")
    return bars


def analyze_symbol(
    *,
    symbol: str,
    universe: dict[str, str],
    bars: list[Bar],
    base_usd: Decimal,
    annual_return: Decimal,
    data_start: date,
    data_end: date,
) -> dict[str, str]:
    event_index = find_crash_event_index(bars)
    event = bars[event_index]
    previous_close = bars[event_index - 1].close
    window_end = event.day + timedelta(days=30)
    trough_index = min(
        [index for index in range(event_index, len(bars)) if bars[index].day <= window_end],
        key=lambda index: bars[index].low,
    )
    trough = bars[trough_index]
    lots = build_lots(entry_price=previous_close, base_usd=base_usd, trough_low=trough.low)
    total_shares = sum((lot.shares for lot in lots), Decimal("0"))
    total_invested = sum((lot.trigger * lot.shares for lot in lots), Decimal("0"))
    avg_cost = total_invested / total_shares
    ten_pct_price = avg_cost * Decimal("1.10")

    break_even = first_high_at_or_above(bars, start_index=trough_index + 1, target=avg_cost)
    ten_pct = first_high_at_or_above(bars, start_index=trough_index + 1, target=ten_pct_price)
    latest = bars[-1]
    hold_value = latest.close * total_shares
    hold_profit = hold_value - total_invested

    ten_pct_sell_proceeds = total_invested * Decimal("1.10") if ten_pct else None
    reinvest_days = (latest.day - ten_pct.day).days if ten_pct else None
    reinvest_value = (
        ten_pct_sell_proceeds * ((Decimal("1") + annual_return) ** (Decimal(reinvest_days) / Decimal(365)))
        if ten_pct and ten_pct_sell_proceeds is not None and reinvest_days is not None
        else None
    )
    reinvest_profit = reinvest_value - total_invested if reinvest_value is not None else None

    deepest = lots[-1]
    return {
        "symbol": symbol,
        "name": universe.get("name", ""),
        "universe_active": universe.get("active", ""),
        "universe_tradable": universe.get("tradable", ""),
        "universe_fractional_eligible": universe.get("fractional_eligible", ""),
        "source": "yahoo_chart_api",
        "analysis_status": "ok",
        "error": "",
        "event_date": iso(event.day),
        "event_prev_close": money(previous_close),
        "event_open": money(event.open),
        "event_high": money(event.high),
        "event_low": money(event.low),
        "event_close": money(event.close),
        "event_close_drop_pct": pct((event.close / previous_close) - Decimal("1")),
        "event_low_drop_pct": pct((event.low / previous_close) - Decimal("1")),
        "trough_date": iso(trough.day),
        "trough_low": money(trough.low),
        "trough_close": money(trough.close),
        "trough_days_after_event": str((trough.day - event.day).days),
        "base_usd": money(base_usd),
        "base_entry_price": money(previous_close),
        "base_entry_date": iso(bars[event_index - 1].day),
        "base_lot_shares": qty(lots[0].shares),
        "lots_bought": str(len(lots)),
        "deepest_lot_index": str(deepest.index),
        "deepest_lot_trigger_price": money(deepest.trigger),
        "deepest_lot_shares": qty(deepest.shares),
        "total_shares": qty(total_shares),
        "total_invested": money(total_invested),
        "avg_cost_break_even_price": money(avg_cost),
        "ten_pct_gain_price": money(ten_pct_price),
        "break_even_date": iso(break_even.day) if break_even else "",
        "break_even_high": money(break_even.high) if break_even else "",
        "days_trough_to_break_even": str((break_even.day - trough.day).days) if break_even else "",
        "ten_pct_date": iso(ten_pct.day) if ten_pct else "",
        "ten_pct_high": money(ten_pct.high) if ten_pct else "",
        "days_trough_to_ten_pct": str((ten_pct.day - trough.day).days) if ten_pct else "",
        "latest_price_date": iso(latest.day),
        "latest_price": money(latest.close),
        "hold_value_today": money(hold_value),
        "hold_profit_today": money(hold_profit),
        "hold_return_pct_today": pct((hold_value / total_invested) - Decimal("1")),
        "ten_pct_sell_proceeds": money(ten_pct_sell_proceeds) if ten_pct_sell_proceeds else "",
        "reinvest_annual_return_pct": pct(annual_return),
        "reinvest_days_after_ten_pct": str(reinvest_days) if reinvest_days is not None else "",
        "sell_10_reinvest_value_today": money(reinvest_value) if reinvest_value is not None else "",
        "sell_10_reinvest_profit_today": money(reinvest_profit) if reinvest_profit is not None else "",
        "sell_10_reinvest_return_pct_today": pct((reinvest_value / total_invested) - Decimal("1"))
        if reinvest_value is not None
        else "",
        "sell_10_reinvest_delta_vs_hold": money(reinvest_value - hold_value) if reinvest_value is not None else "",
        "data_start": iso(data_start),
        "data_end": iso(data_end),
        "bars_count": str(len(bars)),
    }


def find_crash_event_index(bars: list[Bar]) -> int:
    best_index = 1
    best_score = Decimal("999")
    for index in range(1, len(bars)):
        previous_close = bars[index - 1].close
        if previous_close <= 0:
            continue
        bar = bars[index]
        close_drop = (bar.close / previous_close) - Decimal("1")
        low_drop = (bar.low / previous_close) - Decimal("1")
        score = close_drop
        if close_drop <= Decimal("-0.45") or low_drop <= Decimal("-0.60"):
            score = close_drop - Decimal("1")
        if score < best_score:
            best_score = score
            best_index = index
    return best_index


def build_lots(*, entry_price: Decimal, base_usd: Decimal, trough_low: Decimal) -> list[LadderLot]:
    base_shares = lot_shares_for_target(entry_price, base_usd)
    lots: list[LadderLot] = []
    index = 1
    trigger = entry_price
    shares = base_shares
    while True:
        lots.append(LadderLot(index=index, trigger=trigger, shares=shares))
        next_index = index + 1
        next_trigger = trigger * (Decimal("1") - drop_pct_for_next_lot(next_index))
        if next_trigger < trough_low:
            return lots
        index = next_index
        trigger = next_trigger
        shares = shares * Decimal("2")
        if index > 100:
            return lots


def lot_shares_for_target(price: Decimal, target_usd: Decimal) -> Decimal:
    if price < Decimal("1.00"):
        return max((target_usd / price).to_integral_value(rounding=ROUND_FLOOR), Decimal("1"))
    return target_usd / price


def drop_pct_for_next_lot(next_lot_index: int) -> Decimal:
    if next_lot_index <= 5:
        return Decimal("0.10")
    if next_lot_index <= 10:
        return Decimal("0.20")
    if next_lot_index <= 15:
        return Decimal("0.40")
    return Decimal("0.80")


def first_high_at_or_above(bars: list[Bar], *, start_index: int, target: Decimal) -> Bar | None:
    for bar in bars[start_index:]:
        if bar.high >= target:
            return bar
    return None


def empty_error_row(symbol: str, universe: dict[str, str], data_start: date, data_end: date, error: Exception) -> dict[str, str]:
    row = {field: "" for field in CSV_FIELDS}
    row.update(
        {
            "symbol": symbol,
            "name": universe.get("name", ""),
            "universe_active": universe.get("active", ""),
            "universe_tradable": universe.get("tradable", ""),
            "universe_fractional_eligible": universe.get("fractional_eligible", ""),
            "source": "yahoo_chart_api",
            "analysis_status": "error",
            "error": str(error),
            "data_start": iso(data_start),
            "data_end": iso(data_end),
        }
    )
    return row


def iso(value: date) -> str:
    return value.isoformat()


def money(value: Decimal | None) -> str:
    if value is None or not value.is_finite():
        return ""
    return f"{value:.4f}"


def qty(value: Decimal) -> str:
    return f"{value:.8f}"


def pct(value: Decimal) -> str:
    if not value.is_finite():
        return ""
    return f"{value * Decimal('100'):.4f}"


if __name__ == "__main__":
    raise SystemExit(main())
