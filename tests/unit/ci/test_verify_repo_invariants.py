import json
import tempfile
import unittest
from pathlib import Path

from scripts.ci import verify_repo_invariants


SAFE_FILES = {
    ".github/workflows/deploy.yml": """name: Deploy Cloud Run service
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    if: github.event.workflow_run.conclusion == 'success' && github.event.workflow_run.head_branch == 'main' && github.event.workflow_run.event == 'push'
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.workflow_run.head_sha }}
  deploy:
    needs: build
    environment:
      name: production
    steps:
      - run: |
          echo "APPROVED_SHA=${{ github.event.workflow_run.head_sha }}"
          echo "@sha256: --no-traffic update-traffic smoke_test_services.py rollback"
""",
    "dataform/definitions/trading_champion_challenger_policy.sqlx": """
SELECT STRUCT("AAPL" AS ticker, "SHADOW_ONLY" AS execution_mode)
""",
    "dataform/definitions/legacy_result_registry.sqlx": """
SELECT "LEGACY_PRE_AUDIT_GRADE" AS legacy_classification,
       FALSE AS promotion_eligible,
       "NOT_ELIGIBLE_FOR_PROMOTION" AS promotion_block_reason
""",
    "docs/audit-grade/evidence/baseline_manifest.json": json.dumps(
        {
            "promotion_eligible": False,
            "operating_state": {
                "research": "BACKTEST_ONLY",
                "policy": "SHADOW_ONLY",
                "broker": "ALPACA_PAPER",
            },
            "legacy_results": [
                {
                    "legacy_classification": "LEGACY_PRE_AUDIT_GRADE",
                    "promotion_eligible": False,
                    "promotion_block_reason": "NOT_ELIGIBLE_FOR_PROMOTION",
                }
            ],
            "policy": {
                "rows": [{"execution_mode": "SHADOW_ONLY"}],
                "strategy_brain_statuses": ["BACKTEST_ONLY"],
                "production_change_allowed_values": [False],
            },
            "cloud_inventory": {
                "schedulers": [
                    {"name": "strategy-brain-generate", "state": "PAUSED"},
                    {"name": "strategy-brain-review", "state": "PAUSED"},
                ]
            },
        }
    ),
    "cloud-functions/strategy_brain/main.py": 'candidate = {"candidate_status": "BACKTEST_ONLY", "production_change_allowed": False}\n',
    "cloud-functions/paper_trade_executor/conf/conf.py": 'url = "https://paper-api.alpaca.markets"\nmode = os.environ.get("PAPER_EXECUTION_MODE", "paper")\n',
    "cloud-functions/paper_trade_risk_monitor/conf/conf.py": 'url = "https://paper-api.alpaca.markets"\nmode = os.environ.get("PAPER_EXECUTION_MODE", "paper")\n',
}


class RepoFixture:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for name, content in SAFE_FILES.items():
            self.write(name, content)

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def read(self, name):
        return (self.root / name).read_text(encoding="utf-8")

    def close(self):
        self._tmp.cleanup()


