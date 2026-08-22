from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = (
    ROOT
    / "docs"
    / "audit-grade"
    / "runbooks"
    / "WP-04_SECONDARY_SOURCE_OUTAGE.md"
)


class Wp04SecondarySourceRunbookTests(unittest.TestCase):
    def test_outage_runbook_preserves_configurable_reconciliation_contract(self):
        source = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("wp04-secondary-source-configurable-v1", source)
        self.assertIn("secondary_source_status", source)
        self.assertIn("SECONDARY_SOURCE_UNAVAILABLE_OPTIONAL", source)
        self.assertIn("WP04_REQUIRE_SECONDARY_SOURCE=false", source)
        self.assertIn("--require-secondary-source", source)
        self.assertIn("CANONICAL_SINGLE_SOURCE", source)
        self.assertIn("no intenta eludir", source)
        self.assertIn("no ejecuta JavaScript", source)
        self.assertIn("no resuelve CAPTCHA", source)


if __name__ == "__main__":
    unittest.main()
