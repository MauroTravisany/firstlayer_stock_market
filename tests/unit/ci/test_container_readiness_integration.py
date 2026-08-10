import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class ContainerReadinessIntegrationContractTests(unittest.TestCase):
    def test_integration_runner_is_non_mutating_and_checks_both_states(self):
        source = (
            ROOT / "scripts" / "ci" / "integration_test_containers.py"
        ).read_text(encoding="utf-8")
        for fragment in (
            "--read-only",
            "--cap-drop",
            "no-new-privileges",
            "/healthz",
            "/readyz",
            "not_ready",
            "mutation_performed",
            "PAPER_EXECUTION_MODE",
            "paper-api.alpaca.markets",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
