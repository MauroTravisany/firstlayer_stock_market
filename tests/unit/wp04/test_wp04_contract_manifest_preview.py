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
    "fx_rates_pit",
}
EXPECTED_CONTRACT_SET_HASH = (
    "954796de8bd7a40d71a25aee822535bf8cf9b58bdddbb284fb3d47049ad63dd2"
)
EXPECTED_SCHEMA_SNAPSHOT_HASH = (
    "febd3ec35f65d9fd761831bbb88ee1ef1d90c1b3db8ad5dd79b78111a2630413"
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
