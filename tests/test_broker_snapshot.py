from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from agentic_strategy.broker_snapshot import write_broker_snapshot


class BrokerSnapshotTest(unittest.TestCase):
    def test_writes_monitor_inputs_from_robinhood_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "position-state.csv"
            state_path.write_text(
                "symbol,invested_cost,current_lot_index,next_trigger_price,next_lot_shares,ladder_profile\n"
                "msft,100.00,3,47.50,4,under5_20\n"
            )

            files = write_broker_snapshot(
                portfolio_payload={
                    "data": {
                        "total_value": "1000",
                        "cash": "925.50",
                        "buying_power": {"buying_power": "900.0000"},
                    }
                },
                positions_payload={
                    "data": {
                        "positions": [
                            {"symbol": "AAPL", "quantity": "0.000000", "type": "empty"},
                            {
                                "symbol": "MSFT",
                                "quantity": "2.000000",
                                "average_buy_price": "50.000000",
                                "type": "long",
                            },
                        ]
                    }
                },
                quotes_payload={
                    "data": {
                        "results": [
                            {
                                "quote": {
                                    "symbol": "MSFT",
                                    "bid_price": "51.000000",
                                    "ask_price": "51.100000",
                                    "last_trade_price": "50.900000",
                                    "venue_last_trade_time": "2026-06-09T16:00:00Z",
                                    "last_non_reg_trade_price": "51.050000",
                                    "venue_last_non_reg_trade_time": "2026-06-09T20:00:00Z",
                                }
                            }
                        ]
                    }
                },
                tradability_payload={
                    "data": {
                        "results": [
                            {
                                "symbol": "AAPL",
                                "name": "Apple Inc. Common Stock",
                                "state": "active",
                                "tradeable": True,
                                "fractional_tradability": "tradable",
                                "account_type_tradabilities": [
                                    {"account_type": "individual", "account_type_tradability": "tradable"}
                                ],
                            }
                        ]
                    }
                },
                position_state_path=state_path,
                output_dir=Path(tmpdir) / "runtime",
                as_of="2026-06-09",
            )

            portfolio = json.loads(files.portfolio.read_text())
            self.assertEqual(portfolio["total_value"], "1000")
            self.assertEqual(portfolio["buying_power"], "900")
            self.assertEqual(portfolio["cash"], "925.5")

            positions = _read_csv(files.positions)
            self.assertEqual(len(positions), 1)
            self.assertEqual(positions[0]["symbol"], "MSFT")
            self.assertEqual(positions[0]["invested_cost"], "100.00")
            self.assertEqual(positions[0]["current_lot_index"], "3")
            self.assertEqual(positions[0]["next_trigger_price"], "47.50")
            self.assertEqual(positions[0]["ladder_profile"], "under5_20")

            quotes = _read_csv(files.quotes)
            self.assertEqual(quotes[0]["symbol"], "MSFT")
            self.assertEqual(quotes[0]["last_price"], "51.05")
            self.assertEqual(quotes[0]["updated_at"], "2026-06-09T20:00:00Z")

            validations = _read_csv(files.universe_validations)
            self.assertEqual(validations[0]["symbol"], "AAPL")
            self.assertEqual(validations[0]["tradable"], "true")
            self.assertEqual(validations[0]["fractional_eligible"], "true")
            self.assertEqual(validations[0]["updated_at"], "2026-06-09")


def _read_csv(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
