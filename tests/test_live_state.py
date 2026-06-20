from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from agentic_strategy.live_state import render_live_state


class LiveStateTest(unittest.TestCase):
    def test_renders_queued_orders_positions_and_ledger_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_path = Path(tmpdir) / "order-ledger.csv"
            with ledger_path.open("w", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "recorded_at",
                        "event_type",
                        "symbol",
                        "side",
                        "order_type",
                        "dollar_amount",
                        "reason",
                        "payload_ref",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "recorded_at": "2026-06-09T05:30:00Z",
                        "event_type": "order",
                        "symbol": "CPT",
                    }
                )
                writer.writerow(
                    {
                        "recorded_at": "2026-06-09T05:31:00Z",
                        "event_type": "skip",
                        "symbol": "AAPL",
                    }
                )
                writer.writerow(
                    {
                        "recorded_at": "2026-06-09T05:32:00Z",
                        "event_type": "review",
                        "symbol": "GM",
                        "side": "buy",
                        "order_type": "market",
                        "dollar_amount": "1",
                    }
                )
                writer.writerow(
                    {
                        "recorded_at": "2026-06-09T05:33:00Z",
                        "event_type": "order",
                        "symbol": "GM",
                        "side": "buy",
                        "order_type": "market",
                        "dollar_amount": "1",
                    }
                )
                writer.writerow(
                    {
                        "recorded_at": "2026-06-09T05:34:00Z",
                        "event_type": "review",
                        "symbol": "CL",
                        "side": "buy",
                        "order_type": "market",
                        "dollar_amount": "1",
                        "reason": "broker review for next-90-open batch",
                        "payload_ref": "data/private/latest/next-90-open-review.md",
                    }
                )
                writer.writerow(
                    {
                        "recorded_at": "2026-06-09T05:35:00Z",
                        "event_type": "review",
                        "symbol": "F",
                        "side": "buy",
                        "order_type": "market",
                        "dollar_amount": "1",
                        "reason": "broker review for next-90-open batch",
                        "payload_ref": "data/private/latest/next-90-open-review.md",
                    }
                )

            markdown = render_live_state(
                portfolio_payload={
                    "data": {
                        "total_value": "1000",
                        "cash": "1000",
                        "buying_power": {"buying_power": "998.0000"},
                    }
                },
                positions_payload={
                    "data": {
                        "positions": [
                            {"symbol": "AAPL", "quantity": "0.000000", "type": "empty"},
                        ]
                    }
                },
                orders_payload={
                    "data": {
                        "orders": [
                            {
                                "id": "order-aapl",
                                "symbol": "AAPL",
                                "side": "buy",
                                "type": "market",
                                "state": "queued",
                                "quantity": "0.003330",
                                "cumulative_quantity": "0.000000",
                                "dollar_based_amount": {"amount": "1.000000"},
                                "created_at": "2026-06-09T00:33:36Z",
                            },
                            {
                                "id": "order-cpt",
                                "symbol": "CPT",
                                "side": "buy",
                                "type": "market",
                                "state": "queued",
                                "quantity": "0.008850",
                                "cumulative_quantity": "0.000000",
                                "dollar_based_amount": {"amount": "1.000000"},
                                "created_at": "2026-06-09T05:30:15Z",
                            },
                            {
                                "id": "order-cl",
                                "symbol": "CL",
                                "side": "buy",
                                "type": "market",
                                "state": "confirmed",
                                "quantity": "0.000000",
                                "cumulative_quantity": "0.000000",
                                "dollar_based_amount": {"amount": "1.000000"},
                                "created_at": "2026-06-09T13:05:40Z",
                            },
                        ]
                    }
                },
                ledger_path=ledger_path,
                generated_at="2026-06-09T05:40:00Z",
            )

            self.assertIn("## Queued Orders (2)", markdown)
            self.assertIn("| AAPL | buy | market | queued | $1 | 0.00333 | 0 |", markdown)
            self.assertIn("| CPT | buy | market | queued | $1 | 0.00885 | 0 |", markdown)
            self.assertIn("## Active Non-Queued Orders (1)", markdown)
            self.assertIn("| CL | buy | market | confirmed | $1 | 0 | 0 |", markdown)
            self.assertIn("## Reviewed Opens Pending Confirmation (1)", markdown)
            self.assertIn("| F | buy | market | $1 | 2026-06-09T05:35:00Z |", markdown)
            self.assertNotIn("| CL | buy | market | $1 | 2026-06-09T05:34:00Z |", markdown)
            self.assertNotIn("| GM | buy | market | $1 | 2026-06-09T05:32:00Z |", markdown)
            self.assertIn("No open equity positions.", markdown)
            self.assertIn("- Total rows: 6", markdown)
            self.assertIn("- order: 2", markdown)
            self.assertIn("- review: 3", markdown)
            self.assertIn("- skip: 1", markdown)


if __name__ == "__main__":
    unittest.main()
