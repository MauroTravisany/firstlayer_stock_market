from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
DOWNSTREAM_CONDITION = (
    "${{ always() && needs.preflight-gate.result == 'success' }}"
)
DOWNSTREAM_JOBS = ("build-images", "dataform", "dashboard", "terraform")


class MainPushWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.workflow = yaml.load(cls.workflow_text, Loader=yaml.BaseLoader)
        cls.jobs = cls.workflow["jobs"]

    def test_ci_is_triggered_by_pull_request_and_main_push(self):
        triggers = self.workflow["on"]
        self.assertEqual(["main"], triggers["pull_request"]["branches"])
        self.assertEqual(["main"], triggers["push"]["branches"])
        self.assertIn("workflow_dispatch", triggers)

    def test_dependency_review_job_succeeds_for_every_event(self):
        job = self.jobs["dependency-review"]
        self.assertNotIn(
            "if",
            job,
            "A job-level pull_request condition makes the job skipped on main push",
        )
        steps = {step["name"]: step for step in job["steps"]}
        review = steps["Review dependency changes"]
        self.assertEqual("github.event_name == 'pull_request'", review["if"])
        self.assertTrue(
            review["uses"].startswith("actions/dependency-review-action@")
        )
        not_applicable = steps["Record dependency review as not applicable"]
        self.assertEqual(
            "github.event_name != 'pull_request'", not_applicable["if"]
        )
        self.assertIn("NOT_APPLICABLE_OUTSIDE_PULL_REQUEST", not_applicable["run"])

    def test_preflight_requires_dependency_review_job_success(self):
        job = self.jobs["preflight-gate"]
        self.assertIn("dependency-review", job["needs"])
        script = job["steps"][0]["run"]
        self.assertIn('"dependency-review"', script)
        self.assertNotIn(
            'dependency not in {"success", "skipped"}',
            script,
            "The preflight must no longer treat a skipped job as successful",
        )

    def test_heavy_verification_jobs_run_after_successful_preflight(self):
        for job_name in DOWNSTREAM_JOBS:
            with self.subTest(job=job_name):
                job = self.jobs[job_name]
                self.assertEqual(["preflight-gate"], job["needs"])
                self.assertEqual(DOWNSTREAM_CONDITION, job["if"])

    def test_final_gate_requires_every_heavy_verification_surface(self):
        gate = self.jobs["ci-gate"]
        self.assertEqual(
            {
                "preflight-gate",
                "build-images",
                "dataform",
                "dashboard",
                "terraform",
            },
            set(gate["needs"]),
        )
        script = gate["steps"][0]["run"]
        for job_name in DOWNSTREAM_JOBS:
            self.assertIn(f'"{job_name}"', script)


if __name__ == "__main__":
    unittest.main()
