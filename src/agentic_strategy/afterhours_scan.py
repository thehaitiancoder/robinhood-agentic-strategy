from __future__ import annotations

import argparse
import json
from csv import DictReader, DictWriter
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_FLOOR
from pathlib import Path
from typing import Any, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .dd_blockers import DDBlockerEvent, DEFAULT_KNOWN_DD_BLOCKERS_CSV, update_known_dd_blockers
from .ladder import (
    STANDARD_LADDER_PROFILE,
    ladder_profile_for_entry_price,
    next_lot_shares,
    next_trigger_price,
    normalize_ladder_profile,
)
from .symbol_policy import (
    DEFAULT_SYMBOL_POLICY_CSV,
    SymbolPolicy,
    is_double_down_allowed,
    is_sell_allowed,
    read_symbol_policy_csv,
)


ACTIVE_ORDER_STATES = {"new", "queued", "unconfirmed", "confirmed", "partially_filled"}
ZERO = Decimal("0")
DEFAULT_SPLIT_ADJUSTMENTS_CSV = Path("data/split-adjustments.csv")
DEFAULT_DD_FRACTIONAL_LEFTOVERS_CSV = Path("data/runtime/dd-fractional-leftovers.csv")
DD_FRACTIONAL_LEFTOVER_FIELDS = [
    "pacific_date",
    "recorded_at",
    "symbol",
    "reason",
    "due_lots",
    "due_qty",
    "integer_qty",
    "decimal_left",
    "buy_price",
    "buy_price_basis",
    "deepest_trigger",
    "suggested_limit",
    "active_buy_count",
    "active_buy_details",
]

POST_INTEGER_DD_LEFTOVER_REASON = "post_integer_execution_decimal_leftover"
# Broker reconciliation may absorb rounding residue; ladder completion may not absorb a tiny lot.
CYCLE_QUANTITY_TOLERANCE = Decimal("0.000010")
LADDER_PROGRESS_MAX_TOLERANCE = Decimal("0.000001")
LADDER_PROGRESS_RELATIVE_TOLERANCE = Decimal("0.001")
UNDER5_20_ADOPTION_AT = datetime(2026, 6, 24, 9, 9, 9, tzinfo=timezone.utc)


class _DueLot(TypedDict):
    lot_index: int
    trigger: Decimal
    shares: Decimal
    remaining: Decimal


@dataclass(frozen=True)
class SplitAdjustment:
    symbol: str
    effective_date: str
    split_ratio: str
    pre_split_base_qty: Decimal
    pre_split_base_price: Decimal
    adjusted_base_qty: Decimal
    adjusted_base_price: Decimal
    ladder_profile: str
    notes: str = ""
    base_order_id: str = ""

    @property
    def quantity_multiplier(self) -> Decimal:
        post, pre = _split_ratio_parts(self.split_ratio)
        return post / pre

    @property
    def price_multiplier(self) -> Decimal:
        post, pre = _split_ratio_parts(self.split_ratio)
        return pre / post


@dataclass(frozen=True)
class LadderProfileProvenanceIssue:
    symbol: str
    blocker_type: str
    reason: str
    base_order_id: str
    cycle_started_at: str


@dataclass(frozen=True)
class _OwnershipCycle:
    lots: list[dict[str, Any]]
    base_order_id: str
    base_price: Decimal
    base_shares: Decimal
    raw_base_price: Decimal
    raw_base_shares: Decimal
    started_at: datetime
    buy_order_times: tuple[tuple[str, datetime, datetime], ...]


@dataclass(frozen=True)
class _LadderProfileResolution:
    ladder_profile: str
    provenance: str


@dataclass(frozen=True)
class _NormalizedFilledOrder:
    side: str
    quantity: Decimal
    price: Decimal
    raw_quantity: Decimal
    raw_price: Decimal
    order_id: str
    first_filled_at: datetime
    last_filled_at: datetime


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
    base_order_id: str
    ladder_profile: str
    ladder_profile_provenance: str
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
    integer_est_cost: Decimal


@dataclass(frozen=True)
class AfterHoursDoubleDownWatchCandidate:
    symbol: str
    ask: Decimal
    bid: Decimal
    last_non_reg: Decimal
    last_trade: Decimal
    buy_price: Decimal
    buy_price_basis: str
    base_price: Decimal
    base_shares: Decimal
    base_order_id: str
    ladder_profile: str
    ladder_profile_provenance: str
    position_qty: Decimal
    completed_lot: int
    partial_next: Decimal
    next_lot: int
    next_trigger: Decimal
    next_lot_shares: Decimal
    remaining_lot_shares: Decimal
    trigger_gap_pct: Decimal
    active_buy_count: int
    active_buy_details: str


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
    exact_share_dd: list[AfterHoursDoubleDownCandidate]
    whole_share_dd: list[AfterHoursDoubleDownCandidate]
    regular_hours_only_dd: list[AfterHoursDoubleDownCandidate]
    fractional_dd: list[AfterHoursDoubleDownCandidate]
    dd_watch: list[AfterHoursDoubleDownWatchCandidate]
    whole_share_sells: list[AfterHoursSellCandidate]
    not_due_count: int
    policy_blocked_dd: list[str]
    policy_blocked_sell: list[str]
    no_history: list[str]
    incomplete: list[dict[str, str]]
    ladder_profile_provenance_unresolved: list[LadderProfileProvenanceIssue]


