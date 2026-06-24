from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR, getcontext
from pathlib import Path
from typing import Iterable


getcontext().prec = 28

BASE_USD = Decimal("1")
CASH_RESERVE_PCT = Decimal("0.15")
SELL_GAIN_PCT = Decimal("0.10")
UNDER5_THRESHOLD = Decimal("5.00")

DAILY_FIELDS = [
    "date",
    "portfolio_value",
    "deposit_adjusted_value",
    "cash",
    "cost_basis",
    "deposits_total",
    "day_deposit",
    "new_opens",
    "dd_lots_bought",
    "sells",
    "forced_green_sells",
    "forced_green_sale_proceeds",
    "reopens",
    "pending_reopens",
    "drawdown_pct",
]

INDEPENDENT_FIELDS = [
    "symbol",
    "name",
    "universe_active",
    "universe_tradable",
    "universe_fractional_eligible",
    "source",
    "analysis_status",
    "error",
    "ladder_profile",
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

TRACKER_FIELDS = [
    "strategy_view",
    "symbol_count",
    "reached_10_count",
    "no_hit_10_count",
    "total_invested",
    "total_deposited",
    "extra_deposits",
    "ending_value",
    "profit",
    "return_pct",
    "deposit_adjusted_return_pct",
    "max_drawdown_pct",
    "deposit_days",
    "sells",
    "reopens",
    "dd_lots",
    "forced_green_sells",
    "forced_green_sale_proceeds",
    "notes",
]


@dataclass(frozen=True)
class Bar:
    day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass
class Lot:
    index: int
    trigger: Decimal
    shares: Decimal
    cost: Decimal


@dataclass(frozen=True)
class ModeledLot:
    index: int
    trigger: Decimal
    shares: Decimal


@dataclass
class Position:
    symbol: str
    ladder_profile: str
    lots: list[Lot]

    @property
    def shares(self) -> Decimal:
        return sum((lot.shares for lot in self.lots), Decimal("0"))

    @property
    def cost_basis(self) -> Decimal:
        return sum((lot.cost for lot in self.lots), Decimal("0"))

    @property
    def average_cost(self) -> Decimal:
        return self.cost_basis / self.shares

    @property
    def next_lot_index(self) -> int:
        return self.lots[-1].index + 1

    @property
    def next_trigger(self) -> Decimal:
        return self.lots[-1].trigger * (
            Decimal("1") - drop_pct_for_next_lot(self.next_lot_index, self.ladder_profile)
        )

    @property
    def next_shares(self) -> Decimal:
        return self.lots[-1].shares * Decimal("2")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run cached one-year replay using Ref 2023 ladder for positions opened under $5."
    )
    parser.add_argument("--universe", default="data/universe.csv")
    parser.add_argument("--cache-dir", default="data/runtime/yahoo-daily-bars")
    parser.add_argument("--existing-independent", default="data/runtime/crash-ladder-backtest.csv")
    parser.add_argument("--output-independent", default="data/runtime/crash-ladder-backtest-ref2023-under5.csv")
    parser.add_argument("--output-daily", default="data/runtime/portfolio-replay-all-daily-ref2023-under5.csv")
    parser.add_argument(
        "--output-forced-daily",
        default="data/runtime/portfolio-replay-all-daily-ref2023-under5-forced-green.csv",
    )
    parser.add_argument("--output-tracker", default="data/runtime/strategy-ref2023-under5-summary.csv")
    parser.add_argument("--output-comparison", default="data/runtime/ref2023-under5-comparison-summary.json")
    parser.add_argument("--start-date", default="2025-06-21")
    parser.add_argument("--end-date", default="2026-06-21")
    parser.add_argument("--starting-cash", default="1000")
    parser.add_argument("--annual-return", default="0.20")
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)
    starting_cash = Decimal(args.starting_cash)
    annual_return = Decimal(args.annual_return)
    universe_rows = read_universe(Path(args.universe))
    symbols = build_symbol_order(universe_rows, Path(args.existing_independent))
    bars_by_symbol = {
        symbol: bars
        for symbol in symbols
        if (bars := load_cached_bars(symbol, Path(args.cache_dir)))
    }
    symbols = [symbol for symbol in symbols if symbol in bars_by_symbol]
    universe_by_symbol = rows_by_symbol(universe_rows)

    independent_rows = [
        analyze_symbol(
            symbol=symbol,
            universe=universe_by_symbol.get(symbol, {}),
            bars=bars_by_symbol[symbol],
            data_start=start_date,
            data_end=end_date,
            annual_return=annual_return,
        )
        for symbol in symbols
    ]
    daily_rows = simulate(
        symbols,
        bars_by_symbol,
        start_date=start_date,
        end_date=end_date,
        starting_cash=starting_cash,
        force_green_sales=False,
    )
    forced_rows = simulate(
        symbols,
        bars_by_symbol,
        start_date=start_date,
        end_date=end_date,
        starting_cash=starting_cash,
        force_green_sales=True,
    )

    write_rows(Path(args.output_independent), INDEPENDENT_FIELDS, independent_rows)
    write_rows(Path(args.output_daily), DAILY_FIELDS, daily_rows)
    write_rows(Path(args.output_forced_daily), DAILY_FIELDS, forced_rows)

    tracker_rows = build_tracker_rows(independent_rows, daily_rows, forced_rows, starting_cash=starting_cash)
    write_rows(Path(args.output_tracker), TRACKER_FIELDS, tracker_rows)

    comparison = build_comparison_summary(
        old_independent=read_csv(Path(args.existing_independent)),
        new_independent=independent_rows,
        old_daily=read_csv(Path("data/runtime/portfolio-replay-all-daily.csv")),
        old_forced=read_csv(Path("data/runtime/portfolio-replay-all-daily-forced-green.csv")),
        new_daily=daily_rows,
        new_forced=forced_rows,
        starting_cash=starting_cash,
    )
    write_json(Path(args.output_comparison), comparison)
    print(
        json.dumps(
            {
                "symbols": len(symbols),
                "independent": args.output_independent,
                "daily": args.output_daily,
                "forced_daily": args.output_forced_daily,
                "tracker": args.output_tracker,
                "comparison": args.output_comparison,
            }
        )
    )
    return 0


