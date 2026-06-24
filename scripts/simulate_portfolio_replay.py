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


getcontext().prec = 28

BASE_USD = Decimal("1")
CASH_RESERVE_PCT = Decimal("0.15")
SELL_GAIN_PCT = Decimal("0.10")

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


@dataclass
class Position:
    symbol: str
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
        return self.lots[-1].trigger * (Decimal("1") - drop_pct_for_next_lot(self.next_lot_index))

    @property
    def next_shares(self) -> Decimal:
        return self.lots[-1].shares * Decimal("2")


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay the strategy over a fixed symbol set with shared cash.")
    parser.add_argument("--symbols-csv", default="data/runtime/crash-ladder-backtest.csv")
    parser.add_argument("--output", default="data/runtime/portfolio-replay-50-daily.csv")
    parser.add_argument("--start-date", default="2025-06-21")
    parser.add_argument("--end-date", default="2026-06-21")
    parser.add_argument("--starting-cash", default="1000")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--pause-seconds", type=float, default=0.1)
    parser.add_argument(
        "--force-green-sales",
        action="store_true",
        help="Before depositing for DD cash, sell all green positions below the 10% target.",
    )
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)
    starting_cash = Decimal(args.starting_cash)
    symbols = read_symbols(Path(args.symbols_csv), limit=args.limit)
    if not symbols:
        raise SystemExit("no symbols found")

    bars_by_symbol: dict[str, list[Bar]] = {}
    for index, symbol in enumerate(symbols, start=1):
        bars_by_symbol[symbol] = fetch_yahoo_daily_bars(symbol, start_date=start_date, end_date=end_date)
        print(f"{index}/{len(symbols)} fetched {symbol}: {len(bars_by_symbol[symbol])} bars")
        if args.pause_seconds:
            time.sleep(args.pause_seconds)

    daily_rows = simulate(
        symbols,
        bars_by_symbol,
        start_date=start_date,
        end_date=end_date,
        starting_cash=starting_cash,
        force_green_sales=args.force_green_sales,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DAILY_FIELDS)
        writer.writeheader()
        writer.writerows(daily_rows)

    print(f"wrote {len(daily_rows)} daily rows to {output}")
    return 0


def read_symbols(path: Path, *, limit: int) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        symbols: list[str] = []
        for row in csv.DictReader(handle):
            symbol = (row.get("symbol") or "").strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
            if len(symbols) >= limit:
                break
    return symbols


def fetch_yahoo_daily_bars(symbol: str, *, start_date: date, end_date: date) -> list[Bar]:
    period1 = int(datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    period2 = int(datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp())
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{urllib.parse.quote(symbol.replace('.', '-'))}"
        f"?period1={period1}&period2={period2}&interval=1d&events=history&includeAdjustedClose=false"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "codex-portfolio-replay/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    error = payload.get("chart", {}).get("error")
    if error:
        raise RuntimeError(f"{symbol}: Yahoo error: {error}")
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"{symbol}: Yahoo returned no chart result")
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    bars: list[Bar] = []
    for timestamp, open_, high, low, close in zip(
        result.get("timestamp") or [],
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
    if not bars:
        raise RuntimeError(f"{symbol}: Yahoo returned no usable bars")
    return bars


def simulate(
    symbols: list[str],
    bars_by_symbol: dict[str, list[Bar]],
    *,
    start_date: date,
    end_date: date,
    starting_cash: Decimal,
    force_green_sales: bool = False,
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

        # Same-day sold symbols try to reopen at the modeled sell price. Older
        # pending symbols use the day's close because daily bars cannot prove a
        # better immediate fill.
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
                "drawdown_pct": pct(drawdown_pct),
            }
        )

    return rows


def new_base_position(symbol: str, price: Decimal) -> Position:
    shares = lot_shares_for_target(price, BASE_USD)
    return Position(symbol=symbol, lots=[Lot(index=1, trigger=price, shares=shares, cost=shares * price)])


def due_dd_lots(position: Position, low: Decimal) -> list[Lot]:
    lots: list[Lot] = []
    trigger = position.next_trigger
    shares = position.next_shares
    index = position.next_lot_index
    while low <= trigger:
        lots.append(Lot(index=index, trigger=trigger, shares=shares, cost=trigger * shares))
        index += 1
        trigger = trigger * (Decimal("1") - drop_pct_for_next_lot(index))
        shares *= Decimal("2")
        if index > 100:
            break
    return lots


def can_spend_for_open(
    cash: Decimal,
    positions: dict[str, Position],
    last_close: dict[str, Decimal],
    cost: Decimal,
) -> bool:
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


def drop_pct_for_next_lot(next_lot_index: int) -> Decimal:
    if next_lot_index <= 5:
        return Decimal("0.10")
    if next_lot_index <= 10:
        return Decimal("0.20")
    if next_lot_index <= 15:
        return Decimal("0.40")
    return Decimal("0.80")


def money(value: Decimal) -> str:
    return f"{value:.4f}"


def pct(value: Decimal) -> str:
    return f"{value:.4f}"


if __name__ == "__main__":
    raise SystemExit(main())
