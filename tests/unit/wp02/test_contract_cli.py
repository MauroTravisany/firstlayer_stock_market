import json
import tempfile
import unittest
from pathlib import Path

from scripts.ci import validate_data_contracts

ROOT = Path(__file__).resolve().parents[3]


@unittest.skipUnless(
    (ROOT / "cloud-functions/daily_stocks/custom_function/bq_operations.py").is_file(),
    "full repository implementation files not present in isolated fixture",
)
class ContractCliTests(unittest.TestCase):
    def test_manifest_and_runtime_manifest_match_repository_contracts(self):
        result = validate_data_contracts.run(
            ROOT,
            ROOT / "contracts",
            manifest_path=ROOT / "contracts/manifest.json",
            runtime_manifest_path=(
                ROOT / "cloud-functions/strategy_brain/contract_set_manifest.json"
            ),
        )
        self.assertEqual(result, 0)

    def test_stale_manifest_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text(json.dumps({"stale": True}))
            result = validate_data_contracts.run(
                ROOT,
                ROOT / "contracts",
                manifest_path=manifest,
                runtime_manifest_path=None,
            )
        self.assertEqual(result, 2)
