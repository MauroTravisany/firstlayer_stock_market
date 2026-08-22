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
    "ed803b540f7e6440f498ba7882a3da42d5785fdd8cd377a1a0a9506fc6ad29f6"
)
EXPECTED_SCHEMA_SNAPSHOT_HASH = (
    "ceb97061136c33afe7462d7c21038c633c82e82fc82ffb8adb988fc476aeea9d"
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
