from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from generate_crash_ladder_backtest import (  # noqa: E402
    CSV_FIELDS,
    SEED_SYMBOLS,
    Bar,
    analyze_symbol,
    empty_error_row,
    fetch_yahoo_daily_bars,
    normalize_symbol,
    read_universe,
    text_bool,
)
from simulate_portfolio_replay import DAILY_FIELDS, Bar as ReplayBar, simulate  # noqa: E402


TRACKER_FIELDS = [
    "universe_size",
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run paced +50 strategy scaling backtests across the whole universe.")
    parser.add_argument("--universe", default="data/universe.csv")
    parser.add_argument("--independent-output", default="data/runtime/crash-ladder-backtest.csv")
    parser.add_argument("--tracker-output", default="data/runtime/strategy-scaling-performance.csv")
    parser.add_argument("--cache-dir", default="data/runtime/yahoo-daily-bars")
    parser.add_argument("--daily-output", default="data/runtime/portfolio-replay-all-daily.csv")
    parser.add_argument("--forced-daily-output", default="data/runtime/portfolio-replay-all-daily-forced-green.csv")
    parser.add_argument("--start-date", default="2025-06-21")
    parser.add_argument("--end-date", default="2026-06-21")
    parser.add_argument("--starting-cash", default="1000")
    parser.add_argument("--base-usd", default="1")
    parser.add_argument("--annual-return", default="0.20")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--sleep-seconds", type=int, default=300)
    parser.add_argument("--per-symbol-pause", type=float, default=0.05)
    parser.add_argument("--max-symbols", type=int, default=0, help="Optional cap for testing/resume slices.")
    parser.add_argument("--retry-count", type=int, default=3)
    parser.add_argument("--retry-sleep-seconds", type=int, default=30)
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)
    starting_cash = Decimal(args.starting_cash)
    base_usd = Decimal(args.base_usd)
    annual_return = Decimal(args.annual_return)
    independent_path = Path(args.independent_output)
    tracker_path = Path(args.tracker_output)
    cache_dir = Path(args.cache_dir)

    universe_rows = read_universe(Path(args.universe))
    final_symbols = build_symbol_order(universe_rows, existing_path=independent_path)
    if args.max_symbols:
        final_symbols = final_symbols[: args.max_symbols]

    independent_rows = read_independent_rows(independent_path)
    bars_by_symbol: dict[str, list[Bar]] = {}
    cache_dir.mkdir(parents=True, exist_ok=True)
    independent_path.parent.mkdir(parents=True, exist_ok=True)
    tracker_path.parent.mkdir(parents=True, exist_ok=True)
    ensure_independent_header(independent_path)
    ensure_tracker_header(tracker_path)

    print(f"target_symbols={len(final_symbols)} existing_rows={len(independent_rows)} batch_size={args.batch_size}")
    next_checkpoint = args.batch_size
    while next_checkpoint <= len(independent_rows):
        if next_checkpoint <= len(final_symbols):
            next_checkpoint += args.batch_size
        else:
            break

    for batch_start in range(0, len(final_symbols), args.batch_size):
        batch_symbols = final_symbols[batch_start : batch_start + args.batch_size]
        batch_number = (batch_start // args.batch_size) + 1
        print(f"batch_start batch={batch_number} symbols={batch_symbols[0]}..{batch_symbols[-1]}")
        for symbol in batch_symbols:
            bars = ensure_bars(
                symbol,
                cache_dir=cache_dir,
                start_date=start_date,
                end_date=end_date,
                retry_count=args.retry_count,
                retry_sleep_seconds=args.retry_sleep_seconds,
            )
            if bars:
                bars_by_symbol[symbol] = bars
            if symbol not in independent_rows:
                universe = universe_by_symbol(universe_rows).get(symbol, {})
                if bars:
                    try:
                        row = analyze_symbol(
                            symbol=symbol,
                            universe=universe,
                            bars=bars,
                            base_usd=base_usd,
                            annual_return=annual_return,
                            data_start=start_date,
                            data_end=end_date,
                        )
                    except Exception as error:
                        row = empty_error_row(symbol, universe, start_date, end_date, error)
                else:
                    row = empty_error_row(symbol, universe, start_date, end_date, RuntimeError("no cached bars"))
                append_independent_row(independent_path, row)
                independent_rows[symbol] = row
            if args.per_symbol_pause:
                time.sleep(args.per_symbol_pause)

        completed = min(batch_start + len(batch_symbols), len(final_symbols))
        while next_checkpoint <= completed:
            checkpoint_symbols = final_symbols[:next_checkpoint]
            checkpoint_bars = {symbol: bars_by_symbol.get(symbol) or load_cached_bars(symbol, cache_dir) for symbol in checkpoint_symbols}
            checkpoint_bars = {symbol: bars for symbol, bars in checkpoint_bars.items() if bars}
            tracker_rows = build_tracker_rows(
                size=next_checkpoint,
                independent_rows=[independent_rows[symbol] for symbol in checkpoint_symbols if symbol in independent_rows],
                symbols=list(checkpoint_bars),
                bars_by_symbol=checkpoint_bars,
                start_date=start_date,
                end_date=end_date,
                starting_cash=starting_cash,
            )
            upsert_tracker_rows(tracker_path, size=next_checkpoint, rows=tracker_rows)
            print(f"checkpoint size={next_checkpoint} tracker_updated=true replay_symbols={len(checkpoint_bars)}")
            next_checkpoint += args.batch_size

        if completed < len(final_symbols):
            print(f"batch_complete completed={completed}/{len(final_symbols)} sleeping_seconds={args.sleep_seconds}")
            time.sleep(args.sleep_seconds)

    final_bars = {symbol: bars_by_symbol.get(symbol) or load_cached_bars(symbol, cache_dir) for symbol in final_symbols}
    final_bars = {symbol: bars for symbol, bars in final_bars.items() if bars}
    final_symbols_with_bars = list(final_bars)
    final_replay_bars = convert_bars_for_replay(final_bars)
    daily_rows = simulate(
        final_symbols_with_bars,
        final_replay_bars,
        start_date=start_date,
        end_date=end_date,
        starting_cash=starting_cash,
    )
    forced_daily_rows = simulate(
        final_symbols_with_bars,
        final_replay_bars,
        start_date=start_date,
        end_date=end_date,
        starting_cash=starting_cash,
        force_green_sales=True,
    )
    write_daily_rows(Path(args.daily_output), daily_rows)
    write_daily_rows(Path(args.forced_daily_output), forced_daily_rows)
    print(f"final_daily_written symbols={len(final_symbols_with_bars)} rows={len(daily_rows)}")
    return 0


def build_symbol_order(universe_rows: list[dict[str, str]], *, existing_path: Path) -> list[str]:
    existing = list(read_independent_rows(existing_path))
    result = list(existing)
    if not result:
        result.extend(SEED_SYMBOLS)
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


def universe_by_symbol(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {normalize_symbol(row.get("symbol", "")): row for row in rows if normalize_symbol(row.get("symbol", ""))}


def ensure_independent_header(path: Path) -> None:
    if path.exists():
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=CSV_FIELDS).writeheader()


def ensure_tracker_header(path: Path) -> None:
    if path.exists():
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=TRACKER_FIELDS).writeheader()


