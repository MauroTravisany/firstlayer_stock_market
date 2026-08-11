import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "cloud-functions" / "financial_data" / "custom_function" / "point_in_time.py"
spec = importlib.util.spec_from_file_location("wp03_point_in_time", MODULE_PATH)
pit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pit)


class PointInTimeFinancialTests(unittest.TestCase):
    def _row(self, **overrides):
        values = dict(
            ticker="AAPL",
            cik="320193",
            form_type="10-Q",
            accession_number="0000320193-26-000050",
            filing_date="2026-05-02",
            source_published_at="2026-05-02T13:30:00Z",
            period_end_date="2026-03-31",
            fiscal_year=2026,
            fiscal_quarter=1,
            currency="USD",
            facts={"revenue": 120.0, "net_income": 30.0},
            source_url="https://www.sec.gov/Archives/example",
        )
        values.update(overrides)
        return pit.build_statement_revision(**values)

    def test_filing_is_invisible_before_publication(self):
        row = self._row()
        self.assertIsNone(pit.select_as_of([row], "2026-05-01T23:59:59Z"))

    def test_filing_is_visible_from_publication_timestamp(self):
        row = self._row()
        self.assertEqual(row["revision_id"], pit.select_as_of([row], "2026-05-02T13:30:00Z")["revision_id"])

    def test_missing_verifiable_availability_is_not_backtest_eligible(self):
        row = self._row(source_published_at=None)
        self.assertFalse(row["backtest_eligible"])
        self.assertEqual("MISSING_VERIFIABLE_AVAILABILITY", row["eligibility_reason"])
        self.assertIsNone(pit.select_as_of([row], "2030-01-01T00:00:00Z"))

    def test_restatement_does_not_rewrite_earlier_snapshot(self):
        original = self._row(accession_number="original", source_published_at="2026-05-02T13:30:00Z", facts={"revenue": 100.0})
        amended = self._row(accession_number="amended", form_type="10-Q/A", filing_date="2026-06-10", source_published_at="2026-06-10T15:00:00Z", facts={"revenue": 105.0})
        self.assertNotEqual(original["revision_id"], amended["revision_id"])
        self.assertEqual(original["revision_id"], pit.select_as_of([original, amended], "2026-06-01T00:00:00Z")["revision_id"])
        self.assertEqual(amended["revision_id"], pit.select_as_of([original, amended], "2026-06-10T15:00:00Z")["revision_id"])

    def test_yoy_uses_same_fiscal_quarter(self):
        rows = [
            {"fiscal_year": 2025, "fiscal_quarter": 1, "revenue": 100.0},
            {"fiscal_year": 2025, "fiscal_quarter": 2, "revenue": 900.0},
            {"fiscal_year": 2026, "fiscal_quarter": 1, "revenue": 120.0},
        ]
        enriched = pit.compute_quarterly_yoy(rows, "revenue")
        q1_2026 = next(row for row in enriched if row["fiscal_year"] == 2026)
        self.assertAlmostEqual(0.20, q1_2026["revenue_yoy"])

    def test_revision_id_is_deterministic_for_same_evidence(self):
        first = self._row()
        second = self._row()
        self.assertEqual(first["revision_id"], second["revision_id"])


if __name__ == "__main__":
    unittest.main()
