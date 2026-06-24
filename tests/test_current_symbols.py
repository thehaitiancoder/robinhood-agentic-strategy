from __future__ import annotations

import unittest

from agentic_strategy.current_symbols import (
    build_current_symbols,
    render_close_summary,
    select_open_symbols,
)
from agentic_strategy.symbol_policy import SymbolPolicy
from agentic_strategy.universe import UniverseRecord


class CurrentSymbolsTest(unittest.TestCase):
    def test_builds_broker_owned_and_active_order_exclusion_sets(self) -> None:
        state = build_current_symbols(
            account_key="Agentic",
            generated_at="2026-06-09T20:00:00Z",
            portfolio_payload={
                "data": {
                    "total_value": "1000.00",
                    "cash": "900.00",
                    "buying_power": {"buying_power": "900.00"},
                }
            },
            positions_payload={
                "data": {
                    "positions": [
                        {"symbol": "AMD", "quantity": "0.003968", "type": "fractional"},
                        {"symbol": "AAPL", "quantity": "0", "type": "empty"},
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
                            "state": "confirmed",
                            "dollar_based_amount": {"amount": "1.00"},
                        },
                        {
                            "id": "order-tsla",
                            "symbol": "TSLA",
                            "side": "sell",
                            "type": "market",
                            "state": "queued",
                        },
                        {
                            "id": "order-msft",
                            "symbol": "MSFT",
                            "side": "buy",
                            "type": "market",
                            "state": "filled",
                        },
                    ]
                }
            },
        )

        self.assertEqual(state["owned_symbols"], ["AMD"])
        self.assertEqual(state["active_buy_order_symbols"], ["AAPL"])
        self.assertEqual(state["active_sell_order_symbols"], ["TSLA"])
        self.assertEqual(state["blocked_open_symbols"], ["AAPL", "AMD", "TSLA"])
        self.assertEqual(state["counts"]["active_orders"], 2)

    def test_reads_portfolio_from_helper_wrapper_shape(self) -> None:
        state = build_current_symbols(
            account_key="Agentic",
            generated_at="2026-06-23T17:00:00Z",
            portfolio_payload={
                "generated_at": "2026-06-24T00:03:02Z",
                "portfolio": {
                    "total_value": "5819.9162087087",
                    "cash": "389.21",
                    "buying_power": {"buying_power": "233.6800"},
                },
            },
            positions_payload={"positions": []},
            orders_payload={"orders": []},
        )

        self.assertEqual(state["portfolio"]["total_value"], "5819.9162087087")
        self.assertEqual(state["portfolio"]["cash"], "389.21")
        self.assertEqual(state["portfolio"]["buying_power"], "233.68")

    def test_select_open_symbols_uses_broker_state_not_ledger(self) -> None:
        current_symbols = {
            "blocked_open_symbols": ["AAPL", "AMD", "TSLA"],
        }
        universe = [
            UniverseRecord(symbol="AAPL", active=True, tradable=True, fractional_eligible=True),
            UniverseRecord(symbol="AMD", active=True, tradable=True, fractional_eligible=True),
            UniverseRecord(symbol="MSFT", active=True, tradable=True, fractional_eligible=True),
            UniverseRecord(symbol="NOFRAC", active=True, tradable=True, fractional_eligible=False),
            UniverseRecord(symbol="NVDA", active=True, tradable=True, fractional_eligible=True),
            UniverseRecord(symbol="OLD", active=False, tradable=True, fractional_eligible=True),
            UniverseRecord(symbol="TSLA", active=True, tradable=True, fractional_eligible=True),
        ]

        self.assertEqual(
            select_open_symbols(universe, current_symbols, limit=2),
            ["MSFT", "NVDA"],
        )

    def test_select_open_symbols_applies_symbol_policy(self) -> None:
        current_symbols = {"blocked_open_symbols": []}
        universe = [
            UniverseRecord(symbol="AAA", active=True, tradable=True, fractional_eligible=True),
            UniverseRecord(symbol="BBB", active=True, tradable=True, fractional_eligible=True),
            UniverseRecord(symbol="CCC", active=True, tradable=True, fractional_eligible=True),
        ]
        policies = {
            "BBB": SymbolPolicy(
                symbol="BBB",
                policy="no_new_open",
                allow_open=False,
                allow_reopen=False,
            )
        }

        self.assertEqual(
            select_open_symbols(universe, current_symbols, limit=3, symbol_policies=policies),
            ["AAA", "CCC"],
        )

    def test_close_summary_labels_snapshot_as_post_market_cache(self) -> None:
        summary = render_close_summary(
            {
                "generated_at": "2026-06-09T20:00:00Z",
                "account_key": "Agentic",
                "portfolio": {
                    "total_value": "1000",
                    "cash": "900",
                    "buying_power": "900",
                },
                "counts": {"owned_symbols": 1},
                "owned_symbols": ["AMD"],
                "active_buy_order_symbols": [],
                "active_sell_order_symbols": [],
                "open_candidates": ["MSFT"],
            }
        )

        self.assertIn("post-market broker snapshot", summary)
        self.assertIn("Refresh Robinhood before market-hours trading", summary)
        self.assertIn("MSFT", summary)


if __name__ == "__main__":
    unittest.main()
