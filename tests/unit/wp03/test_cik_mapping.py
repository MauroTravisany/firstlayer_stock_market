import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
CUSTOM = ROOT / "cloud-functions" / "financial_data" / "custom_function"
spec = importlib.util.spec_from_file_location(
    "wp03_financial_mapping", CUSTOM / "financial_mapping.py"
)
mapping_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapping_module)


class CikMappingTests(unittest.TestCase):
    def test_repository_mapping_is_versioned_and_contains_foreign_currency(self):
        version, mapping, path = mapping_module.ticker_cik_map(
            {"ticker_cik_map_version": "sec-company-tickers-2026-08-11-v1"}
        )
        self.assertEqual("sec-company-tickers-2026-08-11-v1", version)
        self.assertTrue(path.is_file())
        self.assertEqual("0000320193", mapping["AAPL"]["cik"])
        self.assertEqual("USD", mapping["AAPL"]["reporting_currency"])
        self.assertEqual("EUR", mapping["ASML"]["reporting_currency"])
        self.assertEqual("CLP", mapping["BCH"]["reporting_currency"])
        self.assertEqual(
            "NOT_APPLICABLE", mapping["BTC-USD"]["financial_reporting"]
        )
        self.assertNotIn("cik", mapping["BTC-USD"])

    def _write(self, document):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "mapping.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        self.addCleanup(directory.cleanup)
        return path

    def test_version_mismatch_fails_closed(self):
        path = self._write(
            {
                "mapping_version": "actual-v1",
                "entries": [
                    {
                        "ticker": "AAPL",
                        "cik": "320193",
                        "reporting_currency": "USD",
                    }
                ],
            }
        )
        with self.assertRaisesRegex(RuntimeError, "version mismatch"):
            mapping_module.ticker_cik_map(
                {
                    "ticker_cik_map_path": str(path),
                    "ticker_cik_map_version": "expected-v2",
                }
            )

    def test_duplicate_ticker_fails_closed(self):
        path = self._write(
            {
                "mapping_version": "v1",
                "entries": [
                    {
                        "ticker": "AAPL",
                        "cik": "320193",
                        "reporting_currency": "USD",
                    },
                    {
                        "ticker": "aapl",
                        "cik": "320193",
                        "reporting_currency": "USD",
                    },
                ],
            }
        )
        with self.assertRaisesRegex(RuntimeError, "duplicate ticker AAPL"):
            mapping_module.ticker_cik_map(
                {
                    "ticker_cik_map_path": str(path),
                    "ticker_cik_map_version": "v1",
                }
            )

    def test_missing_reporting_currency_fails_closed_for_sec_issuer(self):
        path = self._write(
            {
                "mapping_version": "v1",
                "entries": [{"ticker": "ASML", "cik": "937966"}],
            }
        )
        with self.assertRaisesRegex(RuntimeError, "reporting_currency"):
            mapping_module.ticker_cik_map(
                {
                    "ticker_cik_map_path": str(path),
                    "ticker_cik_map_version": "v1",
                }
            )

    def test_not_applicable_entry_needs_no_cik_or_currency(self):
        path = self._write(
            {
                "mapping_version": "v1",
                "entries": [
                    {
                        "ticker": "ETH-USD",
                        "financial_reporting": "NOT_APPLICABLE",
                    }
                ],
            }
        )
        version, mapping, _path = mapping_module.ticker_cik_map(
            {
                "ticker_cik_map_path": str(path),
                "ticker_cik_map_version": "v1",
            }
        )
        self.assertEqual("v1", version)
        self.assertEqual(
            "NOT_APPLICABLE", mapping["ETH-USD"]["financial_reporting"]
        )

    def test_unknown_reporting_mode_fails_closed(self):
        path = self._write(
            {
                "mapping_version": "v1",
                "entries": [
                    {
                        "ticker": "AAPL",
                        "financial_reporting": "GUESS",
                    }
                ],
            }
        )
        with self.assertRaisesRegex(RuntimeError, "financial_reporting"):
            mapping_module.ticker_cik_map(
                {
                    "ticker_cik_map_path": str(path),
                    "ticker_cik_map_version": "v1",
                }
            )


if __name__ == "__main__":
    unittest.main()
