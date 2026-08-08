import re
import json
import unittest
from pathlib import Path

from tools.capture_baseline import validate_manifest


REPO_ROOT = Path(__file__).resolve().parents[2]


class Wp00SafetyInvariantTest(unittest.TestCase):
    def read(self, relative_path):
        return (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    def test_champion_challenger_policy_is_entirely_shadow_only(self):
        policy = self.read(
            "dataform/definitions/trading_champion_challenger_policy.sqlx"
        )
        executable_modes = set(
            re.findall(r'"(SHADOW_ONLY|PAPER_CHAMPION|LIVE_[A-Z_]+)"', policy)
        )

        self.assertEqual(executable_modes, {"SHADOW_ONLY"})

    def test_strategy_brain_source_cannot_allow_production_change(self):
        source = self.read("cloud-functions/strategy_brain/main.py")

        self.assertNotRegex(source, r'["\']production_change_allowed["\']\s*:\s*True')
        self.assertIn('"production_change_allowed": False', source)

    def test_alpaca_executor_defaults_and_deploy_config_remain_paper(self):
        executor_config = self.read("cloud-functions/paper_trade_executor/conf/conf.py")
        monitor_config = self.read("cloud-functions/paper_trade_risk_monitor/conf/conf.py")
        deploy = self.read(".github/workflows/deploy.yml")

        self.assertIn('os.environ.get("PAPER_EXECUTION_MODE", "paper")', executor_config)
        self.assertIn('os.environ.get("PAPER_EXECUTION_MODE", "paper")', monitor_config)
        self.assertGreaterEqual(deploy.count("PAPER_EXECUTION_MODE=paper"), 2)

    def test_legacy_registry_contains_required_families_and_hard_block(self):
        registry = self.read("dataform/definitions/legacy_result_registry.sqlx")

        self.assertNotIn("${ref(", registry)
        self.assertNotIn("CURRENT_TIMESTAMP()", registry)
        self.assertNotRegex(registry, r"FROM\s+`stocks-437902\.")
        self.assertIn('"DIRECTIONAL_V1" AS result_family', registry)
        self.assertIn('"DIRECTIONAL_V4" AS result_family', registry)
        for family in (
            "STRATEGY_BRAIN_RUNS",
            "STRATEGY_BRAIN_CANDIDATES",
            "STRATEGY_BRAIN_AUDITS",
            "STRATEGY_BRAIN_SUMMARY",
            "STRATEGY_BRAIN_CAPITAL_CURVE",
            "CHAMPION_CHALLENGER_POLICY",
        ):
            self.assertIn(family, registry)
        self.assertIn('"LEGACY_PRE_AUDIT_GRADE" AS legacy_classification', registry)
        self.assertIn("FALSE AS promotion_eligible", registry)
        self.assertIn('"NOT_ELIGIBLE_FOR_PROMOTION" AS promotion_block_reason', registry)
        self.assertIn(
            '"f7c27dbf6b4293e4ba2755a642d2f616d98b3844" AS baseline_git_sha',
            registry,
        )

    def test_committed_baseline_manifest_is_valid(self):
        manifest = json.loads(
            self.read("docs/audit-grade/evidence/baseline_manifest.json")
        )

        validate_manifest(manifest)
        self.assertEqual(
            manifest["baseline_git_sha"],
            "f7c27dbf6b4293e4ba2755a642d2f616d98b3844",
        )

    def test_static_registry_matches_frozen_manifest(self):
        manifest = json.loads(
            self.read("docs/audit-grade/evidence/baseline_manifest.json")
        )
        registry = self.read("dataform/definitions/legacy_result_registry.sqlx")

        for row in manifest["legacy_results"]:
            self.assertIn(row["result_family"], registry)
            self.assertIn(row["results_checksum"], registry)
            self.assertRegex(registry, rf"\b{row['row_count']}\b")
            if row["date_start"]:
                self.assertIn(f'DATE("{row["date_start"]}")', registry)
            if row["date_end"]:
                self.assertIn(f'DATE("{row["date_end"]}")', registry)
        self.assertIn(manifest["baseline_git_sha"], registry)
        self.assertIn(manifest["bigquery_snapshot_as_of_utc"], registry)

    def test_enabled_strategy_brain_schedulers_are_recorded_as_blocker(self):
        manifest = json.loads(
            self.read("docs/audit-grade/evidence/baseline_manifest.json")
        )

        self.assertEqual(
            manifest["operational_blockers"],
            [
                {
                    "affected_resources": [
                        "strategy-brain-generate",
                        "strategy-brain-review",
                    ],
                    "blocker_id": "WP00_STRATEGY_BRAIN_NOT_PAUSED",
                    "observed_state": "ENABLED",
                    "promotion_eligible": False,
                    "required_state": "PAUSED_OR_LEGACY_RESEARCH",
                }
            ],
        )

    def test_example_manifest_is_valid_json_and_non_promotable(self):
        example = json.loads(
            self.read("docs/audit-grade/evidence/baseline_manifest.example.json")
        )

        self.assertEqual(example["classification"], "LEGACY_PRE_AUDIT_GRADE")
        self.assertIs(example["promotion_eligible"], False)


if __name__ == "__main__":
    unittest.main()
