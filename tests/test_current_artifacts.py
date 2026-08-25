from __future__ import annotations

from pathlib import Path
import sys
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import report  # noqa: E402


class CurrentArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / "parsed" / "futures").exists():
            raise unittest.SkipTest("local market-data artifacts are not installed")
        cls.futures, cls.main, cls.sub, cls.index, _ = report.load_all()

    def test_latest_complete_day_has_six_exchanges(self):
        day = report.pick_date(self.futures)
        current = self.futures[self.futures["trade_date"].eq(day)]
        self.assertEqual(set(current["exchange"]), set(report.EX_CN))
        coverage = current.groupby("exchange")["settle"].apply(lambda x: x.notna().mean())
        self.assertTrue(coverage.gt(0.9).all())

    def test_primary_keys_are_unique(self):
        key = ["trade_date", "exchange", "contract"]
        self.assertFalse(self.futures.duplicated(key).any())
        self.assertFalse(self.main.duplicated(["trade_date", "product"]).any())
        self.assertFalse(self.sub.duplicated(["trade_date", "product"]).any())

    def test_report_preparation_has_all_sections(self):
        prepared = report.prepare("20260821")
        self.assertEqual(len(prepared["mt"]), 76)
        self.assertEqual(len(prepared["st"]), 76)
        self.assertGreater(len(prepared["bf"]), 0)


if __name__ == "__main__":
    unittest.main()
