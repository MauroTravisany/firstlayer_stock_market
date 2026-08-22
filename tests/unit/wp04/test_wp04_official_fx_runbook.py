from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = ROOT / "docs" / "audit-grade" / "runbooks" / "WP-04_OFFICIAL_FX_SOURCE.md"

class Wp04OfficialFxRunbookTests(unittest.TestCase):
    def test_runbook_locks_official_source_and_conservative_availability(self):
        source = RUNBOOK.read_text(encoding="utf-8")
        for marker in ("F073.TCO.PRE.Z.D", "BCCH_API_TOKEN", "wp04-bcch-observed-dollar-v1", "bcch-previous-banking-day-1730-america-santiago-v1", "OFFICIAL_PUBLISHED_RATE", "MAX_INVALID_ROWS_PER_SERIES", "MIN_VALID_ROW_RATIO", "44 invalid", "Forty-three", "DIAGNOSTIC_ONLY"):
            self.assertIn(marker, source)
        self.assertIn("does not fabricate", source)
        self.assertIn("merge", source.lower())

if __name__ == "__main__": unittest.main()
