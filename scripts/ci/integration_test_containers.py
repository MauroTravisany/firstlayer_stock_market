"""Run non-mutating liveness/readiness integration checks against a built image."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import time
import urllib.error
import urllib.request


class IntegrationError(RuntimeError):
    """A container did not satisfy the non-mutating health contract."""


SAFE_ENV = {
    "RELEASE_GIT_SHA": "a" * 40,
    "RELEASE_VERSION": "integration-test",
    "RELEASE_IMAGE_DIGEST": "sha256:" + "b" * 64,
    "PROJECT_ID": "readiness-test",
    "project_id": "readiness-test",
    "dataset_id": "acciones_dataset",
    "bucket_name": "readiness-test",
    "table_id": "prices",
    "OPENAI_API_KEY": "fixture-only",
    "ALERT_WEBHOOK_URL": "https://example.invalid/non-mutating",
    "ALPACA_API_KEY": "fixture-only",
    "ALPACA_SECRET_KEY": "fixture-only",
    "ALPACA_BASE_URL": "https://paper-api.alpaca.markets",
    "PAPER_EXECUTION_MODE": "paper",
    "BRAIN_EXECUTION_MODE": "BACKTEST_ONLY",
    "READINESS_TEST_MODE": "true",
    "READINESS_FAKE_TABLES": "*",
}


def _run(command, timeout=60):
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if completed.returncode:
        raise IntegrationError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _request(port, path, timeout):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _start(image, service, environment):
    port = _free_port()
    command = [
        "docker", "run", "--detach", "--read-only", "--tmpfs", "/tmp",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--publish", f"127.0.0.1:{port}:8080", "--env", f"K_SERVICE={service}",
    ]
    for name, value in sorted(environment.items()):
        command.extend(["--env", f"{name}={value}"])
    command.append(image)
    return _run(command), port


def _wait(port, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, payload = _request(port, "/healthz", 1)
            if status == 200:
                return payload
        except (OSError, ValueError, json.JSONDecodeError):
            time.sleep(0.25)
    raise IntegrationError("container healthz startup timeout")


def _assert_payload(status, payload, expected_status):
    if status != expected_status or payload.get("mutation_performed") is not False:
        raise IntegrationError("unsafe or unexpected health response")
    if payload.get("operation") != "readiness_probe":
        raise IntegrationError("malformed health response")


def _docker_cmd(target):
    value = _run(
        ["docker", "inspect", "--format", "{{json .Config.Cmd}}", target]
    )
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise IntegrationError("docker returned malformed command metadata") from exc


def _assert_strategy_brain_runtime(image, container):
    expected_cmd = ["python", "main.py"]
    image_cmd = _docker_cmd(image)
    container_cmd = _docker_cmd(container)
    if image_cmd != expected_cmd or container_cmd != expected_cmd:
        raise IntegrationError(
            "Strategy Brain image and container must execute python main.py"
        )

    introspection = (
        "import json\n"
        "from pathlib import Path\n"
        "import legacy_main\n"
        "import main\n"
        "payload = {\n"
        '  "entrypoint_module": Path(main.__file__).name,\n'
        '  "legacy_module": Path(legacy_main.__file__).name,\n'
        '  "legacy_identity": main.legacy is legacy_main,\n'
        '  "registry_installed": bool(getattr(legacy_main, "_WP02_REGISTRY_INSTALLED", False)),\n'
        '  "generate_wrapped": legacy_main._generate.__module__ == "experiment_registry_adapter",\n'
        '  "review_wrapped": legacy_main._review.__module__ == "experiment_registry_adapter",\n'
        '  "alternate_entrypoint_exists": Path("/app/main_wp02.py").exists(),\n'
        '  "process_cmd": [part.decode() for part in Path("/proc/1/cmdline").read_bytes().split(b"\\0") if part],\n'
        "}\n"
        "print(json.dumps(payload, sort_keys=True))\n"
    )
    output = _run(
        ["docker", "exec", container, "python", "-c", introspection],
        timeout=20,
    )
    try:
        runtime = json.loads(output.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise IntegrationError(
            "Strategy Brain runtime introspection was malformed"
        ) from exc

    expected = {
        "entrypoint_module": "main.py",
        "legacy_module": "legacy_main.py",
        "legacy_identity": True,
        "registry_installed": True,
        "generate_wrapped": True,
        "review_wrapped": True,
        "alternate_entrypoint_exists": False,
        "process_cmd": expected_cmd,
    }
    if runtime != expected:
        raise IntegrationError(
            f"Strategy Brain runtime wiring mismatch: {runtime}"
        )
    return {**runtime, "image_cmd": image_cmd, "container_cmd": container_cmd}


def check_image(image, service, timeout):
    results = []
    for label, environment, expected_ready in (
        ("safe_fixture", SAFE_ENV, 200),
        ("missing_configuration", {}, 503),
    ):
        container = None
        try:
            container, port = _start(image, service, environment)
            health = _wait(port, timeout)
            _assert_payload(200, health, 200)
            status, ready = _request(port, "/readyz", min(timeout, 5))
            _assert_payload(status, ready, expected_ready)
            if expected_ready == 503 and ready.get("status") != "not_ready":
                raise IntegrationError("missing configuration did not produce not_ready")
            result = {
                "fixture": label,
                "health": 200,
                "ready": status,
                "mutation_performed": False,
                "requests": ["GET /healthz", "GET /readyz"],
            }
            if service == "strategybrain":
                result["runtime"] = _assert_strategy_brain_runtime(
                    image, container
                )
            results.append(result)
        finally:
            if container:
                subprocess.run(["docker", "rm", "--force", container], capture_output=True, timeout=20, check=False)
    return {"status": "PASS", "service": service, "image": image, "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30)
    args = parser.parse_args()
    try:
        result = check_image(args.image, args.service, args.timeout_seconds)
    except (IntegrationError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "service": args.service, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