def scan_afterhours(
    *,
    positions_payload: dict[str, Any],
    orders_payload: dict[str, Any],
    active_orders_payload: dict[str, Any] | None = None,
    sell_return_threshold: Decimal = Decimal("10"),
    symbol_policies: dict[str, SymbolPolicy] | None = None,
    split_adjustments: dict[str, SplitAdjustment] | None = None,
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
    split_adjustments = split_adjustments or {}

    whole_share_dd: list[AfterHoursDoubleDownCandidate] = []
    exact_share_dd: list[AfterHoursDoubleDownCandidate] = []
    regular_hours_only_dd: list[AfterHoursDoubleDownCandidate] = []
    dd_watch: list[AfterHoursDoubleDownWatchCandidate] = []
    whole_share_sells: list[AfterHoursSellCandidate] = []
    policy_blocked_dd: list[str] = []
    policy_blocked_sell: list[str] = []
    no_history: list[str] = []
    incomplete: list[dict[str, str]] = []
    ladder_profile_provenance_unresolved: list[LadderProfileProvenanceIssue] = []
    not_due_count = 0

    for symbol, position in sorted(position_by_symbol.items()):
        quote = quotes.get(symbol, {})
        if is_sell_allowed(symbol, symbol_policies):
            sell_candidate = _sell_candidate(
                symbol=symbol,
                position=position,
                quote=quote,
                active_sells=active_sells.get(symbol, []),
                sell_return_threshold=sell_return_threshold,
            )
            if sell_candidate is not None:
                whole_share_sells.append(sell_candidate)
        else:
            policy_blocked_sell.append(symbol)

        if not is_double_down_allowed(symbol, symbol_policies):
            policy_blocked_dd.append(symbol)
            continue

        split_adjustment = split_adjustments.get(symbol)
        try:
            ownership_cycle = _reconstruct_current_ownership_cycle(
                orders_by_symbol.get(symbol, []),
                split_adjustment=split_adjustment,
            )
        except ValueError as exc:
            ladder_profile_provenance_unresolved.append(
                LadderProfileProvenanceIssue(
                    symbol=symbol,
                    blocker_type="ladder_profile_provenance_unresolved",
                    reason=str(exc),
                    base_order_id="",
                    cycle_started_at="",
                )
            )
            continue
        if ownership_cycle is None:
            no_history.append(symbol)
            continue

        lots = ownership_cycle.lots
        position_qty = _decimal(position.get("quantity"))
        calculated_qty = sum((lot["qty"] for lot in lots), ZERO)
        if abs(calculated_qty - position_qty) > CYCLE_QUANTITY_TOLERANCE:
            incomplete.append(
                {
                    "symbol": symbol,
                    "position_qty": str(position_qty),
                    "calculated_qty": str(calculated_qty),
                    "split_adjustment": split_adjustment.split_ratio if split_adjustment is not None else "",
                }
            )
            continue

        try:
            cycle_split_adjustment = _split_adjustment_for_cycle(ownership_cycle, split_adjustment)
        except ValueError as exc:
            ladder_profile_provenance_unresolved.append(
                LadderProfileProvenanceIssue(
                    symbol=symbol,
                    blocker_type="ladder_profile_provenance_unresolved",
                    reason=str(exc),
                    base_order_id=ownership_cycle.base_order_id,
                    cycle_started_at=ownership_cycle.started_at.isoformat(),
                )
            )
            continue

        try:
            profile_resolution = _resolve_ladder_profile(
                ownership_cycle,
                cycle_split_adjustment,
            )
        except ValueError as exc:
            ladder_profile_provenance_unresolved.append(
                LadderProfileProvenanceIssue(
                    symbol=symbol,
                    blocker_type="ladder_profile_provenance_unresolved",
                    reason=str(exc),
                    base_order_id=ownership_cycle.base_order_id,
                    cycle_started_at=ownership_cycle.started_at.isoformat(),
                )
            )
            continue
        if profile_resolution is None:
            ladder_profile_provenance_unresolved.append(
                LadderProfileProvenanceIssue(
                    symbol=symbol,
                    blocker_type="ladder_profile_provenance_unresolved",
                    reason="ownership_cycle_cannot_be_classified_at_under5_20_adoption",
                    base_order_id=ownership_cycle.base_order_id,
                    cycle_started_at=ownership_cycle.started_at.isoformat(),
                )
            )
            continue

        base_price = ownership_cycle.base_price
        base_shares = ownership_cycle.base_shares

        dd_candidate = _double_down_candidate(
            symbol=symbol,
            position_qty=position_qty,
            base_price=base_price,
            base_shares=base_shares,
            base_order_id=ownership_cycle.base_order_id,
            ladder_profile=profile_resolution.ladder_profile,
            ladder_profile_provenance=profile_resolution.provenance,
            quote=quote,
            active_buys=active_buys.get(symbol, []),
        )
        if dd_candidate is None:
            watch_candidate = _double_down_watch_candidate(
                symbol=symbol,
                position_qty=position_qty,
                base_price=base_price,
                base_shares=base_shares,
                base_order_id=ownership_cycle.base_order_id,
                ladder_profile=profile_resolution.ladder_profile,
                ladder_profile_provenance=profile_resolution.provenance,
                quote=quote,
                active_buys=active_buys.get(symbol, []),
            )
            if watch_candidate is not None:
                dd_watch.append(watch_candidate)
            not_due_count += 1
            continue
        exact_share_dd.append(dd_candidate)
        if dd_candidate.integer_qty >= Decimal("1"):
            whole_share_dd.append(dd_candidate)
        else:
            regular_hours_only_dd.append(dd_candidate)

    exact_share_dd.sort(key=lambda item: (item.active_buy_count > 0, -item.est_cost, item.symbol))
    whole_share_dd.sort(key=lambda item: (item.active_buy_count > 0, -item.integer_est_cost, item.symbol))
    regular_hours_only_dd.sort(key=lambda item: (-item.due_qty, item.symbol))
    dd_watch.sort(key=lambda item: (item.active_buy_count > 0, item.trigger_gap_pct, item.symbol))
    whole_share_sells.sort(key=lambda item: (item.active_sell_count > 0, -item.return_pct, item.symbol))

    return AfterHoursScanReport(
        checked_positions=len(position_by_symbol),
        exact_share_dd=exact_share_dd,
        whole_share_dd=whole_share_dd,
        regular_hours_only_dd=regular_hours_only_dd,
        fractional_dd=regular_hours_only_dd,
        dd_watch=dd_watch[:100],
        whole_share_sells=whole_share_sells,
        not_due_count=not_due_count,
        policy_blocked_dd=policy_blocked_dd,
        policy_blocked_sell=policy_blocked_sell,
        no_history=no_history,
        incomplete=incomplete,
        ladder_profile_provenance_unresolved=ladder_profile_provenance_unresolved,
    )


def report_to_json(report: AfterHoursScanReport) -> dict[str, Any]:
    return {
        "checked_positions": report.checked_positions,
        "exact_share_dd_count": len(report.exact_share_dd),
        "whole_share_dd_count": len(report.whole_share_dd),
        "regular_hours_only_dd_count": len(report.regular_hours_only_dd),
        "fractional_dd_count": len(report.fractional_dd),
        "dd_watch_count": len(report.dd_watch),
        "whole_share_sell_count": len(report.whole_share_sells),
        "not_due_count": report.not_due_count,
        "policy_blocked_dd_count": len(report.policy_blocked_dd),
        "policy_blocked_sell_count": len(report.policy_blocked_sell),
        "no_history_count": len(report.no_history),
        "incomplete_count": len(report.incomplete),
        "ladder_profile_provenance_unresolved_count": len(report.ladder_profile_provenance_unresolved),
        "dd_shortlist_publishable": not report.ladder_profile_provenance_unresolved,
        "ladder_profile_blocker_message": (
            "DD SCAN BLOCKED: ladder_profile_provenance_unresolved"
            if report.ladder_profile_provenance_unresolved
            else ""
        ),
        "exact_share_dd": [_json_row(item) for item in report.exact_share_dd],
        "whole_share_dd": [_json_row(item) for item in report.whole_share_dd],
        "regular_hours_only_dd": [_json_row(item) for item in report.regular_hours_only_dd],
        "fractional_dd": [_json_row(item) for item in report.fractional_dd],
        "dd_watch": [_json_row(item) for item in report.dd_watch],
        "whole_share_sells": [_json_row(item) for item in report.whole_share_sells],
        "policy_blocked_dd_sample": report.policy_blocked_dd[:25],
        "policy_blocked_sell_sample": report.policy_blocked_sell[:25],
        "no_history_sample": report.no_history[:25],
        "incomplete_sample": report.incomplete[:25],
        "ladder_profile_provenance_unresolved": [
            _json_row(item) for item in report.ladder_profile_provenance_unresolved
        ],
        "dd_scan_blockers": (
            ["ladder_profile_provenance_unresolved"]
            if report.ladder_profile_provenance_unresolved
            else []
        ),
    }


def apply_known_dd_blocker_cache(
    payload: dict[str, Any],
    report: AfterHoursScanReport,
    *,
    path: Path,
    source: str = "",
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    events = _known_dd_blocker_events(report, source=source)
    update = update_known_dd_blockers(path, events, recorded_at=recorded_at or _now_pacific())
    suppressed_keys = {
        (row.get("symbol", ""), row.get("blocker_type", ""))
        for row in update.suppressed
        if row.get("status") == "coverage_blocker"
    }
    raw_no_history = list(report.no_history)
    raw_incomplete = list(report.incomplete)
    raw_provenance = list(report.ladder_profile_provenance_unresolved)
    filtered_no_history = [
        symbol for symbol in raw_no_history if (symbol.upper(), "missing_lot_history") not in suppressed_keys
    ]
    filtered_incomplete = [
        row for row in raw_incomplete if (row.get("symbol", "").upper(), "quantity_mismatch") not in suppressed_keys
    ]
    filtered_provenance = [
        issue
        for issue in raw_provenance
        if (issue.symbol.upper(), issue.blocker_type) not in suppressed_keys
    ]
    payload["raw_no_history_count"] = len(raw_no_history)
    payload["raw_incomplete_count"] = len(raw_incomplete)
    payload["raw_ladder_profile_provenance_unresolved_count"] = len(raw_provenance)
    payload["raw_ladder_profile_provenance_unresolved"] = [
        _json_row(issue) for issue in raw_provenance
    ]
    payload["no_history_count"] = len(filtered_no_history)
    payload["incomplete_count"] = len(filtered_incomplete)
    payload["ladder_profile_provenance_unresolved_count"] = len(filtered_provenance)
    payload["no_history_sample"] = filtered_no_history[:25]
    payload["incomplete_sample"] = filtered_incomplete[:25]
    payload["ladder_profile_provenance_unresolved"] = [
        _json_row(issue) for issue in filtered_provenance
    ]
    payload["dd_shortlist_publishable"] = not raw_provenance
    payload["dd_shortlist_blockers"] = (
        ["ladder_profile_provenance_unresolved"] if raw_provenance else []
    )
    payload["ladder_profile_blocker_message"] = (
        "DD SCAN BLOCKED: ladder_profile_provenance_unresolved"
        if filtered_provenance
        else ""
    )
    payload["dd_scan_blockers"] = (
        ["ladder_profile_provenance_unresolved"] if filtered_provenance else []
    )
    payload["known_dd_blocker_cache"] = str(path)
    payload["known_dd_blocker_count"] = len(update.cache_rows)
    payload["new_dd_blocker_count"] = len(update.reported)
    payload["suppressed_dd_blocker_count"] = len(update.suppressed)
    payload["new_dd_blockers"] = update.reported[:50]
    payload["suppressed_dd_blockers_sample"] = update.suppressed[:50]
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan owned positions for extended-hours whole-share DD and sell candidates."
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
    parser.add_argument(
        "--symbol-policy",
        default=str(DEFAULT_SYMBOL_POLICY_CSV),
        help="Optional symbol policy CSV. Defaults to data/symbol-policy.csv when present.",
    )
    parser.add_argument(
        "--split-adjustments",
        default=str(DEFAULT_SPLIT_ADJUSTMENTS_CSV),
        help=(
            "Optional committed CSV for split-adjusted symbols whose broker live quantity no longer "
            "matches raw order history. Pass an empty string to disable."
        ),
    )
    parser.add_argument(
        "--fractional-dd-cache",
        default="",
        help=(
            "Optional ignored CSV for actual DD decimal leftovers after an integer-share execution. "
            "Due exact-share DDs with integer_qty=0 are not written automatically."
        ),
    )
    parser.add_argument(
        "--known-dd-blockers-cache",
        default=str(DEFAULT_KNOWN_DD_BLOCKERS_CSV),
        help=(
            "Ignored CSV used to suppress unchanged known DD blocker/report-only rows. "
            "Pass an empty string to disable."
        ),
    )
    parser.add_argument(
        "--known-dd-blockers-source",
        default="",
        help="Optional source label recorded in the known DD blockers cache.",
    )
    args = parser.parse_args()

    report = scan_afterhours(
        positions_payload=_read_json(args.positions_json),
        orders_payload=_read_json(args.orders_json),
        active_orders_payload=_read_json(args.active_orders_json) if args.active_orders_json else None,
        sell_return_threshold=Decimal(args.sell_return_pct),
        symbol_policies=read_symbol_policy_csv(args.symbol_policy) if args.symbol_policy else None,
        split_adjustments=read_split_adjustments_csv(args.split_adjustments) if args.split_adjustments else None,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = report_to_json(report)
    if args.known_dd_blockers_cache:
        payload = apply_known_dd_blocker_cache(
            payload,
            report,
            path=Path(args.known_dd_blockers_cache),
            source=args.known_dd_blockers_source,
        )
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in payload if key.endswith("_count") or key == "checked_positions"}))
    return 0


