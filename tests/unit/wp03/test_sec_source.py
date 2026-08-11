import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
CUSTOM = ROOT / "cloud-functions" / "financial_data" / "custom_function"
PKG = types.ModuleType("custom_function")
PKG.__path__ = [str(CUSTOM)]
sys.modules.setdefault("custom_function", PKG)

pit_spec = importlib.util.spec_from_file_location(
    "custom_function.point_in_time", CUSTOM / "point_in_time.py"
)
pit = importlib.util.module_from_spec(pit_spec)
sys.modules["custom_function.point_in_time"] = pit
pit_spec.loader.exec_module(pit)
sec_spec = importlib.util.spec_from_file_location(
    "custom_function.sec_source", CUSTOM / "sec_source.py"
)
sec = importlib.util.module_from_spec(sec_spec)
sys.modules["custom_function.sec_source"] = sec
sec_spec.loader.exec_module(sec)


class SecSourceTests(unittest.TestCase):
    def submissions(self, acceptance="2026-05-02T13:30:00.000Z"):
        return {
            "filings": {
                "recent": {
                    "accessionNumber": ["0000320193-26-000050"],
                    "form": ["10-Q"],
                    "filingDate": ["2026-05-02"],
                    "acceptanceDateTime": [acceptance],
                    "reportDate": ["2026-03-28"],
                    "primaryDocument": ["aapl-20260328.htm"],
                }
            }
        }

    def companyfacts(self, currency="USD", taxonomy="us-gaap"):
        fact = {
            "accn": "0000320193-26-000050",
            "end": "2026-03-28",
            "start": "2025-12-29",
            "filed": "2026-05-02",
            "fy": 2026,
            "fp": "Q2",
            "frame": "CY2026Q1",
            "val": 120.0,
        }
        revenue_concept = (
            "Revenue"
            if taxonomy == "ifrs-full"
            else "RevenueFromContractWithCustomerExcludingAssessedTax"
        )
        income_concept = (
            "ProfitLoss" if taxonomy == "ifrs-full" else "NetIncomeLoss"
        )
        return {
            "facts": {
                taxonomy: {
                    revenue_concept: {"units": {currency: [fact]}},
                    income_concept: {
                        "units": {currency: [{**fact, "val": 30.0}]}
                    },
                }
            }
        }

    def build(self, submissions=None, companyfacts=None, currency="USD"):
        return sec.build_sec_statement_revisions(
            "AAPL",
            "320193",
            submissions or self.submissions(),
            companyfacts or self.companyfacts(currency=currency),
            reporting_currency=currency,
            mapping_version="mapping-test-v1",
        )

    def test_fiscal_period_comes_from_xbrl_not_calendar_month(self):
        rows = self.build()
        self.assertEqual(1, len(rows))
        self.assertEqual(2, rows[0]["fiscal_quarter"])
        self.assertEqual(2026, rows[0]["fiscal_year"])
        self.assertEqual("mapping-test-v1", rows[0]["mapping_version"])

    def test_missing_acceptance_timestamp_is_not_eligible(self):
        rows = self.build(submissions=self.submissions(acceptance=None))
        self.assertFalse(rows[0]["backtest_eligible"])
        self.assertIsNone(rows[0]["available_at"])

    def test_recent_filing_keeps_verified_acceptance_timestamp(self):
        rows = sec.recent_filings_by_accession(self.submissions())
        self.assertEqual(
            "2026-05-02T13:30:00.000Z",
            rows["0000320193-26-000050"]["source_published_at"],
        )

    def test_supplemental_history_is_normalized_with_recent_filings(self):
        submissions = self.submissions()
        submissions["_supplemental_filings"] = [
            {
                "accessionNumber": ["0000320193-20-000010"],
                "form": ["10-K"],
                "filingDate": ["2020-10-30"],
                "acceptanceDateTime": ["2020-10-30T18:00:00.000Z"],
                "reportDate": ["2020-09-26"],
                "primaryDocument": ["aapl-20200926.htm"],
            }
        ]
        rows = sec.recent_filings_by_accession(submissions)
        self.assertEqual(2, len(rows))
        self.assertIn("0000320193-20-000010", rows)
        self.assertIn("0000320193-26-000050", rows)

    def test_fetch_submissions_loads_referenced_history_files(self):
        main = {
            "filings": {
                "recent": self.submissions()["filings"]["recent"],
                "files": [{"name": "CIK0000320193-submissions-001.json"}],
            }
        }
        historical = {
            "accessionNumber": ["0000320193-19-000100"],
            "form": ["10-K"],
        }
        with mock.patch.object(
            sec, "_get_json", side_effect=[main, historical]
        ) as get_json:
            result = sec.fetch_submissions("320193")
        self.assertEqual([historical], result["_supplemental_filings"])
        self.assertEqual(2, get_json.call_count)
        self.assertTrue(
            get_json.call_args_list[1]
            .args[0]
            .endswith("/submissions/CIK0000320193-submissions-001.json")
        )

    def test_reporting_currency_selects_ifrs_non_usd_companyfacts(self):
        rows = self.build(
            companyfacts=self.companyfacts(currency="EUR", taxonomy="ifrs-full"),
            currency="EUR",
        )
        self.assertEqual(120.0, rows[0]["revenue"])
        self.assertEqual(30.0, rows[0]["net_income"])
        self.assertEqual("EUR", rows[0]["currency"])
        self.assertTrue(rows[0]["backtest_eligible"])

    def test_source_revisions_remain_immutable_and_preserve_amendments(self):
        submissions = {
            "filings": {
                "recent": {
                    "accessionNumber": ["a-original", "a-amended"],
                    "form": ["10-Q", "10-Q/A"],
                    "filingDate": ["2026-05-02", "2026-06-10"],
                    "acceptanceDateTime": [
                        "2026-05-02T13:30:00.000Z",
                        "2026-06-10T15:00:00.000Z",
                    ],
                    "reportDate": ["2026-03-31", "2026-03-31"],
                    "primaryDocument": ["original.htm", "amended.htm"],
                }
            }
        }
        facts = []
        for accession, filed, value in (
            ("a-original", "2026-05-02", 100.0),
            ("a-amended", "2026-06-10", 105.0),
        ):
            facts.append(
                {
                    "accn": accession,
                    "start": "2026-01-01",
                    "end": "2026-03-31",
                    "filed": filed,
                    "fy": 2026,
                    "fp": "Q1",
                    "frame": "CY2026Q1",
                    "val": value,
                }
            )
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "Revenues": {"units": {"USD": facts}},
                    "NetIncomeLoss": {
                        "units": {
                            "USD": [
                                {**row, "val": row["val"] / 5}
                                for row in facts
                            ]
                        }
                    },
                }
            }
        }
        rows = self.build(
            submissions=submissions, companyfacts=companyfacts
        )
        self.assertEqual(
            [False, True], [row["source_is_amendment"] for row in rows]
        )
        self.assertNotIn("revision_number", rows[0])
        self.assertNotIn("is_restated", rows[0])
        self.assertNotEqual(rows[0]["revision_id"], rows[1]["revision_id"])

    def test_sec_user_agent_requires_contact(self):
        previous = os.environ.get("SEC_USER_AGENT")
        try:
            os.environ["SEC_USER_AGENT"] = "stock-market-system"
            with self.assertRaises(RuntimeError):
                sec._headers()
        finally:
            if previous is None:
                os.environ.pop("SEC_USER_AGENT", None)
            else:
                os.environ["SEC_USER_AGENT"] = previous


if __name__ == "__main__":
    unittest.main()
