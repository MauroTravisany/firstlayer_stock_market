import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[3]
CUSTOM = ROOT / "cloud-functions" / "financial_data" / "custom_function"
PKG = types.ModuleType("custom_function")
PKG.__path__ = [str(CUSTOM)]
sys.modules.setdefault("custom_function", PKG)

processing = types.ModuleType("custom_function.data_processing")
processing.write_json_lines = lambda *_args, **_kwargs: None
sys.modules["custom_function.data_processing"] = processing
source = types.ModuleType("custom_function.sec_source")
source.build_sec_statement_revisions = lambda *_args, **_kwargs: []
source.fetch_companyfacts = lambda *_args, **_kwargs: {}
source.fetch_submissions = lambda *_args, **_kwargs: {}
sys.modules["custom_function.sec_source"] = source

spec = importlib.util.spec_from_file_location(
    "custom_function.pit_ingestion", CUSTOM / "pit_ingestion.py"
)
ingestion = importlib.util.module_from_spec(spec)
sys.modules["custom_function.pit_ingestion"] = ingestion
spec.loader.exec_module(ingestion)


class CikMappingTests(unittest.TestCase):
    def test_repository_mapping_is_versioned_and_contains_foreign_currency(self):
        version, mapping = ingestion._ticker_cik_map(
            {"ticker_cik_map_version": "sec-company-tickers-2026-08-11-v1"}
        )
        self.assertEqual("sec-company-tickers-2026-08-11-v1", version)
        self.assertEqual("0000320193", mapping["AAPL"]["cik"])
        self.assertEqual("USD", mapping["AAPL"]["reporting_currency"])
        self.assertEqual("EUR", mapping["ASML"]["reporting_currency"])
        self.assertEqual("CLP", mapping["BCH"]["reporting_currency"])

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
            ingestion._ticker_cik_map(
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
            ingestion._ticker_cik_map(
                {
                    "ticker_cik_map_path": str(path),
                    "ticker_cik_map_version": "v1",
                }
            )

    def test_missing_reporting_currency_fails_closed(self):
        path = self._write(
            {
                "mapping_version": "v1",
                "entries": [{"ticker": "ASML", "cik": "937966"}],
            }
        )
        with self.assertRaisesRegex(RuntimeError, "reporting_currency"):
            ingestion._ticker_cik_map(
                {
                    "ticker_cik_map_path": str(path),
                    "ticker_cik_map_version": "v1",
                }
            )


if __name__ == "__main__":
    unittest.main()
