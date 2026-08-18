from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = (
    ROOT
    / "docs"
    / "audit-grade"
    / "runbooks"
    / "WP-04_YAHOO_MOVING_WINDOW_RETRY.md"
)


class Wp04ProviderWindowRunbookTests(unittest.TestCase):
    def test_retry_runbook_uses_checksum_bound_windowed_planner(self):
        source = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("wp04-yahoo-provider-window-v1", source)
        self.assertIn("tools/wp04_shadow_backfill_windowed.py", source)
        self.assertIn("--intraday-lookback-days 45", source)
        self.assertIn("--hourly-lookback-days 365", source)
        self.assertIn("provider_window_checksum", source)
        self.assertIn("--expected-plan-checksum", source)
        self.assertNotIn("INTRADAY_START_DATE=2026-06-16", source)


if __name__ == "__main__":
    unittest.main()
