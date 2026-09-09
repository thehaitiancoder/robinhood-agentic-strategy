from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from agentic_strategy.afterhours_scan import (
    SplitAdjustment,
    apply_known_dd_blocker_cache,
    report_to_json,
    scan_afterhours,
    write_fractional_dd_leftovers,
)
from agentic_strategy.symbol_policy import SymbolPolicy


class AfterHoursScanTest(unittest.TestCase):
    def test_finds_whole_share_dd_and_fractional_leftover(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "NMRA",
                        "quantity": "18.539301",
                        "shares_available_for_sells": "18.539301",
                        "average_buy_price": "0.98",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {
                        "symbol": "NMRA",
                        "bid": "0.85",
                        "ask": "0.92",
                        "last_trade": "0.9178",
                        "last_non_reg": "0.90",
                    }
                ],
            },
            orders_payload={
                "orders": [
                    _order("NMRA", "buy", "0.561797", "1.78"),
                    _order("NMRA", "buy", "16.853910", "0.9547"),
                    _order("NMRA", "buy", "1.123594", "0.9649"),
                ]
            },
        )

        self.assertEqual(len(report.whole_share_dd), 1)
        candidate = report.whole_share_dd[0]
        self.assertEqual(candidate.symbol, "NMRA")
        self.assertEqual(str(candidate.due_lots), "6")
        self.assertEqual(str(candidate.due_qty), "16.853910")
        self.assertEqual(str(candidate.integer_qty), "16")
        self.assertEqual(str(candidate.decimal_left), "0.853910")
        self.assertEqual(str(candidate.suggested_limit), "0.9200")
        self.assertEqual(candidate.ladder_profile, "standard")

    def test_under5_base_only_position_uses_20_pct_ladder(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "BASE",
                        "quantity": "2.000000",
                        "shares_available_for_sells": "2.000000",
                        "average_buy_price": "0.50",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {
                        "symbol": "BASE",
                        "bid": "0.38",
                        "ask": "0.39",
                        "last_trade": "0.39",
                    }
                ],
            },
            orders_payload={"orders": [_order("BASE", "buy", "2.000000", "0.50")]},
        )

        self.assertEqual(len(report.exact_share_dd), 1)
        self.assertEqual(len(report.whole_share_dd), 1)
        candidate = report.whole_share_dd[0]
        self.assertEqual(candidate.ladder_profile, "under5_20")
        self.assertEqual(candidate.due_lots, "2")
        self.assertEqual(str(candidate.deepest_trigger), "0.4000")
        self.assertEqual(str(candidate.due_qty), "4.000000")

    def test_split_adjustment_resolves_quantity_mismatch_and_finds_due_lots(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "ABTC",
                        "quantity": "0.066667",
                        "shares_available_for_sells": "0.066667",
                        "average_buy_price": "10.20",
                        "type": "long",
                    }
                ],
                "quotes": [{"symbol": "ABTC", "bid": "6.60", "ask": "6.61", "last_trade": "6.6005"}],
            },
            orders_payload={"orders": [_order("ABTC", "buy", "1.000000", "0.68")]},
            split_adjustments={
                "ABTC": SplitAdjustment(
                    symbol="ABTC",
                    effective_date="2026-07-07",
                    split_ratio="1:15",
                    pre_split_base_qty=Decimal("1.000000"),
                    pre_split_base_price=Decimal("0.680000"),
                    adjusted_base_qty=Decimal("0.066667"),
                    adjusted_base_price=Decimal("10.200000"),
                    ladder_profile="standard",
                )
            },
        )

        self.assertEqual(report.incomplete, [])
        self.assertEqual(len(report.exact_share_dd), 1)
        candidate = report.exact_share_dd[0]
        self.assertEqual(candidate.symbol, "ABTC")
        self.assertEqual(candidate.ladder_profile, "standard")
        self.assertEqual(candidate.completed_lot, 1)
        self.assertEqual(candidate.due_lots, "2,3,4,5")
        self.assertEqual(str(candidate.base_shares), "0.066667")
        self.assertEqual(str(candidate.base_price), "10.200000")
        self.assertEqual(str(candidate.due_qty), "2.000010")
        self.assertEqual(str(candidate.integer_qty), "2")
        self.assertEqual(str(candidate.deepest_trigger), "6.69222000000000")

    def test_split_adjustment_keeps_post_split_buys_unadjusted(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "ABTC",
                        "quantity": "2.066677",
                        "shares_available_for_sells": "2.066677",
                        "average_buy_price": "6.744000",
                        "type": "long",
                    }
                ],
                "quotes": [{"symbol": "ABTC", "bid": "6.60", "ask": "6.61", "last_trade": "6.6005"}],
            },
            orders_payload={
                "orders": [
                    _order("ABTC", "buy", "1.000000", "0.68", filled_at="2026-06-30T13:30:00Z"),
                    _order("ABTC", "buy", "2.000010", "6.629", filled_at="2026-07-07T18:45:04Z"),
                ]
            },
            split_adjustments={
                "ABTC": SplitAdjustment(
                    symbol="ABTC",
                    effective_date="2026-07-07",
                    split_ratio="1:15",
                    pre_split_base_qty=Decimal("1.000000"),
                    pre_split_base_price=Decimal("0.680000"),
                    adjusted_base_qty=Decimal("0.066667"),
                    adjusted_base_price=Decimal("10.200000"),
                    ladder_profile="standard",
                )
            },
        )

        self.assertEqual(report.incomplete, [])
        self.assertEqual(report.exact_share_dd, [])
        self.assertEqual(len(report.dd_watch), 1)
        watch = report.dd_watch[0]
        self.assertEqual(watch.symbol, "ABTC")
        self.assertEqual(watch.completed_lot, 5)
        self.assertEqual(watch.next_lot, 6)
        self.assertEqual(str(watch.next_trigger), "5.3537760000000000")
        self.assertEqual(str(watch.remaining_lot_shares), "2.133344")

    def test_under5_base_only_position_waits_past_old_10_pct_trigger(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "WAIT",
                        "quantity": "2.000000",
                        "shares_available_for_sells": "2.000000",
                        "average_buy_price": "0.50",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {
                        "symbol": "WAIT",
                        "bid": "0.44",
                        "ask": "0.44",
                        "last_trade": "0.44",
                    }
                ],
            },
            orders_payload={"orders": [_order("WAIT", "buy", "2.000000", "0.50")]},
        )

        self.assertEqual(report.exact_share_dd, [])
        self.assertEqual(report.whole_share_dd, [])
        self.assertEqual(report.fractional_dd, [])
        self.assertEqual(len(report.dd_watch), 1)
        watch = report.dd_watch[0]
        self.assertEqual(watch.symbol, "WAIT")
        self.assertEqual(watch.ladder_profile, "under5_20")
        self.assertEqual(watch.next_lot, 2)
        self.assertEqual(str(watch.next_trigger), "0.4000")
        self.assertEqual(str(watch.trigger_gap_pct), "10.0")

    def test_under5_multi_lot_position_keeps_standard_ladder(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "OLD",
                        "quantity": "0.750000",
                        "shares_available_for_sells": "0.750000",
                        "average_buy_price": "3.733333",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {
                        "symbol": "OLD",
                        "bid": "3.20",
                        "ask": "3.20",
                        "last_trade": "3.20",
                    }
                ],
            },
            orders_payload={
                "orders": [
                    _order("OLD", "buy", "0.250000", "4.00"),
                    _order("OLD", "buy", "0.500000", "3.60"),
                ]
            },
        )

        self.assertEqual(len(report.exact_share_dd), 1)
        self.assertEqual(len(report.whole_share_dd), 1)
        candidate = report.whole_share_dd[0]
        self.assertEqual(candidate.ladder_profile, "standard")
        self.assertEqual(candidate.ladder_profile_provenance, "legacy_multi_lot_at_under5_20_adoption")
        self.assertEqual(candidate.due_lots, "3")
        self.assertEqual(str(candidate.deepest_trigger), "3.240000")

    def test_under5_cycle_stays_on_20_pct_ladder_after_lot_two(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "AXG",
                        "quantity": "0.852270",
                        "shares_available_for_sells": "0.852270",
                        "average_buy_price": "3.0458",
                        "type": "long",
                    }
                ],
                "quotes": [{"symbol": "AXG", "bid": "2.81", "ask": "2.82", "last_trade": "2.82"}],
            },
            orders_payload={
                "orders": [
                    _order(
                        "AXG",
                        "buy",
                        "0.284090",
                        "3.52",
                        filled_at="2026-08-03T13:30:00Z",
                        order_id="axg-base",
                    ),
                    _order(
                        "AXG",
                        "buy",
                        "0.568180",
                        "2.8087",
                        filled_at="2026-08-04T13:30:00Z",
                        order_id="axg-lot-2",
                    ),
                ]
            },
        )

        self.assertEqual(report.exact_share_dd, [])
        self.assertEqual(len(report.dd_watch), 1)
        watch = report.dd_watch[0]
        self.assertEqual(watch.ladder_profile, "under5_20")
        self.assertEqual(watch.ladder_profile_provenance, "ownership_cycle_entry_after_under5_20_adoption")
        self.assertEqual(watch.base_order_id, "axg-base")
        self.assertEqual(watch.next_lot, 3)
        self.assertEqual(watch.next_trigger, Decimal("2.2528"))

    def test_premature_under5_fill_advances_progress_without_rebuy(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "AXG",
                        "quantity": "1.988630",
                        "shares_available_for_sells": "1.988630",
                        "average_buy_price": "2.9167",
                        "type": "long",
                    }
                ],
                "quotes": [{"symbol": "AXG", "bid": "2.81", "ask": "2.82", "last_trade": "2.82"}],
            },
            orders_payload={
                "orders": [
                    _order(
                        "AXG",
                        "buy",
                        "0.284090",
                        "3.52",
                        filled_at="2026-08-03T13:30:00Z",
                        order_id="axg-base",
                    ),
                    _order(
                        "AXG",
                        "buy",
                        "0.568180",
                        "2.8087",
                        filled_at="2026-08-04T13:30:00Z",
                        order_id="axg-lot-2",
                    ),
                    _order(
                        "AXG",
                        "buy",
                        "1.136360",
                        "2.8199",
                        filled_at="2026-08-05T13:30:00Z",
                        order_id="axg-premature-lot-3",
                    ),
                ]
            },
        )

        self.assertEqual(report.exact_share_dd, [])
        watch = report.dd_watch[0]
        self.assertEqual(watch.completed_lot, 3)
        self.assertEqual(watch.next_lot, 4)
        self.assertEqual(watch.next_trigger, Decimal("1.80224"))

    def test_full_sell_and_reopen_starts_new_under5_cycle(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "REOPEN",
                        "quantity": "0.750000",
                        "shares_available_for_sells": "0.750000",
                        "average_buy_price": "3.466667",
                        "type": "long",
                    }
                ],
                "quotes": [{"symbol": "REOPEN", "bid": "3.00", "ask": "3.00", "last_trade": "3.00"}],
            },
            orders_payload={
                "orders": [
                    _order(
                        "REOPEN",
                        "buy",
                        "0.250000",
                        "4.00",
                        filled_at="2026-06-15T13:30:00Z",
                        order_id="old-base",
                    ),
                    _order(
                        "REOPEN",
                        "buy",
                        "0.500000",
                        "3.60",
                        filled_at="2026-06-16T13:30:00Z",
                        order_id="old-lot-2",
                    ),
                    _order(
                        "REOPEN",
                        "sell",
                        "0.750000",
                        "4.50",
                        filled_at="2026-06-20T13:30:00Z",
                        order_id="old-close",
                    ),
                    _order(
                        "REOPEN",
                        "buy",
                        "0.250000",
                        "4.00",
                        filled_at="2026-07-01T13:30:00Z",
                        order_id="new-base",
                    ),
                    _order(
                        "REOPEN",
                        "buy",
                        "0.500000",
                        "3.20",
                        filled_at="2026-07-02T13:30:00Z",
                        order_id="new-lot-2",
                    ),
                ]
            },
        )

        self.assertEqual(report.exact_share_dd, [])
        watch = report.dd_watch[0]
        self.assertEqual(watch.base_order_id, "new-base")
        self.assertEqual(watch.ladder_profile, "under5_20")
        self.assertEqual(watch.next_lot, 3)
        self.assertEqual(watch.next_trigger, Decimal("2.5600"))

    def test_unresolved_profile_provenance_blocks_dd_output(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "UNKNOWN",
                        "quantity": "0.250000",
                        "shares_available_for_sells": "0.250000",
                        "average_buy_price": "4.00",
                        "type": "long",
                    }
                ],
                "quotes": [{"symbol": "UNKNOWN", "bid": "3.00", "ask": "3.00", "last_trade": "3.00"}],
            },
            orders_payload={
                "orders": [
                    _order(
                        "UNKNOWN",
                        "buy",
                        "0.250000",
                        "4.00",
                        filled_at="",
                        order_id="unknown-base",
                    )
                ]
            },
        )

        self.assertEqual(report.exact_share_dd, [])
        self.assertEqual(report.dd_watch, [])
        self.assertEqual(len(report.ladder_profile_provenance_unresolved), 1)
        payload = report_to_json(report)
        self.assertEqual(payload["dd_scan_blockers"], ["ladder_profile_provenance_unresolved"])
        self.assertEqual(
            payload["ladder_profile_blocker_message"],
            "DD SCAN BLOCKED: ladder_profile_provenance_unresolved",
        )
        self.assertFalse(payload["dd_shortlist_publishable"])

    def test_split_adjustment_profile_override_wins(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "SPLIT20",
                        "quantity": "0.100000",
                        "shares_available_for_sells": "0.100000",
                        "average_buy_price": "60.00",
                        "type": "long",
                    }
                ],
                "quotes": [{"symbol": "SPLIT20", "bid": "50.00", "ask": "50.00", "last_trade": "50.00"}],
            },
            orders_payload={
                "orders": [
                    _order(
                        "SPLIT20",
                        "buy",
                        "1.000000",
                        "6.00",
                        filled_at="2026-07-01T13:30:00Z",
                        order_id="split20-base",
                    )
                ]
            },
            split_adjustments={
                "SPLIT20": SplitAdjustment(
                    symbol="SPLIT20",
                    effective_date="2026-07-10",
                    split_ratio="1:10",
                    pre_split_base_qty=Decimal("1.000000"),
                    pre_split_base_price=Decimal("6.000000"),
                    adjusted_base_qty=Decimal("0.100000"),
                    adjusted_base_price=Decimal("60.000000"),
                    ladder_profile="under5_20",
                )
            },
        )

        self.assertEqual(report.exact_share_dd, [])
        watch = report.dd_watch[0]
        self.assertEqual(watch.ladder_profile, "under5_20")
        self.assertEqual(watch.ladder_profile_provenance, "split_adjustment:2026-07-10")
        self.assertEqual(watch.next_trigger, Decimal("48.0000000"))

    def test_split_adjustment_does_not_leak_into_post_split_reopen_cycle(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "REOPEN_SPLIT",
                        "quantity": "0.250000",
                        "shares_available_for_sells": "0.250000",
                        "average_buy_price": "4.00",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {"symbol": "REOPEN_SPLIT", "bid": "3.00", "ask": "3.00", "last_trade": "3.00"}
                ],
            },
            orders_payload={
                "orders": [
                    _order(
                        "REOPEN_SPLIT",
                        "buy",
                        "1.000000",
                        "6.00",
                        filled_at="2026-07-01T13:30:00Z",
                        order_id="old-split-base",
                    ),
                    _order(
                        "REOPEN_SPLIT",
                        "sell",
                        "0.100000",
                        "65.00",
                        filled_at="2026-07-11T13:30:00Z",
                        order_id="old-split-close",
                    ),
                    _order(
                        "REOPEN_SPLIT",
                        "buy",
                        "0.250000",
                        "4.00",
                        filled_at="2026-07-12T13:30:00Z",
                        order_id="new-post-split-base",
                    ),
                ]
            },
            split_adjustments={
                "REOPEN_SPLIT": SplitAdjustment(
                    symbol="REOPEN_SPLIT",
                    effective_date="2026-07-10",
                    split_ratio="1:10",
                    pre_split_base_qty=Decimal("1.000000"),
                    pre_split_base_price=Decimal("6.000000"),
                    adjusted_base_qty=Decimal("0.100000"),
                    adjusted_base_price=Decimal("60.000000"),
                    ladder_profile="standard",
                    base_order_id="old-split-base",
                )
            },
        )

        self.assertEqual(report.incomplete, [])
        self.assertEqual(len(report.exact_share_dd), 1)
        candidate = report.exact_share_dd[0]
        self.assertEqual(candidate.base_order_id, "new-post-split-base")
        self.assertEqual(candidate.base_price, Decimal("4.00"))
        self.assertEqual(candidate.base_shares, Decimal("0.250000"))
        self.assertEqual(candidate.ladder_profile, "under5_20")
        self.assertEqual(candidate.due_lots, "2")
        self.assertEqual(candidate.due_qty, Decimal("0.500000"))

    def test_order_spanning_split_effective_date_fails_closed(self) -> None:
        split_order = _order(
            "SPLITSPAN",
            "buy",
            "1.100000",
            "10.909091",
            filled_at="2026-07-10T13:30:00Z",
            order_id="split-span-base",
        )
        split_order["executions"] = [
            {
                "quantity": "1.000000",
                "price": "6.00",
                "timestamp": "2026-07-09T19:59:00Z",
            },
            {
                "quantity": "0.100000",
                "price": "60.00",
                "timestamp": "2026-07-10T13:30:00Z",
            },
        ]
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "SPLITSPAN",
                        "quantity": "0.100000",
                        "shares_available_for_sells": "0.100000",
                        "average_buy_price": "60.00",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {
                        "symbol": "SPLITSPAN",
                        "bid": "50.00",
                        "ask": "50.00",
                        "last_trade": "50.00",
                    }
                ],
            },
            orders_payload={"orders": [split_order]},
            split_adjustments={
                "SPLITSPAN": SplitAdjustment(
                    symbol="SPLITSPAN",
                    effective_date="2026-07-10",
                    split_ratio="1:10",
                    pre_split_base_qty=Decimal("1.000000"),
                    pre_split_base_price=Decimal("6.000000"),
                    adjusted_base_qty=Decimal("0.100000"),
                    adjusted_base_price=Decimal("60.000000"),
                    ladder_profile="standard",
                    base_order_id="split-span-base",
                )
            },
        )

        self.assertEqual(report.exact_share_dd, [])
        self.assertEqual(report.dd_watch, [])
        self.assertEqual(len(report.ladder_profile_provenance_unresolved), 1)
        self.assertEqual(
            report.ladder_profile_provenance_unresolved[0].reason,
            "filled_order_crosses_split_effective_date",
        )

    def test_tiny_full_sell_remainder_resets_ownership_cycle(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "TINY",
                        "quantity": "0.250000",
                        "shares_available_for_sells": "0.250000",
                        "average_buy_price": "4.00",
                        "type": "long",
                    }
                ],
                "quotes": [{"symbol": "TINY", "bid": "3.00", "ask": "3.00", "last_trade": "3.00"}],
            },
            orders_payload={
                "orders": [
                    _order(
                        "TINY",
                        "buy",
                        "0.100000",
                        "10.00",
                        filled_at="2026-07-01T13:30:00Z",
                        order_id="old-base",
                    ),
                    _order(
                        "TINY",
                        "buy",
                        "0.200000",
                        "9.00",
                        filled_at="2026-07-02T13:30:00Z",
                        order_id="old-lot-2",
                    ),
                    _order(
                        "TINY",
                        "sell",
                        "0.299999",
                        "11.00",
                        filled_at="2026-07-03T13:30:00Z",
                        order_id="old-close",
                    ),
                    _order(
                        "TINY",
                        "buy",
                        "0.250000",
                        "4.00",
                        filled_at="2026-07-04T13:30:00Z",
                        order_id="new-base",
                    ),
                ]
            },
        )

        self.assertEqual(report.incomplete, [])
        candidate = report.exact_share_dd[0]
        self.assertEqual(candidate.base_order_id, "new-base")
        self.assertEqual(candidate.base_price, Decimal("4.00"))
        self.assertEqual(candidate.ladder_profile, "under5_20")
        self.assertEqual(candidate.due_qty, Decimal("0.500000"))

    def test_micro_base_position_does_not_skip_next_ladder_lot(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "MICRO",
                        "quantity": "0.000004",
                        "shares_available_for_sells": "0.000004",
                        "average_buy_price": "4.00",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {"symbol": "MICRO", "bid": "3.20", "ask": "3.20", "last_trade": "3.20"}
                ],
            },
            orders_payload={
                "orders": [
                    _order(
                        "MICRO",
                        "buy",
                        "0.000004",
                        "4.00",
                        filled_at="2026-07-01T13:30:00Z",
                        order_id="micro-base",
                    )
                ]
            },
        )

        self.assertEqual(report.incomplete, [])
        self.assertEqual(len(report.exact_share_dd), 1)
        candidate = report.exact_share_dd[0]
        self.assertEqual(candidate.completed_lot, 1)
        self.assertEqual(candidate.partial_next, Decimal("0"))
        self.assertEqual(candidate.due_lots, "2")
        self.assertEqual(candidate.due_qty, Decimal("0.000008"))

    def test_micro_partial_lot_preserves_exact_remaining_quantity(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "MICROPART",
                        "quantity": "0.000007",
                        "shares_available_for_sells": "0.000007",
                        "average_buy_price": "3.657143",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {
                        "symbol": "MICROPART",
                        "bid": "3.20",
                        "ask": "3.20",
                        "last_trade": "3.20",
                    }
                ],
            },
            orders_payload={
                "orders": [
                    _order(
                        "MICROPART",
                        "buy",
                        "0.000004",
                        "4.00",
                        filled_at="2026-07-01T13:30:00Z",
                        order_id="micro-part-base",
                    ),
                    _order(
                        "MICROPART",
                        "buy",
                        "0.000003",
                        "3.20",
                        filled_at="2026-07-02T13:30:00Z",
                        order_id="micro-partial-lot-2",
                    ),
                ]
            },
        )

        self.assertEqual(report.incomplete, [])
        self.assertEqual(len(report.exact_share_dd), 1)
        candidate = report.exact_share_dd[0]
        self.assertEqual(candidate.completed_lot, 1)
        self.assertEqual(candidate.partial_next, Decimal("0.000003"))
        self.assertEqual(candidate.due_lots, "2")
        self.assertEqual(candidate.due_qty, Decimal("0.000005"))

    def test_weighted_execution_price_wins_over_limit_price(self) -> None:
        base_order = _order(
            "PRICE",
            "buy",
            "0.204082",
            "4.90",
            filled_at="2026-07-01T13:30:00Z",
            order_id="price-base",
        )
        base_order["average_price"] = ""
        base_order["price"] = "5.10"
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "PRICE",
                        "quantity": "0.204082",
                        "shares_available_for_sells": "0.204082",
                        "average_buy_price": "4.90",
                        "type": "long",
                    }
                ],
                "quotes": [{"symbol": "PRICE", "bid": "4.20", "ask": "4.20", "last_trade": "4.20"}],
            },
            orders_payload={"orders": [base_order]},
        )

        self.assertEqual(report.exact_share_dd, [])
        watch = report.dd_watch[0]
        self.assertEqual(watch.base_price, Decimal("4.90"))
        self.assertEqual(watch.ladder_profile, "under5_20")
        self.assertEqual(watch.next_trigger, Decimal("3.920"))

    def test_bare_limit_price_without_fill_price_fails_closed(self) -> None:
        base_order = _order(
            "NOFILLPRICE",
            "buy",
            "0.200000",
            "4.90",
            filled_at="2026-07-01T13:30:00Z",
            order_id="no-fill-price-base",
        )
        base_order["average_price"] = ""
        base_order["price"] = "5.10"
        base_order["executions"] = []
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "NOFILLPRICE",
                        "quantity": "0.200000",
                        "shares_available_for_sells": "0.200000",
                        "average_buy_price": "4.90",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {"symbol": "NOFILLPRICE", "bid": "4.20", "ask": "4.20", "last_trade": "4.20"}
                ],
            },
            orders_payload={"orders": [base_order]},
        )

        self.assertEqual(report.exact_share_dd, [])
        self.assertEqual(len(report.ladder_profile_provenance_unresolved), 1)
        self.assertEqual(
            report.ladder_profile_provenance_unresolved[0].reason,
            "filled_buy_order_price_missing_or_invalid",
        )

    def test_execution_time_wins_over_pre_adoption_creation_time(self) -> None:
        post_adoption_lot = _order(
            "BOUNDARY",
            "buy",
            "0.500000",
            "3.20",
            filled_at="2026-06-24T09:30:00Z",
            order_id="boundary-lot-2",
        )
        post_adoption_lot["last_transaction_at"] = ""
        post_adoption_lot["created_at"] = "2026-06-24T09:00:00Z"
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "BOUNDARY",
                        "quantity": "0.750000",
                        "shares_available_for_sells": "0.750000",
                        "average_buy_price": "3.466667",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {"symbol": "BOUNDARY", "bid": "3.00", "ask": "3.00", "last_trade": "3.00"}
                ],
            },
            orders_payload={
                "orders": [
                    _order(
                        "BOUNDARY",
                        "buy",
                        "0.250000",
                        "4.00",
                        filled_at="2026-06-23T13:30:00Z",
                        order_id="boundary-base",
                    ),
                    post_adoption_lot,
                ]
            },
        )

        self.assertEqual(report.exact_share_dd, [])
        watch = report.dd_watch[0]
        self.assertEqual(watch.ladder_profile, "under5_20")
        self.assertEqual(watch.ladder_profile_provenance, "base_only_at_under5_20_adoption")
        self.assertEqual(watch.next_trigger, Decimal("2.5600"))

    def test_order_spanning_profile_adoption_boundary_fails_closed(self) -> None:
        base_order = _order(
            "STRADDLE",
            "buy",
            "0.250000",
            "4.00",
            filled_at="2026-06-24T09:30:00Z",
            order_id="straddle-base",
        )
        base_order["executions"] = [
            {
                "quantity": "0.125000",
                "price": "4.00",
                "timestamp": "2026-06-24T09:00:00Z",
            },
            {
                "quantity": "0.125000",
                "price": "4.00",
                "timestamp": "2026-06-24T09:30:00Z",
            },
        ]
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "STRADDLE",
                        "quantity": "0.250000",
                        "shares_available_for_sells": "0.250000",
                        "average_buy_price": "4.00",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {
                        "symbol": "STRADDLE",
                        "bid": "3.00",
                        "ask": "3.00",
                        "last_trade": "3.00",
                    }
                ],
            },
            orders_payload={"orders": [base_order]},
        )

        self.assertEqual(report.exact_share_dd, [])
        self.assertEqual(report.dd_watch, [])
        self.assertEqual(len(report.ladder_profile_provenance_unresolved), 1)
        self.assertEqual(
            report.ladder_profile_provenance_unresolved[0].reason,
            "filled_buy_order_crosses_under5_20_adoption_boundary",
        )

    def test_creation_time_without_fill_time_fails_closed(self) -> None:
        base_order = _order(
            "CREATEDONLY",
            "buy",
            "0.250000",
            "4.00",
            filled_at="",
            order_id="created-only-base",
        )
        base_order["created_at"] = "2026-07-01T13:00:00Z"
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "CREATEDONLY",
                        "quantity": "0.250000",
                        "shares_available_for_sells": "0.250000",
                        "average_buy_price": "4.00",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {"symbol": "CREATEDONLY", "bid": "3.00", "ask": "3.00", "last_trade": "3.00"}
                ],
            },
            orders_payload={"orders": [base_order]},
        )

        self.assertEqual(report.exact_share_dd, [])
        self.assertEqual(len(report.ladder_profile_provenance_unresolved), 1)
        self.assertEqual(
            report.ladder_profile_provenance_unresolved[0].reason,
            "filled_order_timestamp_missing_or_invalid",
        )

    def test_finds_whole_share_sell_and_fractional_remainder(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "AVAT",
                        "quantity": "2.173911",
                        "shares_available_for_sells": "2.173911",
                        "average_buy_price": "1.26",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {
                        "symbol": "AVAT",
                        "bid": "1.40",
                        "ask": "1.49",
                        "last_trade": "1.17",
                        "last_non_reg": "1.44",
                    }
                ],
            },
            orders_payload={"orders": [_order("AVAT", "buy", "2.173911", "1.26")]},
        )

        self.assertEqual(len(report.whole_share_sells), 1)
        candidate = report.whole_share_sells[0]
        self.assertEqual(candidate.symbol, "AVAT")
        self.assertEqual(str(candidate.whole_qty), "2")
        self.assertEqual(str(candidate.decimal_left), "0.173911")
        self.assertEqual(str(candidate.suggested_limit), "1.40")

    def test_policy_blocked_dd_does_not_require_lot_history(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "LILAP",
                        "quantity": "0.025268",
                        "shares_available_for_sells": "0.025268",
                        "average_buy_price": "25.33",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {
                        "symbol": "LILAP",
                        "bid": "19.61",
                        "ask": "19.87",
                        "last_trade": "19.745",
                    }
                ],
            },
            orders_payload={"orders": []},
            symbol_policies={
                "LILAP": SymbolPolicy(
                    symbol="LILAP",
                    policy="manual_trade_only",
                    allow_open=False,
                    allow_reopen=False,
                    allow_double_down=False,
                    allow_sell=False,
                )
            },
        )

        self.assertEqual(report.no_history, [])
        self.assertEqual(report.incomplete, [])
        self.assertEqual(report.policy_blocked_dd, ["LILAP"])
        self.assertEqual(report.policy_blocked_sell, ["LILAP"])

    def test_sub_one_share_due_dd_is_regular_hours_only_not_leftover(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "FRAC",
                        "quantity": "0.100000",
                        "shares_available_for_sells": "0.100000",
                        "average_buy_price": "10.00",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {
                        "symbol": "FRAC",
                        "bid": "8.80",
                        "ask": "9.00",
                        "last_trade": "9.00",
                    }
                ],
            },
            orders_payload={"orders": [_order("FRAC", "buy", "0.100000", "10.00")]},
        )

        self.assertEqual(len(report.exact_share_dd), 1)
        self.assertEqual(report.whole_share_dd, [])
        self.assertEqual(len(report.regular_hours_only_dd), 1)
        self.assertEqual(report.fractional_dd, report.regular_hours_only_dd)
        candidate = report.regular_hours_only_dd[0]
        self.assertEqual(candidate.symbol, "FRAC")
        self.assertEqual(str(candidate.due_qty), "0.200000")
        self.assertEqual(str(candidate.est_cost), "1.80000000")

    def test_writes_post_integer_dd_leftover_cache_when_called_explicitly(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "LEFT",
                        "quantity": "18.539301",
                        "shares_available_for_sells": "18.539301",
                        "average_buy_price": "0.98",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {
                        "symbol": "LEFT",
                        "bid": "0.85",
                        "ask": "0.92",
                        "last_trade": "0.9178",
                        "last_non_reg": "0.90",
                    }
                ],
            },
            orders_payload={
                "orders": [
                    _order("LEFT", "buy", "0.561797", "1.78"),
                    _order("LEFT", "buy", "16.853910", "0.9547"),
                    _order("LEFT", "buy", "1.123594", "0.9649"),
                ]
            },
        )

        self.assertEqual(len(report.whole_share_dd), 1)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dd-fractional-leftovers.csv"
            write_fractional_dd_leftovers(
                path,
                report.whole_share_dd,
                today=date(2026, 6, 24),
                recorded_at=datetime(2026, 6, 24, 6, 30, tzinfo=timezone(timedelta(hours=-7))),
            )

            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pacific_date"], "2026-06-24")
        self.assertEqual(rows[0]["symbol"], "LEFT")
        self.assertEqual(rows[0]["reason"], "post_integer_execution_decimal_leftover")
        self.assertEqual(rows[0]["integer_qty"], "16")
        self.assertEqual(rows[0]["decimal_left"], "0.853910")

    def test_inve_like_sub_one_share_due_dd_stays_exact_share_candidate(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "INVE",
                        "quantity": "0.257069",
                        "shares_available_for_sells": "0.257069",
                        "average_buy_price": "3.89",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {
                        "symbol": "INVE",
                        "bid": "2.53",
                        "ask": "2.58",
                        "last_trade": "2.54",
                    }
                ],
            },
            orders_payload={"orders": [_order("INVE", "buy", "0.257069", "3.89")]},
        )

        self.assertEqual(len(report.exact_share_dd), 1)
        candidate = report.exact_share_dd[0]
        self.assertEqual(candidate.symbol, "INVE")
        self.assertEqual(candidate.ladder_profile, "under5_20")
        self.assertEqual(candidate.due_lots, "2")
        self.assertEqual(str(candidate.deepest_trigger), "3.1120")
        self.assertEqual(str(candidate.due_qty), "0.514138")
        self.assertEqual(str(candidate.integer_qty), "0")
        self.assertEqual(str(candidate.est_cost), "1.32647604")
        self.assertEqual(report.whole_share_dd, [])
        self.assertEqual(report.regular_hours_only_dd, [candidate])

    def test_known_dd_blocker_cache_suppresses_unchanged_missing_history(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "LILAP",
                        "quantity": "0.025268",
                        "shares_available_for_sells": "0.025268",
                        "average_buy_price": "25.33",
                        "type": "long",
                    }
                ],
                "quotes": [{"symbol": "LILAP", "bid": "19.61", "ask": "19.87", "last_trade": "19.745"}],
            },
            orders_payload={"orders": []},
        )
        uncached = report_to_json(report)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dd-known-blockers.csv"
            first = apply_known_dd_blocker_cache(
                report_to_json(report),
                report,
                path=path,
                source="test",
                recorded_at=datetime(2026, 6, 30, 4, 0, tzinfo=timezone(timedelta(hours=-7))),
            )
            second = apply_known_dd_blocker_cache(
                report_to_json(report),
                report,
                path=path,
                source="test",
                recorded_at=datetime(2026, 6, 30, 4, 30, tzinfo=timezone(timedelta(hours=-7))),
            )

        self.assertFalse(uncached["dd_shortlist_publishable"])
        self.assertEqual(uncached["dd_shortlist_blockers"], ["missing_lot_history"])
        self.assertEqual(first["no_history_count"], 1)
        self.assertEqual(first["new_dd_blocker_count"], 1)
        self.assertEqual(first["suppressed_dd_blocker_count"], 0)
        self.assertEqual(second["raw_no_history_count"], 1)
        self.assertEqual(second["raw_no_history_sample"], ["LILAP"])
        self.assertEqual(second["no_history_count"], 0)
        self.assertFalse(second["dd_shortlist_publishable"])
        self.assertEqual(second["dd_shortlist_blockers"], ["missing_lot_history"])
        self.assertEqual(second["dd_scan_blockers"], [])
        self.assertEqual(second["new_dd_blocker_count"], 0)
        self.assertEqual(second["suppressed_dd_blocker_count"], 1)

    def test_known_provenance_blocker_is_suppressed_from_public_report_only(self) -> None:
        report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "KNOWNPROV",
                        "quantity": "0.250000",
                        "shares_available_for_sells": "0.250000",
                        "average_buy_price": "4.00",
                        "type": "long",
                    }
                ],
                "quotes": [
                    {
                        "symbol": "KNOWNPROV",
                        "bid": "3.00",
                        "ask": "3.00",
                        "last_trade": "3.00",
                    }
                ],
            },
            orders_payload={
                "orders": [
                    _order(
                        "KNOWNPROV",
                        "buy",
                        "0.250000",
                        "4.00",
                        filled_at="",
                        order_id="known-provenance-base",
                    )
                ]
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dd-known-blockers.csv"
            first = apply_known_dd_blocker_cache(
                report_to_json(report),
                report,
                path=path,
                source="test",
                recorded_at=datetime(2026, 8, 6, 4, 0, tzinfo=timezone(timedelta(hours=-7))),
            )
            second = apply_known_dd_blocker_cache(
                report_to_json(report),
                report,
                path=path,
                source="test",
                recorded_at=datetime(2026, 8, 6, 4, 30, tzinfo=timezone(timedelta(hours=-7))),
            )

        self.assertEqual(first["ladder_profile_provenance_unresolved_count"], 1)
        self.assertEqual(first["dd_scan_blockers"], ["ladder_profile_provenance_unresolved"])
        self.assertEqual(second["raw_ladder_profile_provenance_unresolved_count"], 1)
        self.assertEqual(second["ladder_profile_provenance_unresolved_count"], 0)
        self.assertEqual(second["ladder_profile_provenance_unresolved"], [])
        self.assertEqual(second["dd_scan_blockers"], [])
        self.assertEqual(second["ladder_profile_blocker_message"], "")
        self.assertFalse(second["dd_shortlist_publishable"])
        self.assertEqual(
            second["dd_shortlist_blockers"],
            ["ladder_profile_provenance_unresolved"],
        )
        self.assertEqual(second["new_dd_blocker_count"], 0)
        self.assertEqual(second["suppressed_dd_blocker_count"], 1)

    def test_known_dd_blocker_cache_resurfaces_changed_quantity_mismatch(self) -> None:
        first_report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "AIFU",
                        "quantity": "2.500000",
                        "shares_available_for_sells": "2.500000",
                        "average_buy_price": "1.00",
                        "type": "long",
                    }
                ],
                "quotes": [{"symbol": "AIFU", "bid": "0.70", "ask": "0.75", "last_trade": "0.75"}],
            },
            orders_payload={"orders": [_order("AIFU", "buy", "1.000000", "1.00")]},
        )
        changed_report = scan_afterhours(
            positions_payload={
                "positions": [
                    {
                        "symbol": "AIFU",
                        "quantity": "3.000000",
                        "shares_available_for_sells": "3.000000",
                        "average_buy_price": "1.00",
                        "type": "long",
                    }
                ],
                "quotes": [{"symbol": "AIFU", "bid": "0.70", "ask": "0.75", "last_trade": "0.75"}],
            },
            orders_payload={"orders": [_order("AIFU", "buy", "1.000000", "1.00")]},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dd-known-blockers.csv"
            first = apply_known_dd_blocker_cache(
                report_to_json(first_report),
                first_report,
                path=path,
                recorded_at=datetime(2026, 6, 30, 4, 0, tzinfo=timezone(timedelta(hours=-7))),
            )
            changed = apply_known_dd_blocker_cache(
                report_to_json(changed_report),
                changed_report,
                path=path,
                recorded_at=datetime(2026, 6, 30, 5, 0, tzinfo=timezone(timedelta(hours=-7))),
            )
            suppressed = apply_known_dd_blocker_cache(
                report_to_json(changed_report),
                changed_report,
                path=path,
                recorded_at=datetime(2026, 6, 30, 5, 30, tzinfo=timezone(timedelta(hours=-7))),
            )

        self.assertEqual(first["incomplete_count"], 1)
        self.assertEqual(first["new_dd_blocker_count"], 1)
        self.assertEqual(changed["incomplete_count"], 1)
        self.assertEqual(changed["new_dd_blocker_count"], 1)
        self.assertEqual(changed["suppressed_dd_blocker_count"], 0)
        self.assertEqual(suppressed["raw_incomplete_count"], 1)
        self.assertEqual(suppressed["raw_incomplete_sample"][0]["symbol"], "AIFU")
        self.assertEqual(suppressed["incomplete_count"], 0)
        self.assertFalse(suppressed["dd_shortlist_publishable"])
        self.assertEqual(suppressed["dd_shortlist_blockers"], ["quantity_mismatch"])
        self.assertEqual(suppressed["dd_scan_blockers"], [])
        self.assertEqual(suppressed["new_dd_blocker_count"], 0)
        self.assertEqual(suppressed["suppressed_dd_blocker_count"], 1)


def _order(
    symbol: str,
    side: str,
    quantity: str,
    price: str,
    *,
    filled_at: str = "2026-06-15T13:30:00Z",
    order_id: str | None = None,
) -> dict[str, object]:
    return {
        "id": order_id or f"{symbol}-{side}-{quantity}",
        "symbol": symbol,
        "side": side,
        "state": "filled",
        "quantity": quantity,
        "cumulative_quantity": quantity,
        "average_price": price,
        "last_transaction_at": filled_at,
        "executions": [
            {
                "quantity": quantity,
                "price": price,
                "timestamp": filled_at,
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
