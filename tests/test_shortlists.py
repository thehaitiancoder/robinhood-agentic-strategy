from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentic_strategy.shortlists import (
    build_return_candidates,
    render_dd_shortlist,
    render_shortlist,
    top_buy_candidates,
    top_dd_candidates,
    top_sell_candidates,
    write_shortlists,
)


class ShortlistsTest(unittest.TestCase):
    def test_ranks_buy_by_worst_ask_side_return_and_sell_by_best_bid_side_return(self) -> None:
        candidates = build_return_candidates(
            positions_payload={
                "data": {
                    "positions": [
                        {"symbol": "DOWN", "quantity": "1", "average_buy_price": "10"},
                        {"symbol": "UP", "quantity": "1", "average_buy_price": "10"},
                        {"symbol": "FLAT", "quantity": "1", "average_buy_price": "10"},
                    ]
                }
            },
            quotes_payload={
                "data": {
                    "results": [
                        {"quote": {"symbol": "DOWN", "bid_price": "7.90", "ask_price": "8.00"}},
                        {"quote": {"symbol": "UP", "bid_price": "12.00", "ask_price": "12.10"}},
                        {"quote": {"symbol": "FLAT", "bid_price": "10.00", "ask_price": "10.10"}},
                    ]
                }
            },
        )

        self.assertEqual([item.symbol for item in top_buy_candidates(candidates)], ["DOWN", "FLAT", "UP"])
        self.assertEqual([item.symbol for item in top_sell_candidates(candidates)], ["UP", "FLAT", "DOWN"])

    def test_closed_market_buy_ranking_uses_last_price(self) -> None:
        candidates = build_return_candidates(
            positions_payload={
                "data": {
                    "positions": [
                        {"symbol": "ASKDOWN", "quantity": "1", "average_buy_price": "10"},
                        {"symbol": "LASTDOWN", "quantity": "1", "average_buy_price": "10"},
                    ]
                }
            },
            quotes_payload={
                "data": {
                    "results": [
                        {
                            "quote": {
                                "symbol": "ASKDOWN",
                                "ask_price": "8.00",
                                "last_trade_price": "11.00",
                            }
                        },
                        {
                            "quote": {
                                "symbol": "LASTDOWN",
                                "ask_price": "9.00",
                                "last_trade_price": "7.00",
                            }
                        },
                    ]
                }
            },
        )

        self.assertEqual(
            [item.symbol for item in top_buy_candidates(candidates, market_closed=False)],
            ["ASKDOWN", "LASTDOWN"],
        )
        self.assertEqual(
            [item.symbol for item in top_buy_candidates(candidates, market_closed=True)],
            ["LASTDOWN", "ASKDOWN"],
        )

    def test_closed_market_sell_ranking_uses_close_not_stale_bid(self) -> None:
        candidates = build_return_candidates(
            positions_payload={
                "data": {
                    "positions": [
                        {"symbol": "STALEBID", "quantity": "1", "average_buy_price": "7.77"},
                        {"symbol": "REALUP", "quantity": "1", "average_buy_price": "10"},
                    ]
                }
            },
            quotes_payload={
                "data": {
                    "results": [
                        {
                            "quote": {
                                "symbol": "STALEBID",
                                "bid_price": "9.61",
                                "ask_price": "7.40",
                                "last_trade_price": "7.21",
                                "last_non_reg_trade_price": "7.21",
                            },
                            "close": {"price": "7.21"},
                        },
                        {
                            "quote": {
                                "symbol": "REALUP",
                                "bid_price": "11.00",
                                "ask_price": "11.10",
                                "last_trade_price": "10.90",
                            },
                            "close": {"price": "10.90"},
                        },
                    ]
                }
            },
        )

        self.assertEqual(
            [item.symbol for item in top_sell_candidates(candidates, market_closed=False)],
            ["STALEBID", "REALUP"],
        )
        self.assertEqual(
            [item.symbol for item in top_sell_candidates(candidates, market_closed=True)],
            ["REALUP", "STALEBID"],
        )

    def test_renders_speed_hint_and_expected_title(self) -> None:
        candidates = build_return_candidates(
            positions_payload={
                "data": {"positions": [{"symbol": "UP", "quantity": "1", "average_buy_price": "10"}]}
            },
            quotes_payload={"data": {"results": [{"quote": {"symbol": "UP", "bid_price": "11"}}]}},
        )
        markdown = render_shortlist(
            title="Top 10 Sell Candidates",
            generated_at="2026-06-09T17:00:00Z",
            candidates=top_sell_candidates(candidates),
            mode="sell",
        )

        self.assertIn("# Top 10 Sell Candidates", markdown)
        self.assertIn("Use this file as a speed hint only", markdown)
        self.assertIn("| 1 | UP | 10.0000% |", markdown)

    def test_renders_closed_market_buy_basis_and_return(self) -> None:
        candidates = build_return_candidates(
            positions_payload={
                "data": {"positions": [{"symbol": "DOWN", "quantity": "1", "average_buy_price": "10"}]}
            },
            quotes_payload={
                "data": {
                    "results": [
                        {"quote": {"symbol": "DOWN", "ask_price": "11", "last_trade_price": "8"}}
                    ]
                }
            },
        )
        markdown = render_shortlist(
            title="Top 10 Buy Candidates",
            generated_at="2026-06-09T20:00:00Z",
            candidates=top_buy_candidates(candidates, market_closed=True),
            mode="buy",
            market_closed=True,
        )

        self.assertIn("official close/last because regular market is closed", markdown)
        self.assertIn("| 1 | DOWN | -20.0000% |", markdown)

    def test_closed_market_buy_return_prefers_official_close_over_stale_last_trade(self) -> None:
        candidates = build_return_candidates(
            positions_payload={
                "data": {"positions": [{"symbol": "MBAV", "quantity": "1", "average_buy_price": "10.81"}]}
            },
            quotes_payload={
                "data": {
                    "results": [
                        {
                            "quote": {
                                "symbol": "MBAV",
                                "ask_price": "11.00",
                                "last_trade_price": "9.13",
                                "last_non_reg_trade_price": "10.70",
                            },
                            "close": {"price": "9.75"},
                        }
                    ]
                }
            },
        )
        markdown = render_shortlist(
            title="Top 10 Buy Candidates",
            generated_at="2026-06-15T20:00:00Z",
            candidates=top_buy_candidates(candidates, market_closed=True),
            mode="buy",
            market_closed=True,
        )

        self.assertIn("| 1 | MBAV | -9.8057% |", markdown)
        self.assertIn("| 9.1300 | 10.7000 | 9.7500 |", markdown)

    def test_closed_market_buy_return_falls_back_to_non_regular_before_last_trade(self) -> None:
        candidates = build_return_candidates(
            positions_payload={
                "data": {"positions": [{"symbol": "MBAV", "quantity": "1", "average_buy_price": "10.81"}]}
            },
            quotes_payload={
                "data": {
                    "results": [
                        {
                            "quote": {
                                "symbol": "MBAV",
                                "ask_price": "11.00",
                                "last_trade_price": "9.13",
                                "last_non_reg_trade_price": "10.70",
                            }
                        }
                    ]
                }
            },
        )
        markdown = render_shortlist(
            title="Top 10 Buy Candidates",
            generated_at="2026-06-15T20:00:00Z",
            candidates=top_buy_candidates(candidates, market_closed=True),
            mode="buy",
            market_closed=True,
        )

        self.assertIn("| 1 | MBAV | -1.0176% |", markdown)
        self.assertNotIn("-15.5412%", markdown)

    def test_renders_dd_proximity_buy_shortlist_from_scan(self) -> None:
        candidates = top_dd_candidates(
            {
                "exact_share_dd": [
                    {
                        "symbol": "FRAC",
                        "buy_price": "4.00",
                        "deepest_trigger": "9.00",
                        "due_lots": "2",
                        "due_qty": "0.5",
                        "integer_qty": "0",
                        "decimal_left": "0.5",
                        "active_buy_count": "0",
                    },
                    {
                        "symbol": "DUE",
                        "buy_price": "8.90",
                        "deepest_trigger": "9.00",
                        "due_lots": "2",
                        "due_qty": "2",
                        "integer_qty": "2",
                        "decimal_left": "0",
                        "active_buy_count": "0",
                    }
                ],
                "dd_watch": [
                    {
                        "symbol": "FAR",
                        "buy_price": "12.00",
                        "next_trigger": "9.00",
                        "next_lot": "2",
                        "remaining_lot_shares": "2",
                        "trigger_gap_pct": "33.333333",
                        "active_buy_count": "0",
                    },
                    {
                        "symbol": "CLOSE",
                        "buy_price": "9.10",
                        "next_trigger": "9.00",
                        "next_lot": "2",
                        "remaining_lot_shares": "2",
                        "trigger_gap_pct": "1.111111",
                        "active_buy_count": "0",
                    },
                ],
            }
        )
        markdown = render_dd_shortlist(
            generated_at="2026-06-26T15:00:00Z",
            candidates=candidates,
        )

        self.assertEqual([item.symbol for item in candidates], ["DUE", "CLOSE", "FAR"])
        self.assertNotIn("FRAC", [item.symbol for item in candidates])
        self.assertIn("# Top 10 Buy/DD Candidates", markdown)
        self.assertIn("Gap % is `(buy price - trigger) / trigger`", markdown)
        self.assertIn("Exact due rows with integer quantity below 1 are excluded", markdown)
        self.assertIn("| 1 | DUE | -1.1111% | due | 8.9000 | 9.0000 | 2 | 2 | 2 | 0 | 0 |", markdown)
        self.assertIn("| 2 | CLOSE | 1.1111% | watch | 9.1000 | 9.0000 | 2 | 2 |  |  | 0 |", markdown)

    def test_writes_both_shortlist_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            buy_path = Path(tmpdir) / "top-10-buy-candidates.md"
            sell_path = Path(tmpdir) / "top-10-sell-candidates.md"
            write_shortlists(
                positions_payload={
                    "data": {
                        "positions": [
                            {"symbol": "DOWN", "quantity": "1", "average_buy_price": "10"},
                            {"symbol": "UP", "quantity": "1", "average_buy_price": "10"},
                        ]
                    }
                },
                quotes_payload={
                    "data": {
                        "results": [
                            {"quote": {"symbol": "DOWN", "bid_price": "7.9", "ask_price": "8"}},
                            {"quote": {"symbol": "UP", "bid_price": "12", "ask_price": "12.1"}},
                        ]
                    }
                },
                buy_output=buy_path,
                sell_output=sell_path,
                generated_at="2026-06-09T17:00:00Z",
                market_closed=False,
            )

            self.assertIn("# Top 10 Buy Candidates", buy_path.read_text())
            self.assertIn("# Top 10 Sell Candidates", sell_path.read_text())

    def test_accepts_rh_fast_positions_with_quotes_payload_for_quotes(self) -> None:
        candidates = build_return_candidates(
            positions_payload={
                "positions": [
                    {"symbol": "DOWN", "quantity": "1", "average_buy_price": "10"},
                    {"symbol": "UP", "quantity": "1", "average_buy_price": "10"},
                    {"symbol": "FLAT", "quantity": "1", "average_buy_price": "10"},
                ]
            },
            quotes_payload={
                "quotes": [
                    {
                        "symbol": "DOWN",
                        "bid": 7.9,
                        "ask": 8.0,
                        "last": 8.0,
                        "last_trade": 8.0,
                        "last_non_reg": 0,
                        "close": 8.5,
                    },
                    {
                        "symbol": "UP",
                        "bid": 12.0,
                        "ask": 12.1,
                        "last": 12.1,
                        "last_trade": 12.1,
                        "last_non_reg": 0,
                        "close": 11.9,
                    },
                    {
                        "symbol": "FLAT",
                        "bid": 10.0,
                        "ask": 10.1,
                        "last": 10.1,
                        "last_trade": 10.1,
                        "last_non_reg": 0,
                        "close": 10.0,
                    },
                ]
            },
        )

        self.assertEqual([item.symbol for item in top_sell_candidates(candidates)], ["UP", "FLAT", "DOWN"])
        self.assertEqual([item.symbol for item in top_buy_candidates(candidates)], ["DOWN", "FLAT", "UP"])


if __name__ == "__main__":
    unittest.main()
