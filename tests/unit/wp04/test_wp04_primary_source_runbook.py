from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = (
    ROOT
    / "docs"
    / "audit-grade"
    / "runbooks"
    / "WP-04_PRIMARY_SOURCE_ROW_QUARANTINE.md"
)


class Wp04PrimarySourceRunbookTests(unittest.TestCase):
    def test_runbook_requires_checksum_bound_quarantine_without_repair(self):
        source = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("wp04-primary-row-quarantine-v1", source)
        self.assertIn("primary_source_status", source)
        self.assertIn("primary_source_rejections", source)
        self.assertIn("OUTSIDE_CANONICAL_SESSION", source)
        self.assertIn("OHLC_INCONSISTENT", source)
        self.assertIn("QUARANTINE_WITHOUT_REPAIR", source)
        self.assertIn("0.995", source)
        self.assertIn("MAX_INVALID_ROWS_PER_SERIES = 5", source)
        self.assertNotIn("corregir OHLC", source.lower())


if __name__ == "__main__":
    unittest.main()
