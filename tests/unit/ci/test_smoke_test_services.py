import json
import socket
import subprocess
import unittest
from unittest import mock

from scripts.ci import smoke_test_services


DIGEST = "sha256:" + "a" * 64
IMAGE = f"us-east1-docker.pkg.dev/project/repository/service@{DIGEST}"
SHA = "c" * 40
VERSION = "release-c"


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

    def valid_probe(self, **overrides):
        payload = {
            "status": "ready",
            "service": "service",
            "git_sha": SHA,
            "version": VERSION,
            "image_digest": DIGEST,
            "operation": "readiness_probe",
            "mutation_performed": False,
        }
        payload.update(overrides)
        return payload

    def test_functional_http_200_is_accepted(self):
        result = smoke_test_services.evaluate_functional_response(
            "service", self.valid_probe(), SHA, VERSION, IMAGE
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["git_sha"], SHA)

    def test_wrong_sha_or_digest_is_rejected(self):
        for payload in (
            self.valid_probe(git_sha="d" * 40),
            self.valid_probe(image_digest="sha256:" + "e" * 64),
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(smoke_test_services.SmokeCheckError):
                    smoke_test_services.evaluate_functional_response(
                        "service", payload, SHA, VERSION, IMAGE
                    )

    def test_malformed_or_mutating_response_is_rejected(self):
        for payload in (
            {"status": "ready"},
            self.valid_probe(mutation_performed=True),
            self.valid_probe(operation="create_order"),
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(smoke_test_services.SmokeCheckError):
                    smoke_test_services.evaluate_functional_response(
                        "service", payload, SHA, VERSION, IMAGE
                    )

    @mock.patch("scripts.ci.smoke_test_services.urllib.request.urlopen")
    def test_http_200_valid_json_is_returned(self, urlopen):
        response = mock.MagicMock()
        response.status = 200
        response.read.return_value = json.dumps(self.valid_probe()).encode("utf-8")
        urlopen.return_value.__enter__.return_value = response
        document = smoke_test_services.functional_probe(
            "https://service/readyz", "token", 5
        )
        self.assertEqual(document["service"], "service")

    @mock.patch("scripts.ci.smoke_test_services.urllib.request.urlopen")
    def test_http_200_malformed_json_fails_closed(self, urlopen):
        response = mock.MagicMock()
        response.status = 200
        response.read.return_value = b"not-json"
        urlopen.return_value.__enter__.return_value = response
        with self.assertRaises(smoke_test_services.SmokeCheckError):
            smoke_test_services.functional_probe(
                "https://service/readyz", "token", 5
            )

    @mock.patch("scripts.ci.smoke_test_services.urllib.request.urlopen")
    def test_http_500_fails_closed(self, urlopen):
        urlopen.side_effect = smoke_test_services.urllib.error.HTTPError(
            "https://service/readyz", 500, "error", {}, None
        )
        with self.assertRaises(smoke_test_services.SmokeCheckError):
            smoke_test_services.functional_probe(
                "https://service/readyz", "token", 5
            )

    @mock.patch("scripts.ci.smoke_test_services.urllib.request.urlopen")
    def test_http_timeout_fails_closed(self, urlopen):
        urlopen.side_effect = socket.timeout("timed out")
        with self.assertRaises(smoke_test_services.SmokeCheckError):
            smoke_test_services.functional_probe(
                "https://service/readyz", "token", 5
            )

    @mock.patch("scripts.ci.smoke_test_services.subprocess.run")
    def test_private_service_token_uses_explicit_https_audience_and_timeout(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="identity-token\n", stderr=""
        )
        token = smoke_test_services.identity_token("https://service", 9)
        self.assertEqual(token, "identity-token")
        self.assertEqual(
            run.call_args.args[0],
            [
                "gcloud",
                "auth",
                "print-identity-token",
                "--audiences",
                "https://service",
            ],
        )
        self.assertEqual(run.call_args.kwargs["timeout"], 9)


if __name__ == "__main__":
    unittest.main()
