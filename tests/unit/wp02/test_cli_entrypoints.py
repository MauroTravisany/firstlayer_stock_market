import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class CliEntrypointTests(unittest.TestCase):
    def _run_help(self, relative_path: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, str(ROOT / relative_path), "--help"],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"{relative_path} failed:\n{completed.stdout}\n{completed.stderr}",
        )
        self.assertIn("usage:", completed.stdout.lower())

    def test_repository_tools_are_executable_without_pythonpath(self):
        for relative_path in (
            "scripts/ci/validate_data_contracts.py",
            "scripts/ci/validate_observed_schemas.py",
            "research/snapshot_manifest.py",
            "research/replay.py",
        ):
            with self.subTest(relative_path=relative_path):
                self._run_help(relative_path)


if __name__ == "__main__":
    unittest.main()
