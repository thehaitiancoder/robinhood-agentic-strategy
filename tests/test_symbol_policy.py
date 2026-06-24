from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentic_strategy.symbol_policy import (
    SymbolPolicy,
    is_double_down_allowed,
    is_open_allowed,
    is_reopen_allowed,
    is_sell_allowed,
    read_symbol_policy_csv,
    write_symbol_policy_csv,
)


class SymbolPolicyTest(unittest.TestCase):
    def test_missing_policy_defaults_to_allowed(self) -> None:
        self.assertTrue(is_open_allowed("AAPL", {}))
        self.assertTrue(is_reopen_allowed("AAPL", {}))

    def test_round_trips_policy_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "symbol-policy.csv"
            write_symbol_policy_csv(
                path,
                [
                    SymbolPolicy(
                        symbol="FLAT",
                        policy="no_reopen",
                        allow_open=False,
                        allow_reopen=False,
                        reason="valid_months=6 avg_monthly_range_pct=9.5 below 10",
                    )
                ],
            )

            policies = read_symbol_policy_csv(path)

        self.assertIn("FLAT", policies)
        self.assertFalse(is_open_allowed("flat", policies))
        self.assertFalse(is_reopen_allowed("FLAT", policies))
        self.assertTrue(policies["FLAT"].allow_double_down)
        self.assertTrue(policies["FLAT"].allow_sell)
        self.assertTrue(is_double_down_allowed("FLAT", policies))
        self.assertTrue(is_sell_allowed("FLAT", policies))


if __name__ == "__main__":
    unittest.main()