def read_split_adjustments_csv(path: str | Path) -> dict[str, SplitAdjustment]:
    csv_path = Path(path)
    if not csv_path.exists():
        return {}
    adjustments: dict[str, SplitAdjustment] = {}
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in DictReader(handle):
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            adjustments[symbol] = SplitAdjustment(
                symbol=symbol,
                effective_date=str(row.get("effective_date") or "").strip(),
                split_ratio=str(row.get("split_ratio") or "").strip(),
                pre_split_base_qty=_decimal(row.get("pre_split_base_qty")),
                pre_split_base_price=_decimal(row.get("pre_split_base_price")),
                adjusted_base_qty=_decimal(row.get("adjusted_base_qty")),
                adjusted_base_price=_decimal(row.get("adjusted_base_price")),
                ladder_profile=normalize_ladder_profile(row.get("ladder_profile")),
                base_order_id=str(row.get("base_order_id") or "").strip(),
                notes=str(row.get("notes") or "").strip(),
            )
    return adjustments


def _known_dd_blocker_events(report: AfterHoursScanReport, *, source: str = "") -> list[DDBlockerEvent]:
    events: list[DDBlockerEvent] = []
    for symbol in report.no_history:
        events.append(
            DDBlockerEvent(
                symbol=symbol,
                blocker_type="missing_lot_history",
                status="coverage_blocker",
                reason="no_filled_buy_lot_history",
                source=source,
            )
        )
    for row in report.incomplete:
        events.append(
            DDBlockerEvent(
                symbol=row.get("symbol", ""),
                blocker_type="quantity_mismatch",
                status="coverage_blocker",
                reason="live_position_quantity_does_not_match_reconstructed_lots",
                quantity=row.get("position_qty", ""),
                source=source,
                notes=f"calculated_qty={row.get('calculated_qty', '')}",
            )
        )
    for issue in report.ladder_profile_provenance_unresolved:
        events.append(
            DDBlockerEvent(
                symbol=issue.symbol,
                blocker_type=issue.blocker_type,
                status="coverage_blocker",
                reason=issue.reason,
                source=source,
                notes=(
                    f"base_order_id={issue.base_order_id};"
                    f"cycle_started_at={issue.cycle_started_at}"
                ),
            )
        )
    for candidate in report.regular_hours_only_dd:
        events.append(
            DDBlockerEvent(
                symbol=candidate.symbol,
                blocker_type="regular_hours_only_exact_dd",
                status="report_only",
                reason="integer_qty_zero_in_whole_share_lane",
                quantity=str(candidate.position_qty),
                buy_price=str(candidate.buy_price),
                deepest_trigger=str(candidate.deepest_trigger),
                due_qty=str(candidate.due_qty),
                integer_qty=str(candidate.integer_qty),
                active_buy_count=str(candidate.active_buy_count),
                source=source,
                notes=f"due_lots={candidate.due_lots}",
            )
        )
    return events


