from pathlib import Path
import unittest

from packages.common.data_contracts import load_contract_directory, manifest_document


ROOT = Path(__file__).resolve().parents[3]
EXPECTED_WP04_CONTRACTS = {
    "market_price_raw",
    "corporate_actions_pit",
    "market_session_calendar",
    "price_source_reconciliation",
    "market_price_canonical",
    "fx_rate_raw",
    "fx_rates_pit",
}
EXPECTED_CONTRACT_SET_HASH = (
    "c30a58b66643a946f518a04bd879e0cf13af8d403586ae01b487aa3fd64a2227"
)
EXPECTED_SCHEMA_SNAPSHOT_HASH = (
    "e5a1dfea983ca61cd6da0c1cacfb8d8d819e208093cf837470115323644ef3ca"
)


class Wp04ContractManifestPreviewTests(unittest.TestCase):
    def test_wp04_contracts_validate_and_match_frozen_manifest(self):
        contract_set = load_contract_directory(ROOT / "contracts")
        self.assertTrue(EXPECTED_WP04_CONTRACTS.issubset(set(contract_set.tables)))
        manifest = manifest_document(contract_set)
        self.assertEqual(
            EXPECTED_CONTRACT_SET_HASH,
            manifest["contract_set_hash"],
        )
        self.assertEqual(
            EXPECTED_SCHEMA_SNAPSHOT_HASH,
            manifest["schema_snapshot_hash"],
        )
        frozen = (ROOT / "contracts" / "manifest.json").read_text(
            encoding="utf-8"
        )
        self.assertIn(EXPECTED_CONTRACT_SET_HASH, frozen)
        self.assertIn(EXPECTED_SCHEMA_SNAPSHOT_HASH, frozen)


if __name__ == "__main__":
    unittest.main()