def read_universe(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def rows_by_symbol(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {normalize_symbol(row.get("symbol", "")): row for row in rows if normalize_symbol(row.get("symbol", ""))}


def build_symbol_order(universe_rows: list[dict[str, str]], existing_independent: Path) -> list[str]:
    result = [normalize_symbol(row.get("symbol", "")) for row in read_csv(existing_independent)]
    result = [symbol for symbol in result if symbol]
    seen = set(result)
    for row in universe_rows:
        symbol = normalize_symbol(row.get("symbol", ""))
        if not symbol or symbol in seen:
            continue
        if text_bool(row.get("active")) is False or text_bool(row.get("tradable")) is False:
            continue
        result.append(symbol)
        seen.add(symbol)
    return result


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def text_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def load_cached_bars(symbol: str, cache_dir: Path) -> list[Bar]:
    path = cache_dir / f"{symbol.replace('.', '_').replace('/', '_').replace(chr(92), '_')}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") != "ok":
            return []
        return [
            Bar(
                day=date.fromisoformat(item["date"]),
                open=Decimal(item["open"]),
                high=Decimal(item["high"]),
                low=Decimal(item["low"]),
                close=Decimal(item["close"]),
            )
            for item in payload.get("bars", [])
        ]
    except Exception:
        return []


def ladder_profile_for_entry(price: Decimal) -> str:
    return "ref2023_under5" if price < UNDER5_THRESHOLD else "current"


def drop_pct_for_next_lot(next_lot_index: int, ladder_profile: str) -> Decimal:
    if ladder_profile == "ref2023_under5":
        if next_lot_index <= 11:
            return Decimal("0.20")
        return Decimal("0.40")
    if next_lot_index <= 5:
        return Decimal("0.10")
    if next_lot_index <= 10:
        return Decimal("0.20")
    if next_lot_index <= 15:
        return Decimal("0.40")
    return Decimal("0.80")


def analyze_symbol(
    *,
    symbol: str,
    universe: dict[str, str],
    bars: list[Bar],
    data_start: date,
    data_end: date,
    annual_return: Decimal,
) -> dict[str, str]:
    try:
        event_index = find_crash_event_index(bars)
        event = bars[event_index]
        previous_close = bars[event_index - 1].close
        window_end = event.day + timedelta(days=30)
        trough_index = min(
            [index for index in range(event_index, len(bars)) if bars[index].day <= window_end],
            key=lambda index: bars[index].low,
        )
        trough = bars[trough_index]
        ladder_profile = ladder_profile_for_entry(previous_close)
        lots = build_lots(
            entry_price=previous_close,
            base_usd=BASE_USD,
            trough_low=trough.low,
            ladder_profile=ladder_profile,
        )
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
            "source": "cached_yahoo_daily_bars",
            "analysis_status": "ok",
            "error": "",
            "ladder_profile": ladder_profile,
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
            "base_usd": money(BASE_USD),
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
            "ten_pct_sell_proceeds": money(ten_pct_sell_proceeds) if ten_pct_sell_proceeds is not None else "",
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
    except Exception as error:
        row = {field: "" for field in INDEPENDENT_FIELDS}
        row.update(
            {
                "symbol": symbol,
                "name": universe.get("name", ""),
                "universe_active": universe.get("active", ""),
                "universe_tradable": universe.get("tradable", ""),
                "universe_fractional_eligible": universe.get("fractional_eligible", ""),
                "source": "cached_yahoo_daily_bars",
                "analysis_status": "error",
                "error": str(error),
                "data_start": iso(data_start),
                "data_end": iso(data_end),
                "bars_count": str(len(bars)),
            }
        )
        return row


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


def build_lots(
    *,
    entry_price: Decimal,
    base_usd: Decimal,
    trough_low: Decimal,
    ladder_profile: str,
) -> list[ModeledLot]:
    base_shares = lot_shares_for_target(entry_price, base_usd)
    lots: list[ModeledLot] = []
    index = 1
    trigger = entry_price
    shares = base_shares
    while True:
        lots.append(ModeledLot(index=index, trigger=trigger, shares=shares))
        next_index = index + 1
        next_trigger = trigger * (Decimal("1") - drop_pct_for_next_lot(next_index, ladder_profile))
        if next_trigger < trough_low:
            return lots
        index = next_index
        trigger = next_trigger
        shares *= Decimal("2")
        if index > 100:
            return lots


def first_high_at_or_above(bars: list[Bar], *, start_index: int, target: Decimal) -> Bar | None:
    for bar in bars[start_index:]:
        if bar.high >= target:
            return bar
    return None


def simulate(
    symbols: list[str],
    bars_by_symbol: dict[str, list[Bar]],
    *,
    start_date: date,
    end_date: date,
    starting_cash: Decimal,
    force_green_sales: bool,
) -> list[dict[str, str]]:
    bar_maps = {symbol: {bar.day: bar for bar in bars} for symbol, bars in bars_by_symbol.items()}
    trade_days = sorted({bar.day for bars in bars_by_symbol.values() for bar in bars if start_date <= bar.day <= end_date})
    first_trade_day = {symbol: bars[0].day for symbol, bars in bars_by_symbol.items()}
    cash = starting_cash
    deposits_total = starting_cash
    positions: dict[str, Position] = {}
    pending_reopens: set[str] = set()
    ever_opened: set[str] = set()
    last_close: dict[str, Decimal] = {}
    peak_adjusted_value = starting_cash
    rows: list[dict[str, str]] = []

    for day in trade_days:
        day_deposit = Decimal("0")
        day_dd_lots = 0
        day_sells = 0
        day_forced_green_sells = 0
        day_forced_green_sale_proceeds = Decimal("0")
        day_reopens = 0
        opened_today: set[str] = set()
        dd_today: set[str] = set()
        sell_prices: dict[str, Decimal] = {}
        day_new_opens = 0

        for symbol in symbols:
            bar = bar_maps[symbol].get(day)
            if bar:
                last_close[symbol] = bar.close
            if (
                bar
                and symbol not in ever_opened
                and symbol not in positions
                and symbol not in pending_reopens
                and first_trade_day[symbol] <= day
            ):
                position = new_base_position(symbol, bar.open)
                cost = position.cost_basis
                if can_spend_for_open(cash, positions, last_close, cost):
                    cash -= cost
                    positions[symbol] = position
                    ever_opened.add(symbol)
                    opened_today.add(symbol)
                    day_new_opens += 1

        due_orders: list[tuple[str, list[Lot]]] = []
        for symbol in symbols:
            position = positions.get(symbol)
            bar = bar_maps[symbol].get(day)
            if position is None or bar is None or symbol in opened_today:
                continue
            due_lots = due_dd_lots(position, bar.low)
            if due_lots:
                due_orders.append((symbol, due_lots))

        due_cost = sum((sum((lot.cost for lot in lots), Decimal("0")) for _, lots in due_orders), Decimal("0"))
        if force_green_sales and due_cost > cash:
            due_symbols = {symbol for symbol, _ in due_orders}
            green_candidates = rank_green_cash_candidates(
                positions,
                bar_maps,
                day=day,
                exclude_symbols=due_symbols | opened_today,
            )
            for symbol, sale_price, _return_pct in green_candidates:
                if symbol not in positions:
                    continue
                position = positions.pop(symbol)
                proceeds = position.shares * sale_price
                cash += proceeds
                day_forced_green_sells += 1
                day_forced_green_sale_proceeds += proceeds
                pending_reopens.add(symbol)
        if due_cost > cash:
            day_deposit = due_cost - cash
            cash += day_deposit
            deposits_total += day_deposit

        for symbol, lots in due_orders:
            position = positions[symbol]
            position.lots.extend(lots)
            cash -= sum((lot.cost for lot in lots), Decimal("0"))
            day_dd_lots += len(lots)
            dd_today.add(symbol)

        for symbol in symbols:
            position = positions.get(symbol)
            bar = bar_maps[symbol].get(day)
            if position is None or bar is None or symbol in opened_today or symbol in dd_today:
                continue
            target = position.average_cost * (Decimal("1") + SELL_GAIN_PCT)
            if bar.high >= target:
                proceeds = position.shares * target
                cash += proceeds
                del positions[symbol]
                pending_reopens.add(symbol)
                sell_prices[symbol] = target
                day_sells += 1

        for symbol in sorted(pending_reopens):
            bar = bar_maps[symbol].get(day)
            if not bar:
                continue
            reopen_price = sell_prices.get(symbol, bar.close)
            position = new_base_position(symbol, reopen_price)
            if can_spend_for_open(cash, positions, last_close, position.cost_basis):
                cash -= position.cost_basis
                positions[symbol] = position
                ever_opened.add(symbol)
                day_reopens += 1

        for symbol in list(positions):
            pending_reopens.discard(symbol)

        portfolio_value = cash + market_value(positions, last_close)
        deposit_adjusted_value = portfolio_value - (deposits_total - starting_cash)
        peak_adjusted_value = max(peak_adjusted_value, deposit_adjusted_value)
        drawdown_pct = (deposit_adjusted_value / peak_adjusted_value - Decimal("1")) * Decimal("100")
        rows.append(
            {
                "date": day.isoformat(),
                "portfolio_value": money(portfolio_value),
                "deposit_adjusted_value": money(deposit_adjusted_value),
                "cash": money(cash),
                "cost_basis": money(total_cost_basis(positions)),
                "deposits_total": money(deposits_total),
                "day_deposit": money(day_deposit),
                "new_opens": str(day_new_opens),
                "dd_lots_bought": str(day_dd_lots),
                "sells": str(day_sells),
                "forced_green_sells": str(day_forced_green_sells),
                "forced_green_sale_proceeds": money(day_forced_green_sale_proceeds),
                "reopens": str(day_reopens),
                "pending_reopens": str(len(pending_reopens)),
                "drawdown_pct": pct_plain(drawdown_pct),
            }
        )

    return rows


def new_base_position(symbol: str, price: Decimal) -> Position:
    ladder_profile = ladder_profile_for_entry(price)
    shares = lot_shares_for_target(price, BASE_USD)
    return Position(symbol=symbol, ladder_profile=ladder_profile, lots=[Lot(index=1, trigger=price, shares=shares, cost=shares * price)])


def due_dd_lots(position: Position, low: Decimal) -> list[Lot]:
    lots: list[Lot] = []
    trigger = position.next_trigger
    shares = position.next_shares
    index = position.next_lot_index
    while low <= trigger:
        lots.append(Lot(index=index, trigger=trigger, shares=shares, cost=trigger * shares))
        index += 1
        trigger = trigger * (Decimal("1") - drop_pct_for_next_lot(index, position.ladder_profile))
        shares *= Decimal("2")
        if index > 100:
            break
    return lots


def can_spend_for_open(cash: Decimal, positions: dict[str, Position], last_close: dict[str, Decimal], cost: Decimal) -> bool:
    if cash < cost:
        return False
    value_before = cash + market_value(positions, last_close)
    return cash - cost >= value_before * CASH_RESERVE_PCT


def rank_green_cash_candidates(
    positions: dict[str, Position],
    bar_maps: dict[str, dict[date, Bar]],
    *,
    day: date,
    exclude_symbols: set[str],
) -> list[tuple[str, Decimal, Decimal]]:
    candidates: list[tuple[str, Decimal, Decimal]] = []
    for symbol, position in positions.items():
        if symbol in exclude_symbols:
            continue
        bar = bar_maps[symbol].get(day)
        if bar is None:
            continue
        average_cost = position.average_cost
        target_price = average_cost * (Decimal("1") + SELL_GAIN_PCT)
        if average_cost < bar.close < target_price:
            return_pct = (bar.close / average_cost) - Decimal("1")
            candidates.append((symbol, bar.close, return_pct))
    return sorted(candidates, key=lambda item: item[2], reverse=True)


def market_value(positions: dict[str, Position], last_close: dict[str, Decimal]) -> Decimal:
    total = Decimal("0")
    for symbol, position in positions.items():
        close = last_close.get(symbol)
        if close is not None:
            total += position.shares * close
    return total


def total_cost_basis(positions: dict[str, Position]) -> Decimal:
    return sum((position.cost_basis for position in positions.values()), Decimal("0"))


def lot_shares_for_target(price: Decimal, target_usd: Decimal) -> Decimal:
    if price < Decimal("1.00"):
        return max((target_usd / price).to_integral_value(rounding=ROUND_FLOOR), Decimal("1"))
    return target_usd / price


def build_tracker_rows(
    independent_rows: list[dict[str, str]],
    daily_rows: list[dict[str, str]],
    forced_rows: list[dict[str, str]],
    *,
    starting_cash: Decimal,
) -> list[dict[str, str]]:
    ok_rows = [row for row in independent_rows if row.get("analysis_status") == "ok"]
    hit_rows = [row for row in ok_rows if row.get("ten_pct_date")]
    no_hit_rows = [row for row in ok_rows if not row.get("ten_pct_date")]
    independent_invested = sum((decimal(row.get("total_invested")) for row in ok_rows), Decimal("0"))
    independent_hold_profit = sum((decimal(row.get("hold_profit_today")) for row in ok_rows), Decimal("0"))
    independent_hold_value = independent_invested + independent_hold_profit
    independent_sell_profit = sum((decimal(row.get("sell_10_reinvest_profit_today")) for row in hit_rows), Decimal("0")) + sum(
        (decimal(row.get("hold_profit_today")) for row in no_hit_rows),
        Decimal("0"),
    )
    independent_sell_value = independent_invested + independent_sell_profit
    deposit_metrics = summarize_replay(daily_rows, starting_cash=starting_cash)
    forced_metrics = summarize_replay(forced_rows, starting_cash=starting_cash)
    size = len(ok_rows)
    return [
        independent_tracker_row(
            view="independent_hold_ref2023_under5",
            symbol_count=size,
            hit_count=len(hit_rows),
            no_hit_count=len(no_hit_rows),
            invested=independent_invested,
            value=independent_hold_value,
            profit=independent_hold_profit,
            notes="Single-stock independent test; Ref 2023 ladder only when base entry is under $5",
        ),
        independent_tracker_row(
            view="independent_sell10_ref2023_under5",
            symbol_count=size,
            hit_count=len(hit_rows),
            no_hit_count=len(no_hit_rows),
            invested=independent_invested,
            value=independent_sell_value,
            profit=independent_sell_profit,
            notes="Single-stock independent test; first modeled 10% sell, then reinvests at 20% annualized",
        ),
        replay_tracker_row(
            view="replay_deposit_only_ref2023_under5",
            symbol_count=size,
            metrics=deposit_metrics,
            notes="Shared-cash replay; DD shortfalls covered by deposits; under-$5 entries use Ref 2023",
        ),
        replay_tracker_row(
            view="replay_forced_green_ref2023_under5",
            symbol_count=size,
            metrics=forced_metrics,
            notes="Shared-cash replay; green positions sold before deposits; under-$5 entries use Ref 2023",
        ),
    ]


def summarize_replay(rows: list[dict[str, str]], *, starting_cash: Decimal) -> dict[str, Decimal | int]:
    final = rows[-1]
    max_drawdown = min((decimal(row.get("drawdown_pct")) for row in rows), default=Decimal("0"))
    deposits = decimal(final.get("deposits_total"))
    portfolio_value = decimal(final.get("portfolio_value"))
    adjusted_value = decimal(final.get("deposit_adjusted_value"))
    return {
        "portfolio_value": portfolio_value,
        "deposits": deposits,
        "extra_deposits": deposits - starting_cash,
        "profit": portfolio_value - deposits,
        "return_pct": percentage((portfolio_value / deposits) - Decimal("1")) if deposits else Decimal("0"),
        "deposit_adjusted_return_pct": percentage((adjusted_value / starting_cash) - Decimal("1")) if starting_cash else Decimal("0"),
        "max_drawdown_pct": max_drawdown,
        "deposit_days": sum(1 for row in rows if decimal(row.get("day_deposit")) > 0),
        "sells": sum(int(row.get("sells") or 0) for row in rows),
        "reopens": sum(int(row.get("reopens") or 0) for row in rows),
        "dd_lots": sum(int(row.get("dd_lots_bought") or 0) for row in rows),
        "forced_green_sells": sum(int(row.get("forced_green_sells") or 0) for row in rows),
        "forced_green_sale_proceeds": sum((decimal(row.get("forced_green_sale_proceeds")) for row in rows), Decimal("0")),
    }


def independent_tracker_row(
    *,
    view: str,
    symbol_count: int,
    hit_count: int,
    no_hit_count: int,
    invested: Decimal,
    value: Decimal,
    profit: Decimal,
    notes: str,
) -> dict[str, str]:
    return {
        "strategy_view": view,
        "symbol_count": str(symbol_count),
        "reached_10_count": str(hit_count),
        "no_hit_10_count": str(no_hit_count),
        "total_invested": money(invested),
        "total_deposited": "",
        "extra_deposits": "",
        "ending_value": money(value),
        "profit": money(profit),
        "return_pct": money(percentage((value / invested) - Decimal("1"))) if invested else "",
        "deposit_adjusted_return_pct": "",
        "max_drawdown_pct": "",
        "deposit_days": "",
        "sells": "",
        "reopens": "",
        "dd_lots": "",
        "forced_green_sells": "",
        "forced_green_sale_proceeds": "",
        "notes": notes,
    }


def replay_tracker_row(*, view: str, symbol_count: int, metrics: dict[str, Decimal | int], notes: str) -> dict[str, str]:
    return {
        "strategy_view": view,
        "symbol_count": str(symbol_count),
        "reached_10_count": "",
        "no_hit_10_count": "",
        "total_invested": "",
        "total_deposited": money(metrics["deposits"]),
        "extra_deposits": money(metrics["extra_deposits"]),
        "ending_value": money(metrics["portfolio_value"]),
        "profit": money(metrics["profit"]),
        "return_pct": money(metrics["return_pct"]),
        "deposit_adjusted_return_pct": money(metrics["deposit_adjusted_return_pct"]),
        "max_drawdown_pct": money(metrics["max_drawdown_pct"]),
        "deposit_days": str(metrics["deposit_days"]),
        "sells": str(metrics["sells"]),
        "reopens": str(metrics["reopens"]),
        "dd_lots": str(metrics["dd_lots"]),
        "forced_green_sells": str(metrics["forced_green_sells"]),
        "forced_green_sale_proceeds": money(metrics["forced_green_sale_proceeds"]),
        "notes": notes,
    }


def build_comparison_summary(
    *,
    old_independent: list[dict[str, str]],
    new_independent: list[dict[str, str]],
    old_daily: list[dict[str, str]],
    old_forced: list[dict[str, str]],
    new_daily: list[dict[str, str]],
    new_forced: list[dict[str, str]],
    starting_cash: Decimal,
) -> dict[str, object]:
    old_independent_by_symbol = rows_by_symbol(old_independent)
    new_independent_by_symbol = rows_by_symbol(new_independent)
    old_ok = [row for row in old_independent if row.get("analysis_status") == "ok"]
    new_ok = [row for row in new_independent if row.get("analysis_status") == "ok"]
    under5_count = sum(1 for row in new_ok if row.get("ladder_profile") == "ref2023_under5")
    return {
        "generated_from": "cached_yahoo_daily_bars",
        "new_ladder_rule": "positions opened below $5 use 20% DD drops through lot 11, then 40% drops thereafter",
        "symbols": len(new_ok),
        "under5_independent_symbols": under5_count,
        "old": {
            "independent": independent_summary(old_ok),
            "replay_deposit_only": stringify_summary(summarize_replay(old_daily, starting_cash=starting_cash)),
            "replay_forced_green": stringify_summary(summarize_replay(old_forced, starting_cash=starting_cash)),
        },
        "new": {
            "independent": independent_summary(new_ok),
            "replay_deposit_only": stringify_summary(summarize_replay(new_daily, starting_cash=starting_cash)),
            "replay_forced_green": stringify_summary(summarize_replay(new_forced, starting_cash=starting_cash)),
        },
        "inlf": {
            "old": old_independent_by_symbol.get("INLF", {}),
            "new": new_independent_by_symbol.get("INLF", {}),
        },
    }


def independent_summary(rows: list[dict[str, str]]) -> dict[str, str]:
    hit_rows = [row for row in rows if row.get("ten_pct_date")]
    no_hit_rows = [row for row in rows if not row.get("ten_pct_date")]
    invested = sum((decimal(row.get("total_invested")) for row in rows), Decimal("0"))
    hold_profit = sum((decimal(row.get("hold_profit_today")) for row in rows), Decimal("0"))
    sell_profit = sum((decimal(row.get("sell_10_reinvest_profit_today")) for row in hit_rows), Decimal("0")) + sum(
        (decimal(row.get("hold_profit_today")) for row in no_hit_rows),
        Decimal("0"),
    )
    return {
        "symbol_count": str(len(rows)),
        "reached_10_count": str(len(hit_rows)),
        "no_hit_10_count": str(len(no_hit_rows)),
        "total_invested": money(invested),
        "hold_profit": money(hold_profit),
        "hold_return_pct": money(percentage(hold_profit / invested)) if invested else "",
        "sell10_plus_unsold_profit": money(sell_profit),
        "sell10_plus_unsold_return_pct": money(percentage(sell_profit / invested)) if invested else "",
    }


def stringify_summary(summary: dict[str, Decimal | int]) -> dict[str, str]:
    return {key: money(value) if isinstance(value, Decimal) else str(value) for key, value in summary.items()}


def write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def decimal(value: str | None) -> Decimal:
    if not value:
        return Decimal("0")
    return Decimal(value)


def percentage(value: Decimal) -> Decimal:
    return value * Decimal("100")


def money(value: Decimal | int | None) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if not value.is_finite():
        return ""
    return f"{value:.4f}"


def qty(value: Decimal) -> str:
    return f"{value:.8f}"


def pct(value: Decimal) -> str:
    if not value.is_finite():
        return ""
    return f"{value * Decimal('100'):.4f}"


def pct_plain(value: Decimal) -> str:
    if not value.is_finite():
        return ""
    return f"{value:.4f}"


def iso(value: date) -> str:
    return value.isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
