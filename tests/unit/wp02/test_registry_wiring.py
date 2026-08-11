import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


@unittest.skipUnless(
    (ROOT / "cloud-functions/strategy_brain/main_wp02.py").is_file(),
    "WP-02 runtime wrapper is not present in isolated staging",
)
class RegistryWiringTests(unittest.TestCase):
    def test_strategy_brain_image_uses_registry_wrapper(self):
        dockerfile = (ROOT / "cloud-functions/strategy_brain/Dockerfile").read_text()
        wrapper = (ROOT / "cloud-functions/strategy_brain/main_wp02.py").read_text()
        self.assertIn("--source=main_wp02.py", dockerfile)
        self.assertIn("install(legacy)", wrapper)
        self.assertIn("return legacy.main(request)", wrapper)

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
