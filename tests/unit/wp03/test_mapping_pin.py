import json
import re
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
MAPPING_PATH = (
    ROOT
    / "cloud-functions"
    / "financial_data"
    / "config"
    / "ticker_cik_map.v1.json"
)


class FinancialMappingPinTests(unittest.TestCase):
    def test_dataform_and_runtime_mapping_versions_match(self):
        mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
        settings = yaml.safe_load(
            (ROOT / "dataform" / "workflow_settings.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            mapping["mapping_version"],
            settings["vars"]["financialMappingVersion"],
        )
        canonical_sql = (
            ROOT
            / "dataform"
            / "definitions"
            / "financial_statements_pit.sqlx"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "dataform.projectConfig.vars.financialMappingVersion", canonical_sql
        )

    def test_every_asset_profile_ticker_has_an_explicit_mapping_policy(self):
        mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
        mapped = {entry["ticker"] for entry in mapping["entries"]}
        profile_sql = (
            ROOT / "dataform" / "definitions" / "asset_profile.sqlx"
        ).read_text(encoding="utf-8")
        profile_tickers = set(re.findall(r'STRUCT\("([A-Z0-9-]+)"', profile_sql))
        self.assertTrue(profile_tickers)
        self.assertEqual(set(), profile_tickers - mapped)

    def test_mapping_modes_are_complete_and_fail_closed(self):
        mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
        for entry in mapping["entries"]:
            mode = entry["financial_reporting"]
            self.assertIn(mode, {"SEC_EDGAR", "NOT_APPLICABLE"})
            if mode == "SEC_EDGAR":
                self.assertRegex(entry["cik"], r"^\d{10}$")
                self.assertRegex(entry["reporting_currency"], r"^[A-Z]{3}$")
            else:
                self.assertNotIn("cik", entry)
                self.assertNotIn("reporting_currency", entry)


if __name__ == "__main__":
    unittest.main()
