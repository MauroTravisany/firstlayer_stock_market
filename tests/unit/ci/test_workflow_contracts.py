import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"


def load_workflow(name):
    path = WORKFLOWS / name
    if not path.exists():
        raise AssertionError(f"missing workflow: {path.relative_to(ROOT)}")
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


class CiWorkflowContractTests(unittest.TestCase):
    def test_ci_runs_for_main_pr_push_and_manual_verification(self):
        workflow = load_workflow("ci.yml")
        triggers = workflow["on"]

        self.assertEqual(triggers["pull_request"]["branches"], ["main"])
        self.assertEqual(triggers["push"]["branches"], ["main"])
        self.assertIn("workflow_dispatch", triggers)
        self.assertEqual(workflow.get("permissions"), {"contents": "read"})

    def test_ci_contains_every_required_verification_surface(self):
        workflow = load_workflow("ci.yml")
        source = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")

        required_fragments = (
            "python -m unittest discover",
            "python -m compileall",
            "verify_repo_invariants.py",
            "dataform compile",
            "npm run build:strict",
            "terraform fmt -check",
            "terraform validate",
            "dependency-review-action",
            "actionlint",
            "git diff --check",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

        for job_name, job in workflow["jobs"].items():
            with self.subTest(job=job_name):
                permissions = job.get("permissions", workflow.get("permissions", {}))
                self.assertNotIn("write", permissions.values())

        dependency_review = workflow["jobs"]["dependency-review"]["steps"][0]
        self.assertEqual(dependency_review["with"]["fail-on-severity"], "critical")


class DeployWorkflowContractTests(unittest.TestCase):
    def test_cloud_run_deploy_only_follows_successful_ci_on_main(self):
        workflow = load_workflow("deploy.yml")
        triggers = workflow["on"]

        self.assertEqual(set(triggers), {"workflow_run"})
        self.assertEqual(triggers["workflow_run"]["workflows"], ["CI"])
        self.assertEqual(triggers["workflow_run"]["types"], ["completed"])
        self.assertEqual(triggers["workflow_run"]["branches"], ["main"])

        build = workflow["jobs"]["build"]
        condition = build.get("if", "")
        self.assertIn("conclusion == 'success'", condition)
        self.assertIn("head_branch == 'main'", condition)
        self.assertIn("event == 'push'", condition)
        checkout = next(
            step for step in build["steps"] if step.get("uses", "").startswith("actions/checkout@")
        )
        self.assertEqual(checkout["with"]["ref"], "${{ github.event.workflow_run.head_sha }}")

    def test_deploy_requires_approval_and_promotes_exact_immutable_artifact(self):
        workflow = load_workflow("deploy.yml")
        deploy = workflow["jobs"]["deploy"]
        source = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")

        self.assertIn("build", as_list(deploy["needs"]))
        self.assertEqual(deploy["environment"]["name"], "production")
        self.assertIn("APPROVED_SHA", source)
        self.assertIn("workflow_run.head_sha", source)
        self.assertIn("commits/main", source)
        self.assertIn("git rev-parse HEAD", source)
        self.assertIn("verify_release_artifacts.py", source)
        self.assertIn("@sha256:", source)
        self.assertIn("--no-traffic", source)
        self.assertIn("update-traffic", source)
        self.assertIn("smoke_test_services.py", source)
        self.assertIn("rollback", source.lower())
        self.assertIn("tac promoted-revisions.tsv", source)
        self.assertIn('trap \'status=$?; rollback; exit ${status}\' ERR', source)
        self.assertIn('--to-revisions "${previous_revision}=100"', source)
        stage_index = source.index("--no-traffic")
        smoke_index = source.index("smoke_test_services.py", stage_index)
        promote_index = source.index("gcloud run services update-traffic", smoke_index)
        self.assertLess(stage_index, smoke_index)
        self.assertLess(smoke_index, promote_index)
        self.assertNotIn("gcloud run deploy", source)
        self.assertNotIn("--source", source)

    def test_deploy_cannot_reactivate_schedulers_or_write_repository(self):
        workflow = load_workflow("deploy.yml")
        source = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")

        self.assertNotIn("master", source)
        self.assertNotIn("pull_request", workflow["on"])
        self.assertNotIn("push", workflow["on"])
        self.assertNotIn("workflow_dispatch", workflow["on"])
        self.assertNotIn("strategy-brain-generate", source)
        self.assertNotIn("strategy-brain-review", source)
        self.assertNotIn("scheduler jobs create", source)
        self.assertNotIn("scheduler jobs update", source)
        for job_name, job in workflow["jobs"].items():
            with self.subTest(job=job_name):
                permissions = job.get("permissions", workflow.get("permissions", {}))
                self.assertNotIn("write", permissions.values())

    def test_dashboard_deploy_has_no_master_or_unverified_manual_path(self):
        workflow = load_workflow("deploy-dashboard.yml")
        source = (WORKFLOWS / "deploy-dashboard.yml").read_text(encoding="utf-8")

        self.assertNotIn("master", source)
        self.assertNotIn("push", workflow["on"])
        self.assertNotIn("workflow_dispatch", workflow["on"])
        self.assertIn("workflow_run", workflow["on"])
        self.assertIn("schedule", workflow["on"])
        self.assertIn("verify-source", workflow["jobs"])
        self.assertIn("CI", source)
        self.assertIn("head_sha", source)


if __name__ == "__main__":
    unittest.main()
