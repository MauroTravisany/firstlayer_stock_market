import json
import subprocess
import unittest
from unittest import mock

from scripts.ci import smoke_test_services


DIGEST = "sha256:" + "a" * 64
IMAGE = f"us-east1-docker.pkg.dev/project/repository/service@{DIGEST}"


def ready_revision(image=IMAGE):
    return {
        "metadata": {"name": "service-00001-abc", "generation": 1},
        "spec": {"containers": [{"image": image}]},
        "status": {
            "conditions": [{"type": "Ready", "status": "True"}],
            "observedGeneration": 1,
        },
    }


class SmokeTestServicesTests(unittest.TestCase):
    def test_ready_revision_with_expected_digest_passes(self):
        result = smoke_test_services.evaluate_revision(
            "service", ready_revision(), IMAGE
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["image_digest"], DIGEST)

    def test_not_ready_revision_fails_closed(self):
        document = ready_revision()
        document["status"]["conditions"][0]["status"] = "False"
        with self.assertRaises(smoke_test_services.SmokeCheckError):
            smoke_test_services.evaluate_revision("service", document, IMAGE)

    def test_mutable_expected_image_is_rejected(self):
        with self.assertRaises(smoke_test_services.SmokeCheckError):
            smoke_test_services.evaluate_revision(
                "service", ready_revision(), "registry/service:latest"
            )

    def test_image_mismatch_fails_closed(self):
        other = f"registry/service@sha256:{'b' * 64}"
        with self.assertRaises(smoke_test_services.SmokeCheckError):
            smoke_test_services.evaluate_revision("service", ready_revision(), other)

    @mock.patch("scripts.ci.smoke_test_services.subprocess.run")
    def test_gcloud_read_has_timeout_and_is_read_only(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(ready_revision()), stderr=""
        )
        document = smoke_test_services.describe_revision(
            "service-00001-abc", "project", "us-east1", 17
        )

        self.assertEqual(document["metadata"]["name"], "service-00001-abc")
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["gcloud", "run", "revisions", "describe"])
        self.assertNotIn("deploy", command)
        self.assertNotIn("update", command)
        self.assertEqual(run.call_args.kwargs["timeout"], 17)

    @mock.patch("scripts.ci.smoke_test_services.subprocess.run")
    def test_timeout_fails_closed(self, run):
        run.side_effect = subprocess.TimeoutExpired(cmd=["gcloud"], timeout=10)
        with self.assertRaises(smoke_test_services.SmokeCheckError):
            smoke_test_services.describe_revision(
                "service-00001-abc", "project", "us-east1", 10
            )


if __name__ == "__main__":
    unittest.main()
