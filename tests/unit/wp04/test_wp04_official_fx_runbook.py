from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = ROOT / "docs" / "audit-grade" / "runbooks" / "WP-04_OFFICIAL_USD_CLP_REFERENCE.md"

class Wp04OfficialFxRunbookTests(unittest.TestCase):
    def test_runbook_locks_official_source_and_conservative_availability(self):
        source = RUNBOOK.read_text(encoding="utf-8")
        for marker in ("F073.TCO.PRE.Z.D", "BCCH_API_TOKEN", "wp04-bcch-observed-dollar-v1", "CONSERVATIVE_NEXT_LOCAL_DAY", "RAW_REFERENCE_RATE_VALIDATED", "OFFICIAL_REFERENCE_RATE", "MAX_INVALID_ROWS_PER_SERIES", "MIN_VALID_ROW_RATIO"):
            self.assertIn(marker, source)
        self.assertIn("open = NULL", source)
        self.assertIn("adjusted_close = rate", source)
        self.assertIn("no hacer merge", source.lower())

if __name__ == "__main__": unittest.main()
