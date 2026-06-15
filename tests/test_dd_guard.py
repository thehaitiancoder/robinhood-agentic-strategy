from __future__ import annotations

import unittest
from decimal import Decimal

from agentic_strategy.dd_guard import (
    check_dd_order_after_place,
    check_dd_quote_before_place,
    closed_market_watch_price,
)


class DdGuardTest(unittest.TestCase):
    def test_closed_market_watch_prefers_official_close_over_stale_last_trade(self) -> None:
        price, basis = closed_market_watch_price(
            {
                "quote": {
                    "symbol": "MBAV",
                    "ask_price": "11.00",
                    "last_trade_price": "9.13",
                    "last_non_reg_trade_price": "10.70",
                },
                "close": {"price": "9.75"},
            }
        )

        self.assertEqual(price, Decimal("9.75"))
        self.assertEqual(basis, "official_close")

    def test_pre_place_blocks_when_ask_is_above_dd_trigger(self) -> None:
        result = check_dd_quote_before_place(
            symbol="MBAV",
            next_trigger_price=Decimal("9.729"),
            quote_payload={
                "quote": {
                    "symbol": "MBAV",
                    "ask_price": "11.00",
                    "last_trade_price": "9.13",
                    "last_non_reg_trade_price": "10.70",
                },
                "close": {"price": "9.75"},
            },
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.action, "block")
        self.assertEqual(result.price, Decimal("11.00"))
        self.assertEqual(result.price_basis, "ask_price")

    def test_post_place_cancels_active_order_above_dd_trigger(self) -> None:
        result = check_dd_order_after_place(
            symbol="MBAV",
            next_trigger_price=Decimal("9.729"),
            order_payload={
                "order": {
                    "symbol": "MBAV",
                    "state": "queued",
                    "side": "buy",
                    "price": "10.80",
                }
            },
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.action, "cancel")
        self.assertEqual(result.price, Decimal("10.80"))

    def test_post_place_keeps_active_order_at_or_below_dd_trigger(self) -> None:
        result = check_dd_order_after_place(
            symbol="RDAC",
            next_trigger_price=Decimal("6.48"),
            order_payload={
                "order": {
                    "symbol": "RDAC",
                    "state": "queued",
                    "side": "buy",
                    "price": "6.34",
                }
            },
        )

        self.assertTrue(result.allowed)
        self.assertEqual(result.action, "keep")
        self.assertEqual(result.price, Decimal("6.34"))

    def test_post_place_cancels_active_order_without_returned_price(self) -> None:
        result = check_dd_order_after_place(
            symbol="NPRICE",
            next_trigger_price=Decimal("5.00"),
            order_payload={"order": {"symbol": "NPRICE", "state": "queued", "side": "buy"}},
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.action, "cancel")
        self.assertIsNone(result.price)


if __name__ == "__main__":
    unittest.main()