def read_independent_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {normalize_symbol(row.get("symbol", "")): row for row in csv.DictReader(handle) if row.get("symbol")}


def append_independent_row(path: Path, row: dict[str, str]) -> None:
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writerow(row)
        handle.flush()


def cache_path(symbol: str, cache_dir: Path) -> Path:
    safe = symbol.replace(".", "_").replace("/", "_").replace("\\", "_")
    return cache_dir / f"{safe}.json"


def ensure_bars(
    symbol: str,
    *,
    cache_dir: Path,
    start_date: date,
    end_date: date,
    retry_count: int,
    retry_sleep_seconds: int,
) -> list[Bar]:
    cached = load_cached_bars(symbol, cache_dir)
    if cached:
        return cached
    last_error: Exception | None = None
    for attempt in range(1, retry_count + 1):
        try:
            bars = fetch_yahoo_daily_bars(symbol, start_date=start_date, end_date=end_date)
            write_cached_bars(symbol, cache_dir, bars)
            return bars
        except Exception as error:
            last_error = error
            print(f"fetch_error symbol={symbol} attempt={attempt}/{retry_count} error={error}")
            if attempt < retry_count:
                time.sleep(retry_sleep_seconds)
    write_error_cache(symbol, cache_dir, str(last_error) if last_error else "unknown error")
    return []


