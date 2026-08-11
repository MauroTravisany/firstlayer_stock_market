import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STRATEGY_BRAIN = ROOT / "cloud-functions/strategy_brain"
LEGACY_MAIN_SHA256 = (
    "0a7886382206553e71857020336fa71d828030019741841d79ce6a27dc6a6df3"
)


class RegistryWiringTests(unittest.TestCase):
    def test_main_is_the_only_audited_runtime_entrypoint(self):
        dockerfile = (STRATEGY_BRAIN / "Dockerfile").read_text()
        wrapper = (STRATEGY_BRAIN / "main.py").read_text()

        self.assertIn("import legacy_main as legacy", wrapper)
        self.assertIn("from experiment_registry_adapter import install", wrapper)
        install_index = wrapper.index("install(legacy)")
        delegate_index = wrapper.index("return legacy.main(request)")
        self.assertLess(install_index, delegate_index)
        self.assertFalse((STRATEGY_BRAIN / "main_wp02.py").exists())
        self.assertIn('CMD ["python", "main.py"]', dockerfile)
        self.assertNotIn("main_wp02.py", dockerfile)

    def test_legacy_main_is_the_frozen_historical_implementation(self):
        legacy_path = STRATEGY_BRAIN / "legacy_main.py"
        source = legacy_path.read_text(encoding="utf-8").replace("\r\n", "\n")

        self.assertIn("def _generate(", source)
        self.assertIn("def _review(", source)
        self.assertEqual(
            hashlib.sha256(source.encode("utf-8")).hexdigest(),
            LEGACY_MAIN_SHA256,
        )

    def test_registry_context_precedes_legacy_candidate_generation(self):
        source = (
            STRATEGY_BRAIN / "experiment_registry_adapter.py"
        ).read_text()
        context_index = source.index("context = create_context(payload, config, legacy)")
        generate_index = source.index("result = original_generate(client, config, payload)")

        self.assertLess(context_index, generate_index)
        self.assertIn('"production_change_allowed": False', source)

    def test_health_probes_short_circuit_before_business_operations(self):
        source = (STRATEGY_BRAIN / "legacy_main.py").read_text()
        probe_index = source.index('probe = health_response(request, "strategybrain")')
        return_index = source.index("return probe", probe_index)
        payload_index = source.index("payload = request.get_json", return_index)
        config_index = source.index("config = load_config()", return_index)
        generate_index = source.index("result = _generate(", config_index)

        self.assertLess(probe_index, return_index)
        self.assertLess(return_index, payload_index)
        self.assertLess(payload_index, config_index)
        self.assertLess(config_index, generate_index)

    def test_backtest_variants_require_committed_registry_lineage(self):
        source = (
            ROOT / "dataform/definitions/trading_backtest_context_variants.sqlx"
        ).read_text()
        for fragment in (
            'ref("audit_experiment_runs")',
            'ref("audit_experiment_candidates")',
            'dependencies: ["audit_trading_brain_registry_columns"]',
            'c.candidate_status = "BACKTEST_ONLY"',
            'r.status IN ("CANDIDATES_READY", "RUNNING", "COMPLETED")',
            "production_change_allowed IS FALSE",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

    def test_review_links_legacy_audit_before_terminal_publication(self):
        source = (
            ROOT / "cloud-functions/strategy_brain/experiment_registry_adapter.py"
        ).read_text()
        link_index = source.index("link_audit_to_experiment(")
        completed_index = source.index('"COMPLETED",', link_index)
        self.assertLess(link_index, completed_index)

    def test_terminal_registry_state_is_immutable_and_verified(self):
        source = (
            ROOT / "cloud-functions/strategy_brain/experiment_registry_storage.py"
        ).read_text()
        self.assertIn("terminal experiment state is immutable", source)
        self.assertIn("experiment status update was not persisted exactly", source)

    def test_invariant_assertion_blocks_incomplete_completed_experiments(self):
        source = (
            ROOT
            / "dataform/definitions/audit_experiment_registry_invariants.sqlx"
        ).read_text()
        self.assertIn("COMPLETED_EXPERIMENT_INCOMPLETE", source)
        self.assertIn("CANDIDATE_ID_CROSS_RUN_COLLISION", source)
        self.assertIn("DUPLICATE_DATA_SNAPSHOT_ID", source)
        self.assertIn("DUPLICATE_CANDIDATE_KEY", source)
        self.assertIn("DUPLICATE_ARTIFACT_KEY", source)
        self.assertIn("DUPLICATE_DECISION_KEY", source)
        self.assertIn("distinct_hypothesis_count", source)
        self.assertIn("SNAPSHOT_NOT_PUBLISHED", source)
        self.assertIn("DECISION_PRODUCTION_AUTHORITY", source)


if __name__ == "__main__":
    unittest.main()
