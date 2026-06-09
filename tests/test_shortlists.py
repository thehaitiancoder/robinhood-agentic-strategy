from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentic_strategy.shortlists import (
    build_return_candidates,
    render_shortlist,
    top_buy_candidates,
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
            )

            self.assertIn("# Top 10 Buy Candidates", buy_path.read_text())
            self.assertIn("# Top 10 Sell Candidates", sell_path.read_text())


if __name__ == "__main__":
    unittest.main()
