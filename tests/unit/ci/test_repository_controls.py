import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


class RepositoryControlTests(unittest.TestCase):
    def test_codeowners_covers_every_critical_surface(self):
        source = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        for surface in (
            "/.github/workflows/",
            "/cloud-functions/",
            "/dataform/",
            "/terraform/",
            "/tools/",
            "/scripts/ci/",
            "/tests/",
            "/docs/audit-grade/",
        ):
            with self.subTest(surface=surface):
                self.assertIn(surface, source)
        self.assertNotIn("@replace-me", source)

    def test_dependabot_matches_present_package_ecosystems(self):
        path = ROOT / ".github" / "dependabot.yml"
        config = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        updates = config["updates"]
        configured = {
            (row["package-ecosystem"], row["directory"]) for row in updates
        }

        self.assertIn(("github-actions", "/"), configured)
        self.assertIn(("npm", "/dashboard"), configured)
        self.assertIn(("npm", "/dataform"), configured)
        self.assertIn(("terraform", "/terraform"), configured)
        for requirement in ROOT.glob("cloud-functions/*/requirements.txt"):
            directory = "/" + requirement.parent.relative_to(ROOT).as_posix()
            with self.subTest(directory=directory):
                self.assertIn(("pip", directory), configured)

    def test_manual_governance_and_rollback_are_explicit(self):
        source = (
            ROOT / "docs" / "audit-grade" / "runbooks" / "WP-01_CI_CD_GOVERNANCE.md"
        ).read_text(encoding="utf-8")
        for requirement in (
            "default branch",
            "Require a pull request before merging",
            "Require approvals",
            "Require conversation resolution before merging",
            "Require status checks to pass before merging",
            "Block force pushes",
            "Restrict deletions",
            "production",
            "required reviewers",
            "disabled_manually",
            "previous_revision",
            "update-traffic",
            "master",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, source)

    def test_cloud_run_inventory_matches_ci_matrix_and_docker_contexts(self):
        inventory = json.loads(
            (ROOT / "scripts" / "ci" / "cloud_run_services.json").read_text(
                encoding="utf-8"
            )
        )
        ci = yaml.load(
            (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        matrix = ci["jobs"]["build-images"]["strategy"]["matrix"]["include"]
        expected = sorted((row["service"], row["context"]) for row in inventory)
        actual = sorted((row["service"], row["context"]) for row in matrix)

        self.assertEqual(actual, expected)
        self.assertEqual(len(expected), len({service for service, _ in expected}))
        for service, context in expected:
            with self.subTest(service=service):
                self.assertTrue((ROOT / context / "Dockerfile").is_file())


if __name__ == "__main__":
    unittest.main()