class RepoInvariantTests(unittest.TestCase):
    def setUp(self):
        self.repo = RepoFixture()

    def tearDown(self):
        self.repo.close()

    def assertViolation(self, code):
        violations = verify_repo_invariants.collect_violations(self.repo.root)
        self.assertIn(code, {violation.code for violation in violations})
        self.assertNotEqual(verify_repo_invariants.run(self.repo.root), 0)

    def test_safe_repository_is_accepted(self):
        self.assertEqual(verify_repo_invariants.collect_violations(self.repo.root), [])
        self.assertEqual(verify_repo_invariants.run(self.repo.root), 0)

    def test_paper_champion_is_rejected(self):
        self.repo.write(
            "dataform/definitions/trading_champion_challenger_policy.sqlx",
            'SELECT STRUCT("AAPL" AS ticker, "PAPER_CHAMPION" AS execution_mode)',
        )
        self.assertViolation("POLICY_NOT_SHADOW_ONLY")

    def test_live_mode_is_rejected(self):
        manifest = json.loads(self.repo.read("docs/audit-grade/evidence/baseline_manifest.json"))
        manifest["operating_state"]["policy"] = "LIVE_APPROVED"
        self.repo.write("docs/audit-grade/evidence/baseline_manifest.json", json.dumps(manifest))
        self.assertViolation("OPERATING_STATE_UNSAFE")

    def test_production_change_allowed_is_rejected(self):
        self.repo.write(
            "cloud-functions/strategy_brain/main.py",
            'candidate = {"candidate_status": "BACKTEST_ONLY", "production_change_allowed": True}',
        )
        self.assertViolation("PRODUCTION_CHANGE_ALLOWED")

    def test_non_paper_executor_mode_is_rejected(self):
        self.repo.write(
            "cloud-functions/paper_trade_executor/conf/conf.py",
            'url = "https://api.alpaca.markets"\nmode = os.environ.get("PAPER_EXECUTION_MODE", "live")',
        )
        self.assertViolation("ALPACA_NOT_PAPER_ONLY")

    def test_strategy_brain_scheduler_reactivation_is_rejected(self):
        deploy = self.repo.read(".github/workflows/deploy.yml")
        deploy += "\n# gcloud scheduler jobs update http strategy-brain-generate\n"
        self.repo.write(".github/workflows/deploy.yml", deploy)
        self.assertViolation("STRATEGY_BRAIN_REACTIVATION")

    def test_readiness_test_fixture_in_deploy_is_rejected(self):
        deploy = self.repo.read(".github/workflows/deploy.yml")
        deploy += "\n# READINESS_TEST_MODE=true\n"
        self.repo.write(".github/workflows/deploy.yml", deploy)
        self.assertViolation("READINESS_FIXTURE_IN_DEPLOY")

    def test_master_deploy_is_rejected(self):
        deploy = self.repo.read(".github/workflows/deploy.yml").replace("branches: [main]", "branches: [main, master]")
        self.repo.write(".github/workflows/deploy.yml", deploy)
        self.assertViolation("DEPLOY_FROM_MASTER")

    def test_pull_request_deploy_is_rejected(self):
        deploy = self.repo.read(".github/workflows/deploy.yml").replace("  workflow_run:", "  pull_request:\n  workflow_run:")
        self.repo.write(".github/workflows/deploy.yml", deploy)
        self.assertViolation("DEPLOY_FROM_PULL_REQUEST")

    def test_deploy_without_ci_dependency_is_rejected(self):
        deploy = self.repo.read(".github/workflows/deploy.yml").replace("workflows: [CI]", "workflows: [Other]")
        self.repo.write(".github/workflows/deploy.yml", deploy)
        self.assertViolation("DEPLOY_WITHOUT_CI")

    def test_hardcoded_secret_is_rejected(self):
        fake_secret = "sk-" + "proj-" + "abcdefghijklmnopqrstuvwxyz1234567890"
        self.repo.write("cloud-functions/leaked.py", f'OPENAI_API_KEY = "{fake_secret}"')
        self.assertViolation("HARDCODED_SECRET")

    def test_removed_legacy_lock_is_rejected(self):
        registry = self.repo.read("dataform/definitions/legacy_result_registry.sqlx")
        self.repo.write(
            "dataform/definitions/legacy_result_registry.sqlx",
            registry.replace("LEGACY_PRE_AUDIT_GRADE", "CURRENT"),
        )
        self.assertViolation("LEGACY_LOCK_REMOVED")

    def test_legacy_promotion_eligible_is_rejected(self):
        manifest = json.loads(self.repo.read("docs/audit-grade/evidence/baseline_manifest.json"))
        manifest["legacy_results"][0]["promotion_eligible"] = True
        self.repo.write("docs/audit-grade/evidence/baseline_manifest.json", json.dumps(manifest))
        self.assertViolation("LEGACY_PROMOTION_ENABLED")


if __name__ == "__main__":
    unittest.main()
