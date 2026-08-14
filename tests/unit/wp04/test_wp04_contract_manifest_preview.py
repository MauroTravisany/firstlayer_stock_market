import json
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


class Wp04ContractManifestPreviewTests(unittest.TestCase):
    def test_wp04_contracts_validate_and_emit_expected_manifest(self):
        contract_set = load_contract_directory(ROOT / "contracts")
        self.assertTrue(EXPECTED_WP04_CONTRACTS.issubset(set(contract_set.tables)))
        manifest = manifest_document(contract_set)
        print("WP04_EXPECTED_MANIFEST=" + json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
