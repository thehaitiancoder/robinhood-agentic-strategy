from __future__ import annotations

import unittest

from agentic_strategy.afterhours_scan import scan_afterhours


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
