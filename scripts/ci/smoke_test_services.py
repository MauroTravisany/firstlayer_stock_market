"""Read-only Cloud Run revision readiness smoke test."""

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import urllib.error
import urllib.request


DIGEST_IMAGE = re.compile(r"^.+@(?P<digest>sha256:[0-9a-f]{64})$")


class SmokeCheckError(RuntimeError):
    """A smoke check could not prove readiness."""


def describe_revision(revision, project, region, timeout_seconds):
    command = [
        "gcloud",
        "run",
        "revisions",
        "describe",
        revision,
        "--project",
        project,
        "--region",
        region,
        "--platform",
        "managed",
        "--format=json",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise SmokeCheckError(
            f"readiness describe timed out after {timeout_seconds}s"
        ) from exc
    except OSError as exc:
        raise SmokeCheckError(f"could not execute read-only gcloud describe: {exc}") from exc

    if completed.returncode != 0:
        raise SmokeCheckError(
            f"read-only gcloud describe failed with exit {completed.returncode}"
        )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeCheckError("gcloud describe did not return valid JSON") from exc
    if not isinstance(document, dict):
        raise SmokeCheckError("gcloud describe JSON root is not an object")
    return document


def evaluate_revision(service, document, expected_image):
    expected_match = DIGEST_IMAGE.fullmatch(expected_image)
    if not expected_match:
        raise SmokeCheckError("expected image must be immutable and include @sha256:<64 hex>")

    metadata = document.get("metadata", {})
    status = document.get("status", {})
    containers = document.get("spec", {}).get("containers", [])
    if len(containers) != 1:
        raise SmokeCheckError("revision must expose exactly one container")
    actual_image = containers[0].get("image")
    if actual_image != expected_image:
        raise SmokeCheckError("revision image does not match approved immutable digest")

    ready = next(
        (row for row in status.get("conditions", []) if row.get("type") == "Ready"),
        None,
    )
    if not ready or ready.get("status") != "True":
        raise SmokeCheckError("revision Ready condition is not True")
    if str(status.get("observedGeneration")) != str(metadata.get("generation")):
        raise SmokeCheckError("revision status has not observed the current generation")

    return {
        "status": "PASS",
        "service": service,
        "revision": metadata.get("name"),
        "image": actual_image,
        "image_digest": expected_match.group("digest"),
        "ready": True,
        "mutation_performed": False,
    }


def identity_token(audience, timeout_seconds):
    if not audience.startswith("https://"):
        raise SmokeCheckError("identity token audience must use https")
    command = [
        "gcloud",
        "auth",
        "print-identity-token",
        "--audiences",
        audience,
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise SmokeCheckError("could not obtain a private-service identity token") from exc
    token = completed.stdout.strip()
    if completed.returncode != 0 or not token:
        raise SmokeCheckError("private-service identity token command failed")
    return token


def functional_probe(url, token, timeout_seconds):
    if not url.startswith("https://") or not url.endswith(("/healthz", "/readyz")):
        raise SmokeCheckError("functional probe URL must be an HTTPS health endpoint")
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                raise SmokeCheckError(f"functional probe returned HTTP {response.status}")
            raw = response.read(64 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        raise SmokeCheckError(f"functional probe returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        raise SmokeCheckError(f"functional probe failed: {exc}") from exc
    if len(raw) > 64 * 1024:
        raise SmokeCheckError("functional probe response is too large")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SmokeCheckError("functional probe did not return valid JSON") from exc
    if not isinstance(document, dict):
        raise SmokeCheckError("functional probe JSON root is not an object")
    return document


def evaluate_functional_response(
    service, document, expected_git_sha, expected_version, expected_image
):
    match = DIGEST_IMAGE.fullmatch(expected_image)
    if not match:
        raise SmokeCheckError("functional check requires an immutable expected image")
    expected = {
        "status": "ready",
        "service": service,
        "git_sha": expected_git_sha,
        "version": expected_version,
        "image_digest": match.group("digest"),
        "operation": "readiness_probe",
        "mutation_performed": False,
    }
    for key, value in expected.items():
        if document.get(key) != value:
            raise SmokeCheckError(
                f"functional probe field {key!r} does not match the approved release"
            )
    forbidden = {
        "order_created",
        "strategy_executed",
        "bigquery_write",
        "alert_sent",
        "resource_modified",
    }
    if forbidden.intersection(document):
        raise SmokeCheckError("functional probe exposed a forbidden mutating operation")
    return {
        "status": "PASS",
        "service": service,
        "git_sha": expected_git_sha,
        "version": expected_version,
        "image_digest": match.group("digest"),
        "functional_ready": True,
        "mutation_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--expected-image", required=True)
    parser.add_argument("--expected-git-sha", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--audience", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()

    if not 1 <= args.timeout_seconds <= 120:
        print(json.dumps({"status": "FAIL", "error": "timeout must be between 1 and 120"}))
        return 2

    try:
        document = describe_revision(
            args.revision, args.project, args.region, args.timeout_seconds
        )
        result = evaluate_revision(args.service, document, args.expected_image)
        token = identity_token(args.audience, args.timeout_seconds)
        response = functional_probe(args.url, token, args.timeout_seconds)
        functional = evaluate_functional_response(
            args.service,
            response,
            args.expected_git_sha,
            args.expected_version,
            args.expected_image,
        )
        result.update(functional)
    except SmokeCheckError as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "service": args.service,
                    "revision": args.revision,
                    "error": str(exc),
                    "mutation_performed": False,
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
