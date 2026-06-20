from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


class WeeklySymbolPolicyRefreshTest(unittest.TestCase):
    def test_node_self_test_passes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["node", "scripts/weekly_symbol_policy_refresh.mjs", "--self-test"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("self-test ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