def load_cached_bars(symbol: str, cache_dir: Path) -> list[Bar]:
    path = cache_path(symbol, cache_dir)
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


def write_cached_bars(symbol: str, cache_dir: Path, bars: list[Bar]) -> None:
    payload = {
        "symbol": symbol,
        "status": "ok",
        "bars": [
            {
                "date": bar.day.isoformat(),
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
            }
            for bar in bars
        ],
    }
    cache_path(symbol, cache_dir).write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def write_error_cache(symbol: str, cache_dir: Path, error: str) -> None:
    payload = {"symbol": symbol, "status": "error", "error": error}
    cache_path(symbol, cache_dir).write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def build_tracker_rows(
    *,
    size: int,
    independent_rows: list[dict[str, str]],
    symbols: list[str],
    bars_by_symbol: dict[str, list[Bar]],
    start_date: date,
    end_date: date,
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

    replay_bars = convert_bars_for_replay(bars_by_symbol)
    replay_rows = simulate(symbols, replay_bars, start_date=start_date, end_date=end_date, starting_cash=starting_cash)
    forced_rows = simulate(
        symbols,
        replay_bars,
        start_date=start_date,
        end_date=end_date,
        starting_cash=starting_cash,
        force_green_sales=True,
    )
    deposit_metrics = summarize_replay(replay_rows, starting_cash=starting_cash)
    forced_metrics = summarize_replay(forced_rows, starting_cash=starting_cash)

    return [
        independent_tracker_row(
            size=size,
            view="independent_hold",
            symbol_count=len(ok_rows),
            hit_count=len(hit_rows),
            no_hit_count=len(no_hit_rows),
            invested=independent_invested,
            value=independent_hold_value,
            profit=independent_hold_profit,
            notes="Single-stock independent test; no shared cash constraint",
        ),
        independent_tracker_row(
            size=size,
            view="independent_sell10_reinvest",
            symbol_count=len(ok_rows),
            hit_count=len(hit_rows),
            no_hit_count=len(no_hit_rows),
            invested=independent_invested,
            value=independent_sell_value,
            profit=independent_sell_profit,
            notes="Single-stock independent test; sells at first modeled 10% then reinvests at 20% annualized",
        ),
        replay_tracker_row(size=size, view="replay_deposit_only", metrics=deposit_metrics, notes="Shared-cash replay; DD shortfalls covered by deposits"),
        replay_tracker_row(size=size, view="replay_forced_green", metrics=forced_metrics, notes="Shared-cash replay; green positions sold before deposits"),
    ]


def convert_bars_for_replay(bars_by_symbol: dict[str, list[Bar]]) -> dict[str, list[ReplayBar]]:
    return {
        symbol: [
            ReplayBar(
                day=bar.day,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
            )
            for bar in bars
        ]
        for symbol, bars in bars_by_symbol.items()
    }


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
    size: int,
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
        "universe_size": str(size),
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


def replay_tracker_row(*, size: int, view: str, metrics: dict[str, Decimal | int], notes: str) -> dict[str, str]:
    return {
        "universe_size": str(size),
        "strategy_view": view,
        "symbol_count": str(size),
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


def upsert_tracker_rows(path: Path, *, size: int, rows: list[dict[str, str]]) -> None:
    existing: list[dict[str, str]] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            existing = list(csv.DictReader(handle))
    kept = [row for row in existing if row.get("universe_size") != str(size)]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRACKER_FIELDS)
        writer.writeheader()
        writer.writerows(kept)
        writer.writerows(rows)


def write_daily_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DAILY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def decimal(value: str | None) -> Decimal:
    if not value:
        return Decimal("0")
    return Decimal(value)


def percentage(value: Decimal) -> Decimal:
    return value * Decimal("100")


def money(value: Decimal | int) -> str:
    if isinstance(value, int):
        return str(value)
    return f"{value:.4f}"


if __name__ == "__main__":
    raise SystemExit(main())
