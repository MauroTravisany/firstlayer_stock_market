"""Non-mutating liveness and readiness contract for Cloud Run."""

from __future__ import annotations

import importlib.util
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout


HEALTH_PATHS = {"/healthz", "/readyz"}
PAPER_URL = "https://paper-api.alpaca.markets"
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
PROFILES = {
    "stockdaily": {
        "secrets": ("project_id", "dataset_id", "bucket_name", "table_id"),
        "imports": ("google.cloud.bigquery", "google.cloud.secretmanager", "yfinance"),
        "tables": ("portfolio_assets",),
    },
    "stockfinancial": {
        "secrets": ("project_id", "dataset_id", "bucket_name"),
        "imports": ("google.cloud.bigquery", "google.cloud.secretmanager", "pandas", "yfinance"),
        "tables": ("portfolio_assets", "peer_universe"),
    },
    "stockmacrodata": {
        "secrets": ("project_id", "dataset_id"),
        "imports": ("google.cloud.bigquery", "google.cloud.secretmanager", "pandas", "yfinance"),
        "tables": ("portfolio_assets",),
    },
    "stockaianalysis": {
        "secrets": ("project_id", "dataset_id", "OPENAI_API_KEY", "ALERT_WEBHOOK_URL"),
        "imports": ("google.cloud.bigquery", "google.cloud.secretmanager", "openai"),
        "tables": ("portfolio_daily_signal",),
    },
    "papertradingalerts": {
        "secrets": ("project_id", "dataset_id", "OPENAI_API_KEY", "ALERT_WEBHOOK_URL"),
        "imports": ("google.cloud.bigquery", "google.cloud.secretmanager", "openai"),
        "tables": ("trading_daily_summary",),
    },
    "papertradeexecutor": {
        "secrets": ("project_id", "dataset_id", "ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
        "imports": ("google.cloud.bigquery", "google.cloud.secretmanager", "requests"),
        "tables": ("trading_paper_signals_active",),
        "paper": True,
    },
    "papertraderiskmonitor": {
        "secrets": ("project_id", "dataset_id", "ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
        "imports": ("google.cloud.bigquery", "google.cloud.secretmanager", "requests"),
        "tables": ("trading_alpaca_paper_executions", "valores_acciones_recientes"),
        "paper": True,
    },
    "strategybrain": {
        "secrets": ("project_id", "dataset_id"),
        "imports": ("google.cloud.bigquery", "google.cloud.secretmanager", "openai"),
        "tables": ("trading_backtest_context_variants",),
        "brain": True,
    },
}


def _payload(status, service, checks=None):
    return {
        "status": status,
        "service": service,
        "git_sha": os.environ.get("RELEASE_GIT_SHA", "unknown"),
        "version": os.environ.get("RELEASE_VERSION", "unknown"),
        "image_digest": os.environ.get("RELEASE_IMAGE_DIGEST", "unknown"),
        "operation": "readiness_probe",
        "mutation_performed": False,
        **({"checks": checks} if checks is not None else {}),
    }


def _run_bounded(function, timeout_seconds):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(function)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeout as exc:
        future.cancel()
        raise TimeoutError("read-only dependency timed out") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _secret_value(secret_id, project_id, timeout_seconds):
    value = os.environ.get(secret_id)
    if value and value.strip():
        return value.strip()
    if os.environ.get("READINESS_TEST_MODE", "").lower() == "true":
        raise RuntimeError(f"required secret is absent: {secret_id}")

    def access():
        from google.cloud import secretmanager

        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = secretmanager.SecretManagerServiceClient().access_secret_version(
            request={"name": name}, timeout=timeout_seconds
        )
        return response.payload.data.decode("utf-8").strip()

    value = _run_bounded(access, timeout_seconds)
    if not value:
        raise RuntimeError(f"required secret is empty: {secret_id}")
    return value


def _imports_ready(modules):
    fake = os.environ.get("READINESS_FAKE_IMPORTS") == "*"
    missing = []
    for module in modules:
        try:
            present = fake or importlib.util.find_spec(module) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            present = False
        if not present:
            missing.append(module)
    if missing:
        raise RuntimeError("essential imports unavailable: " + ",".join(missing))


def _tables_ready(project_id, dataset_id, tables, timeout_seconds):
    if os.environ.get("READINESS_TEST_MODE", "").lower() == "true":
        allowed = os.environ.get("READINESS_FAKE_TABLES", "")
        if allowed == "*":
            return
        provided = {value.strip() for value in allowed.split(",") if value.strip()}
        missing = set(tables) - provided
        if missing:
            raise RuntimeError("required table fixtures absent: " + ",".join(sorted(missing)))
        return

    def inspect():
        from google.cloud import bigquery

        client = bigquery.Client(project=project_id)
        for table in tables:
            client.get_table(f"{project_id}.{dataset_id}.{table}", timeout=timeout_seconds)

    _run_bounded(inspect, timeout_seconds)


def _readiness(default_service):
    service = os.environ.get("K_SERVICE", default_service)
    profile = PROFILES.get(service)
    checks = []
    if profile is None:
        return _payload("not_ready", service, [{"name": "service_profile", "status": "FAIL"}]), 503

    base_errors = []
    git_sha = os.environ.get("RELEASE_GIT_SHA", "")
    version = os.environ.get("RELEASE_VERSION", "")
    digest = os.environ.get("RELEASE_IMAGE_DIGEST", "")
    project_id = os.environ.get("PROJECT_ID", "")
    if not SHA.fullmatch(git_sha):
        base_errors.append("RELEASE_GIT_SHA")
    if not version.strip():
        base_errors.append("RELEASE_VERSION")
    if not DIGEST.fullmatch(digest):
        base_errors.append("RELEASE_IMAGE_DIGEST")
    if not project_id.strip():
        base_errors.append("PROJECT_ID")
    if base_errors:
        checks.append({"name": "required_configuration", "status": "FAIL", "missing": base_errors})
        return _payload("not_ready", service, checks), 503
    checks.append({"name": "required_configuration", "status": "PASS"})

    timeout_seconds = min(max(float(os.environ.get("READINESS_TIMEOUT_SECONDS", "5")), 0.1), 10.0)
    failures = []
    try:
        _imports_ready(profile["imports"])
        checks.append({"name": "essential_imports", "status": "PASS"})
    except Exception as exc:
        failures.append("essential_imports")
        checks.append({"name": "essential_imports", "status": "FAIL", "reason": type(exc).__name__})

    values = {}
    try:
        for secret_id in profile["secrets"]:
            values[secret_id] = _secret_value(secret_id, project_id, timeout_seconds)
        checks.append({"name": "required_secrets", "status": "PASS"})
    except Exception as exc:
        failures.append("required_secrets")
        checks.append({"name": "required_secrets", "status": "FAIL", "reason": type(exc).__name__})

    if profile.get("paper"):
        mode = os.environ.get("PAPER_EXECUTION_MODE", "").lower()
        url = os.environ.get("ALPACA_BASE_URL", "").rstrip("/")
        safe = mode == "paper" and url == PAPER_URL
        checks.append({"name": "alpaca_paper_only", "status": "PASS" if safe else "FAIL"})
        if not safe:
            failures.append("alpaca_paper_only")
    if profile.get("brain"):
        safe = os.environ.get("BRAIN_EXECUTION_MODE") == "BACKTEST_ONLY"
        checks.append({"name": "strategy_brain_backtest_only", "status": "PASS" if safe else "FAIL"})
        if not safe:
            failures.append("strategy_brain_backtest_only")

    if "project_id" in values and "dataset_id" in values:
        try:
            _tables_ready(values["project_id"], values["dataset_id"], profile["tables"], timeout_seconds)
            checks.append({"name": "read_only_table_contracts", "status": "PASS"})
        except Exception as exc:
            failures.append("read_only_table_contracts")
            checks.append({"name": "read_only_table_contracts", "status": "FAIL", "reason": type(exc).__name__})
    else:
        failures.append("read_only_table_contracts")
        checks.append({"name": "read_only_table_contracts", "status": "FAIL", "reason": "configuration_unavailable"})

    status = "not_ready" if failures else "ready"
    return _payload(status, service, checks), 503 if failures else 200


def health_response(request, default_service):
    path = str(getattr(request, "path", "")).rstrip("/") or "/"
    if path not in HEALTH_PATHS:
        return None
    headers = {"Content-Type": "application/json", "Cache-Control": "no-store"}
    service = os.environ.get("K_SERVICE", default_service)
    if str(getattr(request, "method", "GET")).upper() != "GET":
        return json.dumps(_payload("error", service), sort_keys=True), 405, headers
    if path == "/healthz":
        return json.dumps(_payload("alive", service), sort_keys=True), 200, headers
    payload, status = _readiness(default_service)
    return json.dumps(payload, sort_keys=True), status, headers
