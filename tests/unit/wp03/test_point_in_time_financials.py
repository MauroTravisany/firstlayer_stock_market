import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = (
    ROOT
    / "cloud-functions"
    / "financial_data"
    / "custom_function"
    / "point_in_time.py"
)
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
            mapping_version="sec-company-tickers-test-v1",
        )
        values.update(overrides)
        return pit.build_statement_revision(**values)

    def test_filing_is_invisible_before_publication(self):
        row = self._row()
        self.assertIsNone(pit.select_as_of([row], "2026-05-01T23:59:59Z"))

    def test_filing_is_visible_from_publication_timestamp(self):
        row = self._row()
        self.assertEqual(
            row["revision_id"],
            pit.select_as_of([row], "2026-05-02T13:30:00Z")["revision_id"],
        )

    def test_missing_verifiable_availability_is_not_backtest_eligible(self):
        row = self._row(source_published_at=None)
        self.assertFalse(row["backtest_eligible"])
        self.assertEqual(
            "MISSING_VERIFIABLE_AVAILABILITY", row["eligibility_reason"]
        )
        self.assertEqual("UNVERIFIED_AVAILABLE_AT", row["quality_status"])
        self.assertIsNone(pit.select_as_of([row], "2030-01-01T00:00:00Z"))

    def test_quarterly_filing_without_xbrl_quarter_is_not_eligible(self):
        row = self._row(fiscal_quarter=None)
        self.assertFalse(row["backtest_eligible"])
        self.assertEqual(
            "MISSING_VERIFIABLE_FISCAL_PERIOD", row["eligibility_reason"]
        )
        self.assertEqual("UNVERIFIED_FISCAL_PERIOD", row["quality_status"])

    def test_annual_filing_requires_fy_quarter_marker(self):
        invalid = self._row(form_type="10-K", fiscal_quarter=None)
        valid = self._row(form_type="10-K", fiscal_quarter=4)
        self.assertFalse(invalid["backtest_eligible"])
        self.assertTrue(valid["backtest_eligible"])

    def test_filing_without_usable_core_facts_is_not_eligible(self):
        row = self._row(facts={"gross_profit": None, "total_debt": 5.0})
        self.assertFalse(row["backtest_eligible"])
        self.assertEqual(
            "MISSING_USABLE_FINANCIAL_FACTS", row["eligibility_reason"]
        )
        self.assertEqual("NO_USABLE_FINANCIAL_FACTS", row["quality_status"])

    def test_restatement_does_not_rewrite_earlier_snapshot(self):
        original = self._row(
            accession_number="original",
            source_published_at="2026-05-02T13:30:00Z",
            facts={"revenue": 100.0},
        )
        amended = self._row(
            accession_number="amended",
            form_type="10-Q/A",
            filing_date="2026-06-10",
            source_published_at="2026-06-10T15:00:00Z",
            facts={"revenue": 105.0},
        )
        self.assertNotEqual(original["revision_id"], amended["revision_id"])
        self.assertEqual(
            original["revision_id"],
            pit.select_as_of(
                [original, amended], "2026-06-01T00:00:00Z"
            )["revision_id"],
        )
        self.assertEqual(
            amended["revision_id"],
            pit.select_as_of(
                [original, amended], "2026-06-10T15:00:00Z"
            )["revision_id"],
        )

    def test_late_old_period_restatement_does_not_displace_newer_period(self):
        q2 = self._row(
            accession_number="q2",
            period_end_date="2026-06-30",
            fiscal_quarter=2,
            source_published_at="2026-08-01T14:00:00Z",
            facts={"revenue": 140.0},
        )
        q1_amended_late = self._row(
            accession_number="q1-amended",
            form_type="10-Q/A",
            period_end_date="2026-03-31",
            fiscal_quarter=1,
            source_published_at="2026-09-01T14:00:00Z",
            facts={"revenue": 121.0},
        )
        selected = pit.select_as_of(
            [q2, q1_amended_late], "2026-09-02T00:00:00Z"
        )
        self.assertEqual(q2["revision_id"], selected["revision_id"])

    def test_yoy_uses_same_fiscal_quarter_and_latest_revision(self):
        rows = [
            {
                "fiscal_year": 2025,
                "fiscal_quarter": 1,
                "revenue": 100.0,
                "period_end_date": "2025-03-31",
                "available_at": "2025-05-01T00:00:00Z",
                "revision_number": 1,
                "revision_id": "old",
            },
            {
                "fiscal_year": 2025,
                "fiscal_quarter": 1,
                "revenue": 110.0,
                "period_end_date": "2025-03-31",
                "available_at": "2025-06-01T00:00:00Z",
                "revision_number": 2,
                "revision_id": "restated",
            },
            {
                "fiscal_year": 2025,
                "fiscal_quarter": 2,
                "revenue": 900.0,
                "period_end_date": "2025-06-30",
                "available_at": "2025-08-01T00:00:00Z",
                "revision_number": 1,
                "revision_id": "q2",
            },
            {
                "fiscal_year": 2026,
                "fiscal_quarter": 1,
                "revenue": 121.0,
                "period_end_date": "2026-03-31",
                "available_at": "2026-05-01T00:00:00Z",
                "revision_number": 1,
                "revision_id": "current",
            },
        ]
        enriched = pit.compute_quarterly_yoy(rows, "revenue")
        q1_2026 = next(
            row for row in enriched if row["fiscal_year"] == 2026
        )
        self.assertAlmostEqual(0.10, q1_2026["revenue_yoy"])

    def test_revision_id_is_deterministic_for_same_evidence(self):
        first = self._row()
        second = self._row()
        self.assertEqual(first["revision_id"], second["revision_id"])

    def test_mapping_version_is_part_of_revision_identity(self):
        first = self._row(mapping_version="mapping-v1")
        second = self._row(mapping_version="mapping-v2")
        self.assertNotEqual(first["revision_id"], second["revision_id"])


if __name__ == "__main__":
    unittest.main()
