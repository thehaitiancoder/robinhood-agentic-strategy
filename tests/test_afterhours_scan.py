from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from agentic_strategy.afterhours_scan import scan_afterhours, write_fractional_dd_leftovers
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

        self.assertEqual(len(report.whole_share_dd), 1)
        candidate = report.whole_share_dd[0]
        self.assertEqual(candidate.ladder_profile, "under5_20")
        self.assertEqual(candidate.due_lots, "2")
        self.assertEqual(str(candidate.deepest_trigger), "0.4000")
        self.assertEqual(str(candidate.due_qty), "4.000000")

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

        self.assertEqual(report.whole_share_dd, [])
        self.assertEqual(report.fractional_dd, [])

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

        self.assertEqual(len(report.whole_share_dd), 1)
        candidate = report.whole_share_dd[0]
        self.assertEqual(candidate.ladder_profile, "standard")
        self.assertEqual(candidate.due_lots, "3")
        self.assertEqual(str(candidate.deepest_trigger), "3.240000")

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

    def test_writes_fractional_only_dd_leftover_cache(self) -> None:
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

        self.assertEqual(report.whole_share_dd, [])
        self.assertEqual(len(report.fractional_dd), 1)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dd-fractional-leftovers.csv"
            write_fractional_dd_leftovers(
                path,
                report.fractional_dd,
                today=date(2026, 6, 24),
                recorded_at=datetime(2026, 6, 24, 6, 30, tzinfo=timezone(timedelta(hours=-7))),
            )

            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pacific_date"], "2026-06-24")
        self.assertEqual(rows[0]["symbol"], "FRAC")
        self.assertEqual(rows[0]["reason"], "integer_qty_zero_fractional_only")
        self.assertEqual(rows[0]["integer_qty"], "0")
        self.assertEqual(rows[0]["decimal_left"], "0.200000")


def _order(symbol: str, side: str, quantity: str, price: str) -> dict[str, object]:
    return {
        "id": f"{symbol}-{side}-{quantity}",
        "symbol": symbol,
        "side": side,
        "state": "filled",
        "quantity": quantity,
        "cumulative_quantity": quantity,
        "average_price": price,
        "last_transaction_at": "2026-06-15T13:30:00Z",
        "executions": [
            {
                "quantity": quantity,
                "price": price,
                "timestamp": "2026-06-15T13:30:00Z",
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