def write_fractional_dd_leftovers(
    path: Path,
    candidates: list[AfterHoursDoubleDownCandidate],
    *,
    today: date | None = None,
    recorded_at: datetime | None = None,
) -> None:
    if not candidates:
        return
    now = recorded_at or _now_pacific()
    pacific_date = (today or now.date()).isoformat()
    symbols = {candidate.symbol for candidate in candidates}
    rows: list[dict[str, str]] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            rows = [
                row
                for row in DictReader(handle)
                if not (row.get("pacific_date") == pacific_date and row.get("symbol") in symbols)
            ]
    rows.extend(_fractional_leftover_row(candidate, pacific_date=pacific_date, recorded_at=now) for candidate in candidates)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = DictWriter(handle, fieldnames=DD_FRACTIONAL_LEFTOVER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _fractional_leftover_row(
    candidate: AfterHoursDoubleDownCandidate,
    *,
    pacific_date: str,
    recorded_at: datetime,
) -> dict[str, str]:
    return {
        "pacific_date": pacific_date,
        "recorded_at": recorded_at.isoformat(),
        "symbol": candidate.symbol,
        "reason": POST_INTEGER_DD_LEFTOVER_REASON,
        "due_lots": candidate.due_lots,
        "due_qty": str(candidate.due_qty),
        "integer_qty": str(candidate.integer_qty),
        "decimal_left": str(candidate.decimal_left),
        "buy_price": str(candidate.buy_price),
        "buy_price_basis": candidate.buy_price_basis,
        "deepest_trigger": str(candidate.deepest_trigger),
        "suggested_limit": str(candidate.suggested_limit),
        "active_buy_count": str(candidate.active_buy_count),
        "active_buy_details": candidate.active_buy_details,
    }


def _now_pacific() -> datetime:
    try:
        return datetime.now(tz=ZoneInfo("America/Los_Angeles"))
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone()


def _split_effective_date(adjustment: SplitAdjustment) -> date:
    try:
        return date.fromisoformat(adjustment.effective_date)
    except ValueError as exc:
        raise ValueError("split_adjustment_effective_date_invalid") from exc


def _filled_before_split(filled_at: datetime, adjustment: SplitAdjustment) -> bool:
    return filled_at.date() < _split_effective_date(adjustment)


def _split_ratio_parts(split_ratio: str) -> tuple[Decimal, Decimal]:
    raw_post, raw_pre = split_ratio.split(":", 1)
    post = Decimal(raw_post.strip())
    pre = Decimal(raw_pre.strip())
    if post <= ZERO or pre <= ZERO:
        raise ValueError(f"invalid split_ratio: {split_ratio}")
    return post, pre


def _double_down_candidate(
    *,
    symbol: str,
    position_qty: Decimal,
    base_price: Decimal,
    base_shares: Decimal,
    base_order_id: str,
    ladder_profile: str,
    ladder_profile_provenance: str,
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

    if base_price <= ZERO or base_shares <= ZERO:
        return None

    completed_lot, partial_next = _current_ladder_progress(
        position_qty=position_qty,
        base_price=base_price,
        base_shares=base_shares,
        ladder_profile=ladder_profile,
    )
    due_lots = _due_lots(
        start_lot=completed_lot + 1,
        partial_next=partial_next,
        base_price=base_price,
        base_shares=base_shares,
        buy_price=buy_price,
        ladder_profile=ladder_profile,
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
        base_order_id=base_order_id,
        ladder_profile=ladder_profile,
        ladder_profile_provenance=ladder_profile_provenance,
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
        est_cost=due_qty * suggested_limit,
        integer_est_cost=integer_qty * suggested_limit,
    )


def _double_down_watch_candidate(
    *,
    symbol: str,
    position_qty: Decimal,
    base_price: Decimal,
    base_shares: Decimal,
    base_order_id: str,
    ladder_profile: str,
    ladder_profile_provenance: str,
    quote: dict[str, Any],
    active_buys: list[dict[str, Any]],
) -> AfterHoursDoubleDownWatchCandidate | None:
    ask = _decimal(quote.get("ask") or quote.get("ask_price"))
    bid = _decimal(quote.get("bid") or quote.get("bid_price"))
    last_non_reg = _decimal(quote.get("last_non_reg") or quote.get("last_non_reg_trade_price"))
    last_trade = _decimal(quote.get("last_trade") or quote.get("last_trade_price") or quote.get("last"))
    buy_price = ask if ask > ZERO else (last_non_reg or last_trade)
    buy_price_basis = "ask" if ask > ZERO else "after_hours_last_fallback"
    if buy_price <= ZERO:
        return None

    if base_price <= ZERO or base_shares <= ZERO:
        return None

    completed_lot, partial_next = _current_ladder_progress(
        position_qty=position_qty,
        base_price=base_price,
        base_shares=base_shares,
        ladder_profile=ladder_profile,
    )
    next_lot = max(completed_lot + 1, 2)
    next_trigger, shares = _ladder_lot(
        base_price=base_price,
        base_shares=base_shares,
        lot_index=next_lot,
        ladder_profile=ladder_profile,
    )
    if buy_price <= next_trigger:
        return None

    remaining = shares
    if next_lot == completed_lot + 1 and partial_next > ZERO:
        remaining = max(shares - partial_next, ZERO)

    return AfterHoursDoubleDownWatchCandidate(
        symbol=symbol,
        ask=ask,
        bid=bid,
        last_non_reg=last_non_reg,
        last_trade=last_trade,
        buy_price=buy_price,
        buy_price_basis=buy_price_basis,
        base_price=base_price,
        base_shares=base_shares,
        base_order_id=base_order_id,
        ladder_profile=ladder_profile,
        ladder_profile_provenance=ladder_profile_provenance,
        position_qty=position_qty,
        completed_lot=completed_lot,
        partial_next=partial_next,
        next_lot=next_lot,
        next_trigger=next_trigger,
        next_lot_shares=shares,
        remaining_lot_shares=remaining,
        trigger_gap_pct=((buy_price - next_trigger) / next_trigger) * Decimal("100"),
        active_buy_count=len(active_buys),
        active_buy_details=_active_details(active_buys),
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
    ladder_profile: str,
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
            trigger = next_trigger_price(base_price, 2, ladder_profile=ladder_profile)
            shares = next_lot_shares(base_shares)
        else:
            trigger = next_trigger_price(trigger, lot_index, ladder_profile=ladder_profile)
            shares = next_lot_shares(shares)
        progress_tolerance = min(
            LADDER_PROGRESS_MAX_TOLERANCE,
            shares * LADDER_PROGRESS_RELATIVE_TOLERANCE,
        )
        if position_qty + progress_tolerance >= cumulative + shares:
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
    ladder_profile: str,
) -> list[_DueLot]:
    due: list[_DueLot] = []
    trigger = base_price
    shares = base_shares
    for lot_index in range(2, 80):
        if lot_index == 2:
            trigger = next_trigger_price(base_price, 2, ladder_profile=ladder_profile)
            shares = next_lot_shares(base_shares)
        else:
            trigger = next_trigger_price(trigger, lot_index, ladder_profile=ladder_profile)
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


def _ladder_lot(
    *,
    base_price: Decimal,
    base_shares: Decimal,
    lot_index: int,
    ladder_profile: str,
) -> tuple[Decimal, Decimal]:
    if lot_index < 1:
        raise ValueError("lot_index must be positive")
    trigger = base_price
    shares = base_shares
    for next_index in range(2, lot_index + 1):
        trigger = next_trigger_price(trigger, next_index, ladder_profile=ladder_profile)
        shares = next_lot_shares(shares)
    return trigger, shares


def _resolve_ladder_profile(
    cycle: _OwnershipCycle,
    split_adjustment: SplitAdjustment | None,
) -> _LadderProfileResolution | None:
    if split_adjustment is not None:
        return _LadderProfileResolution(
            ladder_profile=normalize_ladder_profile(split_adjustment.ladder_profile),
            provenance=f"split_adjustment:{split_adjustment.effective_date}",
        )

    if any(
        first_filled_at < UNDER5_20_ADOPTION_AT <= last_filled_at
        for _, first_filled_at, last_filled_at in cycle.buy_order_times
    ):
        raise ValueError("filled_buy_order_crosses_under5_20_adoption_boundary")

    if cycle.started_at >= UNDER5_20_ADOPTION_AT:
        return _LadderProfileResolution(
            ladder_profile=ladder_profile_for_entry_price(cycle.base_price),
            provenance="ownership_cycle_entry_after_under5_20_adoption",
        )

    buy_orders_at_adoption = {
        order_id
        for order_id, _, last_filled_at in cycle.buy_order_times
        if last_filled_at <= UNDER5_20_ADOPTION_AT
    }
    if len(buy_orders_at_adoption) == 1:
        return _LadderProfileResolution(
            ladder_profile=ladder_profile_for_entry_price(cycle.base_price),
            provenance="base_only_at_under5_20_adoption",
        )
    if len(buy_orders_at_adoption) > 1:
        return _LadderProfileResolution(
            ladder_profile=STANDARD_LADDER_PROFILE,
            provenance="legacy_multi_lot_at_under5_20_adoption",
        )
    return None


def _split_adjustment_for_cycle(
    cycle: _OwnershipCycle,
    adjustment: SplitAdjustment | None,
) -> SplitAdjustment | None:
    if adjustment is None:
        return None
    if cycle.started_at.date() >= _split_effective_date(adjustment):
        return None
    if adjustment.base_order_id:
        if cycle.base_order_id == adjustment.base_order_id:
            return adjustment
        raise ValueError("split_adjustment_base_order_mismatch")
    if (
        abs(cycle.raw_base_shares - adjustment.pre_split_base_qty) <= CYCLE_QUANTITY_TOLERANCE
        and abs(cycle.raw_base_price - adjustment.pre_split_base_price) <= Decimal("0.0001")
    ):
        return adjustment
    raise ValueError("split_adjustment_base_provenance_unresolved")


def _reconstruct_current_ownership_cycle(
    orders: list[dict[str, Any]],
    *,
    split_adjustment: SplitAdjustment | None = None,
) -> _OwnershipCycle | None:
    normalized_orders = [
        _normalize_filled_order(order, split_adjustment=split_adjustment)
        for order in orders
    ]

    lots: deque[dict[str, Any]] = deque()
    base_order_id = ""
    base_price = ZERO
    base_shares = ZERO
    raw_base_price = ZERO
    raw_base_shares = ZERO
    started_at: datetime | None = None
    buy_order_times: list[tuple[str, datetime, datetime]] = []

    for order in sorted(normalized_orders, key=lambda item: item.first_filled_at):
        if order.quantity <= ZERO:
            continue
        if order.side == "buy":
            if not lots:
                base_order_id = order.order_id
                base_price = order.price
                base_shares = order.quantity
                raw_base_price = order.raw_price
                raw_base_shares = order.raw_quantity
                started_at = order.first_filled_at
                buy_order_times = []
            lots.append(
                {
                    "qty": order.quantity,
                    "price": order.price,
                    "order_id": order.order_id,
                    "time": order.first_filled_at.isoformat(),
                }
            )
            buy_order_times.append(
                (order.order_id, order.first_filled_at, order.last_filled_at)
            )
        elif order.side == "sell":
            left = order.quantity
            while left > CYCLE_QUANTITY_TOLERANCE and lots:
                if lots[0]["qty"] <= left + CYCLE_QUANTITY_TOLERANCE:
                    left = max(left - lots[0]["qty"], ZERO)
                    lots.popleft()
                else:
                    lots[0]["qty"] -= left
                    left = ZERO
            remaining_qty = sum((lot["qty"] for lot in lots), ZERO)
            if not lots or remaining_qty <= CYCLE_QUANTITY_TOLERANCE:
                lots.clear()
                base_order_id = ""
                base_price = ZERO
                base_shares = ZERO
                raw_base_price = ZERO
                raw_base_shares = ZERO
                started_at = None
                buy_order_times = []

    if not lots or started_at is None:
        return None
    return _OwnershipCycle(
        lots=list(lots),
        base_order_id=base_order_id,
        base_price=base_price,
        base_shares=base_shares,
        raw_base_price=raw_base_price,
        raw_base_shares=raw_base_shares,
        started_at=started_at,
        buy_order_times=tuple(buy_order_times),
    )


def _normalize_filled_order(
    order: dict[str, Any],
    *,
    split_adjustment: SplitAdjustment | None,
) -> _NormalizedFilledOrder:
    side = str(order.get("side") or "").lower()
    order_id = str(order.get("id") or "").strip()
    fill_window = _event_datetime_range(order)
    if fill_window is None:
        raise ValueError("filled_order_timestamp_missing_or_invalid")
    first_filled_at, last_filled_at = fill_window
    if side == "buy" and not order_id:
        raise ValueError("filled_buy_order_id_missing")

    raw_quantity = _filled_order_quantity(order)
    raw_price = _filled_order_price(order) if side == "buy" else ZERO
    if side == "buy" and raw_price <= ZERO:
        raise ValueError("filled_buy_order_price_missing_or_invalid")

    quantity = raw_quantity
    price = raw_price
    if split_adjustment is not None:
        first_is_pre_split = _filled_before_split(first_filled_at, split_adjustment)
        last_is_pre_split = _filled_before_split(last_filled_at, split_adjustment)
        if first_is_pre_split != last_is_pre_split:
            raise ValueError("filled_order_crosses_split_effective_date")
        if first_is_pre_split:
            quantity = raw_quantity * split_adjustment.quantity_multiplier
            price = raw_price * split_adjustment.price_multiplier
            if side == "buy" and _is_configured_split_base(
                order_id=order_id,
                raw_quantity=raw_quantity,
                raw_price=raw_price,
                adjustment=split_adjustment,
            ):
                if (
                    split_adjustment.adjusted_base_qty <= ZERO
                    or split_adjustment.adjusted_base_price <= ZERO
                ):
                    raise ValueError("split_adjustment_base_values_invalid")
                quantity = split_adjustment.adjusted_base_qty
                price = split_adjustment.adjusted_base_price

    return _NormalizedFilledOrder(
        side=side,
        quantity=quantity,
        price=price,
        raw_quantity=raw_quantity,
        raw_price=raw_price,
        order_id=order_id,
        first_filled_at=first_filled_at,
        last_filled_at=last_filled_at,
    )


def _is_configured_split_base(
    *,
    order_id: str,
    raw_quantity: Decimal,
    raw_price: Decimal,
    adjustment: SplitAdjustment,
) -> bool:
    if adjustment.base_order_id:
        return order_id == adjustment.base_order_id
    return (
        abs(raw_quantity - adjustment.pre_split_base_qty) <= CYCLE_QUANTITY_TOLERANCE
        and abs(raw_price - adjustment.pre_split_base_price) <= Decimal("0.0001")
    )


def _filled_order_quantity(order: dict[str, Any]) -> Decimal:
    quantity = _decimal(order.get("cumulative_quantity") or order.get("quantity"))
    if quantity > ZERO:
        return quantity
    executions = order.get("executions") or []
    return sum(
        (_decimal(execution.get("quantity")) for execution in executions if isinstance(execution, dict)),
        ZERO,
    )


def _filled_order_price(order: dict[str, Any]) -> Decimal:
    executions = [execution for execution in (order.get("executions") or []) if isinstance(execution, dict)]
    filled_executions = [execution for execution in executions if _decimal(execution.get("quantity")) > ZERO]
    if filled_executions:
        if any(_decimal(execution.get("price")) <= ZERO for execution in filled_executions):
            return ZERO
        total_quantity = sum((_decimal(execution.get("quantity")) for execution in filled_executions), ZERO)
        reported_quantity = _decimal(order.get("cumulative_quantity") or order.get("quantity"))
        if (
            reported_quantity > ZERO
            and abs(total_quantity - reported_quantity) > CYCLE_QUANTITY_TOLERANCE
        ):
            return ZERO
        total_cost = sum(
            (
                _decimal(execution.get("quantity")) * _decimal(execution.get("price"))
                for execution in filled_executions
            ),
            ZERO,
        )
        return total_cost / total_quantity
    return _decimal(order.get("average_price"))


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


def _event_datetime_range(order: dict[str, Any]) -> tuple[datetime, datetime] | None:
    filled_executions = [
        execution
        for execution in (order.get("executions") or [])
        if isinstance(execution, dict) and _decimal(execution.get("quantity")) > ZERO
    ]
    if filled_executions:
        execution_times = [_parse_datetime(execution.get("timestamp")) for execution in filled_executions]
        if all(parsed is not None for parsed in execution_times):
            parsed_times = [parsed for parsed in execution_times if parsed is not None]
            return min(parsed_times), max(parsed_times)
    last_transaction_at = _parse_datetime(order.get("last_transaction_at"))
    if last_transaction_at is None:
        return None
    return last_transaction_at, last_transaction_at


def _parse_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
