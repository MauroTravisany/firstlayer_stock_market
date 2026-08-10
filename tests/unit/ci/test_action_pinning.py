import tempfile
import unittest
from pathlib import Path

from scripts.ci import verify_action_pinning


ROOT = Path(__file__).resolve().parents[3]


class ActionPinningTests(unittest.TestCase):
    def test_repository_actions_are_immutable(self):
        self.assertEqual(verify_action_pinning.find_violations(ROOT / ".github" / "workflows"), [])

    def test_mutable_action_tag_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.yml"
            path.write_text(
                "jobs:\n  test:\n    steps:\n      - uses: actions/checkout@v4\n",
                encoding="utf-8",
            )
            violations = verify_action_pinning.find_violations(Path(directory))
        self.assertEqual(len(violations), 1)
        self.assertIn("actions/checkout@v4", violations[0])

    def test_mutable_docker_tag_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.yml"
            path.write_text(
                "jobs:\n  test:\n    steps:\n      - uses: docker://rhysd/actionlint:1.7.7\n",
                encoding="utf-8",
            )
            violations = verify_action_pinning.find_violations(Path(directory))
        self.assertEqual(len(violations), 1)


if __name__ == "__main__":
    unittest.main()
