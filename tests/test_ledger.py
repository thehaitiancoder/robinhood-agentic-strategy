from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from agentic_strategy.ledger import (
    append_ledger_events,
    new_ledger_event,
    order_events_from_payload,
    review_events_from_payload,
)


class LedgerTest(unittest.TestCase):
    def test_records_review_payload_and_preserves_disclosure(self) -> None:
        events = review_events_from_payload(
            {
                "data": {
                    "symbol": "CPT",
                    "side": "buy",
                    "type": "market",
                    "dollar_amount": "1.000000",
                    "order_checks": {},
                    "quote_data": {
                        "symbol": "CPT",
                        "last_trade_price": "113.000000",
                        "venue_last_trade_time": "2026-06-08T19:59:57Z",
                    },
                    "market_data_disclosure": "Bid $109.47 - Ask $116.78 - Last $112.97.",
                }
            },
            account_key="Agentic",
            payload_ref="data/private/run/review.json",
        )

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["event_type"], "review")
        self.assertEqual(event["symbol"], "CPT")
        self.assertEqual(event["dollar_amount"], "1")
        self.assertEqual(event["alerts"], "{}")
        self.assertEqual(event["market_data_disclosure"], "Bid $109.47 - Ask $116.78 - Last $112.97.")

    def test_imports_order_snapshot_fill_summary_and_cancel(self) -> None:
        events = order_events_from_payload(
            {
                "data": {
                    "orders": [
                        {
                            "id": "order-1",
                            "symbol": "CPT",
                            "side": "buy",
                            "type": "market",
                            "state": "filled",
                            "quantity": "0.008850",
                            "cumulative_quantity": "0.008850",
                            "price": "112.970000",
                            "average_price": "112.970000",
                            "fees": "0.000000",
                            "dollar_based_amount": {"amount": "1.000000"},
                            "time_in_force": "gfd",
                            "market_hours": "regular_hours",
                            "placed_agent": "agentic",
                            "created_at": "2026-06-09T05:30:15Z",
                            "last_transaction_at": "2026-06-09T14:30:00Z",
                            "executions": [],
                        },
                        {
                            "id": "order-2",
                            "symbol": "MSFT",
                            "side": "buy",
                            "type": "market",
                            "state": "cancelled",
                            "quantity": "0.002000",
                            "cumulative_quantity": "0.000000",
                            "price": "500.000000",
                            "dollar_based_amount": {"amount": "1.000000"},
                            "time_in_force": "gfd",
                            "market_hours": "regular_hours",
                            "placed_agent": "agentic",
                            "created_at": "2026-06-09T05:00:00Z",
                            "last_transaction_at": "2026-06-09T05:10:00Z",
                            "executions": [],
                        },
                    ]
                }
            },
            account_key="Agentic",
            payload_ref="orders.json",
        )

        event_types = [event["event_type"] for event in events]
        self.assertEqual(event_types, ["order", "fill", "cancel"])
        fill = events[1]
        self.assertEqual(fill["order_id"], "order-1")
        self.assertEqual(fill["quantity"], "0.00885")
        self.assertEqual(fill["average_price"], "112.97")

    def test_append_skips_duplicate_import_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_path = Path(tmpdir) / "order-ledger.csv"
            event = new_ledger_event(
                event_type="order",
                symbol="CPT",
                order_id="order-1",
                raw_event_key="order:order-1:queued",
            )

            first = append_ledger_events(ledger_path, [event])
            second = append_ledger_events(ledger_path, [event])

            self.assertEqual(first.appended, 1)
            self.assertEqual(first.duplicates, 0)
            self.assertEqual(second.appended, 0)
            self.assertEqual(second.duplicates, 1)

            rows = _read_csv(ledger_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["raw_event_key"], "order:order-1:queued")

    def test_append_skips_semantically_duplicate_order_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger_path = Path(tmpdir) / "order-ledger.csv"
            manual = new_ledger_event(
                event_type="order",
                symbol="CPT",
                order_id="order-1",
                order_state="queued",
                cumulative_quantity="0",
                broker_last_transaction_at="2026-06-09T05:30:15Z",
                source="manual_order",
            )
            imported = new_ledger_event(
                event_type="order",
                symbol="CPT",
                order_id="order-1",
                order_state="queued",
                cumulative_quantity="0",
                broker_last_transaction_at="2026-06-09T05:30:15Z",
                source="broker_order",
                raw_event_key="order:order-1:queued:broker",
            )

            first = append_ledger_events(ledger_path, [manual])
            second = append_ledger_events(ledger_path, [imported])

            self.assertEqual(first.appended, 1)
            self.assertEqual(second.appended, 0)
            self.assertEqual(second.duplicates, 1)
            self.assertEqual(len(_read_csv(ledger_path)), 1)

    def test_records_skip_reason(self) -> None:
        event = new_ledger_event(
            account_key="Agentic",
            event_type="skip",
            symbol="AAPL",
            reason="existing queued order for symbol",
            source="manual_skip",
        )

        self.assertEqual(event["event_type"], "skip")
        self.assertEqual(event["symbol"], "AAPL")
        self.assertEqual(event["reason"], "existing queued order for symbol")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
