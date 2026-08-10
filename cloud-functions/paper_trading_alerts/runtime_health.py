"""Non-mutating runtime health contract for Cloud Run."""

import json
import os


HEALTH_PATHS = {"/healthz", "/readyz"}


def health_response(request, default_service):
    path = str(getattr(request, "path", "")).rstrip("/") or "/"
    if path not in HEALTH_PATHS:
        return None
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
    }
    if str(getattr(request, "method", "GET")).upper() != "GET":
        return (
            json.dumps(
                {
                    "status": "error",
                    "service": os.environ.get("K_SERVICE", default_service),
                    "operation": "readiness_probe",
                    "mutation_performed": False,
                    "message": "health endpoints only accept GET",
                },
                sort_keys=True,
            ),
            405,
            headers,
        )
    payload = {
        "status": "ready",
        "service": os.environ.get("K_SERVICE", default_service),
        "git_sha": os.environ.get("RELEASE_GIT_SHA", "unknown"),
        "version": os.environ.get("RELEASE_VERSION", "unknown"),
        "image_digest": os.environ.get("RELEASE_IMAGE_DIGEST", "unknown"),
        "operation": "readiness_probe",
        "mutation_performed": False,
    }
    return json.dumps(payload, sort_keys=True), 200, headers

