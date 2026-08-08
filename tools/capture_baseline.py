#!/usr/bin/env python3
"""Capture an audit baseline without mutating repository or cloud state."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import decimal
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = "audit-grade-baseline/v1"
LEGACY_CLASSIFICATION = "LEGACY_PRE_AUDIT_GRADE"
NOT_PROMOTABLE_REASON = "NOT_ELIGIBLE_FOR_PROMOTION"
ALLOWED_BRAIN_STATUSES = frozenset({"BACKTEST_ONLY", "LEGACY_RESEARCH"})
DEFAULT_BASELINE_REF = "legacy-pre-audit-grade-2026-08"
DEFAULT_PROJECT_ID = "stocks-437902"
DEFAULT_DATASET_ID = "acciones_dataset"
DEFAULT_LOCATION = "us-east1"
DEFAULT_DATAFORM_REPOSITORY = "portfolio-valuation"
DEFAULT_DATAFORM_RELEASE = "production"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")
_SENSITIVE_KEY = re.compile(
    r"(^|_)(authorization|credential|discord|key|password|secret|token|webhook)($|_)",
    re.IGNORECASE,
)


class BaselineValidationError(ValueError):
    """Raised when the captured state violates the WP-00 safety contract."""


class ReadOnlyViolation(ValueError):
    """Raised before a command capable of mutating state can run."""


def canonical_json(value: Any) -> str:
    """Return the stable JSON representation used by every baseline checksum."""

    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def checksum(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_timestamp(value: dt.datetime | None = None) -> str:
    instant = value or dt.datetime.now(dt.timezone.utc)
    return instant.astimezone(dt.timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _parse_utc_timestamp(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise BaselineValidationError(f"{field} must be an ISO-8601 UTC timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise BaselineValidationError(f"{field} is invalid") from exc
    return parsed


def json_safe(value: Any) -> Any:
    """Convert BigQuery/API values into canonical JSON-compatible values."""

    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def sanitize(value: Any, *, parent_key: str = "") -> Any:
    """Remove secret values while preserving enough configuration for inventory."""

    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        env_name = str(value.get("name", ""))
        secret_env = bool(_SENSITIVE_KEY.search(env_name))
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY.search(key_text):
                sanitized[key_text] = "<redacted>"
            elif secret_env and key_text in {"value", "valueSource"}:
                sanitized[key_text] = "<redacted>"
            else:
                sanitized[key_text] = sanitize(item, parent_key=key_text)
        return sanitized
    if isinstance(value, list):
        return [sanitize(item, parent_key=parent_key) for item in value]
    return json_safe(value)


_CAPTURE_METADATA_FIELDS = (
    "capture_started_at_utc",
    "capture_completed_at_utc",
    "bigquery_snapshot_as_of_utc",
)


def _manifest_without_checksum(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic state material, excluding per-attempt capture metadata."""

    material = copy.deepcopy(manifest)
    material.pop("manifest_checksum", None)
    for field in _CAPTURE_METADATA_FIELDS:
        material.pop(field, None)
    return material


def _unredacted_secret_paths(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        env_name = str(value.get("name", ""))
        secret_env = bool(_SENSITIVE_KEY.search(env_name))
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if _SENSITIVE_KEY.search(str(key)) and item != "<redacted>":
                findings.append(child_path)
            elif secret_env and key in {"value", "valueSource"} and item != "<redacted>":
                findings.append(child_path)
            else:
                findings.extend(_unredacted_secret_paths(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_unredacted_secret_paths(item, f"{path}[{index}]"))
    return findings


def build_manifest(
    *,
    baseline_ref: str,
    baseline_git_sha: str,
    repository: dict[str, Any],
    cloud: dict[str, Any],
    results: list[dict[str, Any]],
    policy: dict[str, Any],
    capture_started_at_utc: str,
    capture_completed_at_utc: str,
    bigquery_snapshot_as_of_utc: str,
    capture_atomicity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic baseline manifest from already captured inputs."""

    legacy_results = []
    for source in results:
        row = copy.deepcopy(source)
        row["baseline_git_sha"] = baseline_git_sha
        row["legacy_classification"] = LEGACY_CLASSIFICATION
        row["promotion_eligible"] = False
        row["promotion_block_reason"] = NOT_PROMOTABLE_REASON
        legacy_results.append(row)

    legacy_results.sort(
        key=lambda row: (str(row.get("result_family", "")), str(row.get("source_table", "")))
    )

    normalized_policy = copy.deepcopy(policy)
    normalized_policy["rows"] = sorted(
        normalized_policy.get("rows", []),
        key=lambda row: (str(row.get("ticker", "")), str(row.get("champion_strategy_version", ""))),
    )
    normalized_policy["strategy_brain_statuses"] = sorted(
        set(normalized_policy.get("strategy_brain_statuses", []))
    )
    normalized_policy["production_change_allowed_values"] = sorted(
        set(normalized_policy.get("production_change_allowed_values", []))
    )
    normalized_policy["alpaca_execution_modes"] = sorted(
        set(normalized_policy.get("alpaca_execution_modes", []))
    )

    repository_copy = copy.deepcopy(repository)
    cloud_copy = copy.deepcopy(cloud)
    active_brain_schedulers = sorted(
        str(row.get("name", "")).rsplit("/", 1)[-1]
        for row in cloud_copy.get("schedulers", [])
        if str(row.get("name", "")).rsplit("/", 1)[-1]
        in {"strategy-brain-generate", "strategy-brain-review"}
        and row.get("state") != "PAUSED"
    )
    operational_blockers = []
    if active_brain_schedulers:
        operational_blockers.append(
            {
                "blocker_id": "WP00_STRATEGY_BRAIN_NOT_PAUSED",
                "affected_resources": active_brain_schedulers,
                "observed_state": "ENABLED",
                "required_state": "PAUSED_OR_LEGACY_RESEARCH",
                "promotion_eligible": False,
            }
        )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "capture_started_at_utc": capture_started_at_utc,
        "capture_completed_at_utc": capture_completed_at_utc,
        "bigquery_snapshot_as_of_utc": bigquery_snapshot_as_of_utc,
        "capture_atomicity": copy.deepcopy(capture_atomicity or {}),
        "baseline_ref": baseline_ref,
        "baseline_git_sha": baseline_git_sha,
        "classification": LEGACY_CLASSIFICATION,
        "promotion_eligible": False,
        "operating_state": {
            "research": "BACKTEST_ONLY",
            "policy": "SHADOW_ONLY",
            "broker": "ALPACA_PAPER",
            "real_execution_enabled": False,
        },
        "repository": repository_copy,
        "cloud": cloud_copy,
        "legacy_results": legacy_results,
        "policy": normalized_policy,
        "operational_blockers": operational_blockers,
        "section_checksums": {
            "repository": checksum(repository_copy),
            "cloud": checksum(cloud_copy),
            "legacy_results": checksum(legacy_results),
            "policy": checksum(normalized_policy),
        },
    }
    manifest["manifest_checksum"] = checksum(_manifest_without_checksum(manifest))
    return manifest


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Fail closed unless the captured baseline remains non-promotable and shadow-only."""

    errors: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported schema_version")
    if manifest.get("classification") != LEGACY_CLASSIFICATION:
        errors.append("baseline classification is not legacy")
    if manifest.get("promotion_eligible") is not False:
        errors.append("baseline is promotion eligible")
    try:
        started_at = _parse_utc_timestamp(
            manifest.get("capture_started_at_utc"), "capture_started_at_utc"
        )
        completed_at = _parse_utc_timestamp(
            manifest.get("capture_completed_at_utc"), "capture_completed_at_utc"
        )
        snapshot_at = _parse_utc_timestamp(
            manifest.get("bigquery_snapshot_as_of_utc"),
            "bigquery_snapshot_as_of_utc",
        )
        if not (started_at <= snapshot_at <= completed_at):
            errors.append("BigQuery snapshot timestamp is outside the capture interval")
    except BaselineValidationError as exc:
        errors.append(str(exc))
    baseline_git_sha = str(manifest.get("baseline_git_sha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", baseline_git_sha):
        errors.append("baseline_git_sha is not a full commit SHA")

    operating_state = manifest.get("operating_state", {})
    if operating_state.get("research") != "BACKTEST_ONLY":
        errors.append("research mode is not BACKTEST_ONLY")
    if operating_state.get("policy") != "SHADOW_ONLY":
        errors.append("policy mode is not SHADOW_ONLY")
    if operating_state.get("broker") != "ALPACA_PAPER":
        errors.append("broker mode is not ALPACA_PAPER")
    if operating_state.get("real_execution_enabled") is not False:
        errors.append("real execution is enabled")

    legacy_results = manifest.get("legacy_results", [])
    if not legacy_results:
        errors.append("legacy result registry is empty")
    required_families = {spec[0] for spec in RESULT_FAMILIES}
    captured_families = {row.get("result_family") for row in legacy_results}
    if captured_families != required_families:
        errors.append(
            "legacy result families mismatch: "
            f"missing={sorted(required_families - captured_families)} "
            f"unexpected={sorted(captured_families - required_families)}"
        )
    for row in legacy_results:
        family = row.get("result_family", "unknown")
        if row.get("legacy_classification") != LEGACY_CLASSIFICATION:
            errors.append(f"{family}: invalid legacy classification")
        if row.get("promotion_eligible") is not False:
            errors.append(f"{family}: promotion_eligible must be false")
        if row.get("promotion_block_reason") != NOT_PROMOTABLE_REASON:
            errors.append(f"{family}: missing promotion block reason")
        if not row.get("results_checksum"):
            errors.append(f"{family}: missing results checksum")
        if row.get("baseline_git_sha") != baseline_git_sha:
            errors.append(f"{family}: baseline_git_sha mismatch")

    repository = manifest.get("repository", {})
    configuration = repository.get("configuration", {})
    required_configurations = {spec[0] for spec in CONFIGURATION_TABLES}
    if not required_configurations.issubset(configuration):
        errors.append("repository configuration inventory is incomplete")

    cloud = manifest.get("cloud", {})
    if not cloud.get("schedulers"):
        errors.append("scheduler inventory is empty")
    if not cloud.get("services"):
        errors.append("Cloud Run service inventory is empty")
    if not cloud.get("dataform_release", {}).get("name"):
        errors.append("Dataform release inventory is missing")

    policy = manifest.get("policy", {})
    policy_rows = policy.get("rows", [])
    if not policy_rows:
        errors.append("champion/challenger policy inventory is empty")
    for row in policy_rows:
        if row.get("execution_mode") != "SHADOW_ONLY":
            errors.append(f"{row.get('ticker', 'unknown')}: policy is not SHADOW_ONLY")

    brain_statuses = set(policy.get("strategy_brain_statuses", []))
    if not brain_statuses:
        errors.append("Strategy Brain status inventory is empty")
    unexpected_statuses = brain_statuses - ALLOWED_BRAIN_STATUSES
    if unexpected_statuses:
        errors.append(f"unsafe Strategy Brain statuses: {sorted(unexpected_statuses)}")
    if set(policy.get("production_change_allowed_values", [])) != {False}:
        errors.append("Strategy Brain allows a production change")
    if set(policy.get("alpaca_execution_modes", [])) != {"paper"}:
        errors.append("Alpaca executor is not exclusively configured for paper")

    active_brain_schedulers = sorted(
        str(row.get("name", "")).rsplit("/", 1)[-1]
        for row in cloud.get("schedulers", [])
        if str(row.get("name", "")).rsplit("/", 1)[-1]
        in {"strategy-brain-generate", "strategy-brain-review"}
        and row.get("state") != "PAUSED"
    )
    blocker_resources = sorted(
        resource
        for blocker in manifest.get("operational_blockers", [])
        if blocker.get("blocker_id") == "WP00_STRATEGY_BRAIN_NOT_PAUSED"
        for resource in blocker.get("affected_resources", [])
    )
    if blocker_resources != active_brain_schedulers:
        errors.append("Strategy Brain scheduler blocker does not match captured state")

    secret_paths = _unredacted_secret_paths(manifest)
    if secret_paths:
        errors.append(f"manifest contains unredacted secrets at {secret_paths}")

    section_values = {
        "repository": repository,
        "cloud": cloud,
        "legacy_results": legacy_results,
        "policy": policy,
    }
    for section_name, section_value in section_values.items():
        if manifest.get("section_checksums", {}).get(section_name) != checksum(section_value):
            errors.append(f"{section_name} section checksum mismatch")

    expected_checksum = checksum(_manifest_without_checksum(manifest))
    if manifest.get("manifest_checksum") != expected_checksum:
        errors.append("manifest checksum mismatch")

    if errors:
        raise BaselineValidationError("; ".join(errors))


_MUTATING_SQL = re.compile(
    r"\b(ALTER|CALL|CREATE|DELETE|DROP|EXPORT|GRANT|INSERT|LOAD|MERGE|REPLACE|REVOKE|TRUNCATE|UPDATE)\b",
    re.IGNORECASE,
)


def _program_name(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe").removesuffix(".cmd")


def assert_read_only_command(command: Sequence[str]) -> None:
    """Allow only the explicit read surfaces needed by the baseline collector."""

    if not command:
        raise ReadOnlyViolation("empty command")

    parts = [str(part) for part in command]
    program = _program_name(parts[0])
    args = [part.lower() for part in parts[1:]]

    if program == "git":
        if args and args[0] in {"rev-parse", "show", "status", "ls-files"}:
            return
    elif program == "bq":
        if "query" in args:
            sql = parts[-1].strip()
            if not _MUTATING_SQL.search(sql) and re.match(r"^(SELECT|WITH)\b", sql, re.IGNORECASE):
                return
    elif program == "gcloud":
        normalized = [arg for arg in args if arg not in {"alpha", "beta"}]
        allowed_prefixes = (
            ["scheduler", "jobs", "list"],
            ["scheduler", "jobs", "describe"],
            ["run", "services", "list"],
            ["run", "services", "describe"],
            ["dataform", "release-configs", "describe"],
            ["dataform", "repositories", "describe"],
        )
        if any(normalized[: len(prefix)] == prefix for prefix in allowed_prefixes):
            return

    raise ReadOnlyViolation(f"command is outside the read-only allowlist: {parts!r}")


def assert_read_only_sql(sql: str) -> None:
    normalized = sql.strip()
    if not re.match(r"^(SELECT|WITH)\b", normalized, re.IGNORECASE):
        raise ReadOnlyViolation("BigQuery capture accepts only SELECT/WITH queries")
    if _MUTATING_SQL.search(normalized):
        raise ReadOnlyViolation("mutating SQL is forbidden in baseline capture")


def _validate_identifier(value: str, field: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} contains unsupported characters")
    return value


class GitReader:
    def __init__(self, repo_root: Path, timeout_seconds: int = 20):
        self.repo_root = repo_root
        self.timeout_seconds = timeout_seconds

    def run(self, *args: str) -> str:
        command = ["git", *args]
        assert_read_only_command(command)
        completed = subprocess.run(
            command,
            cwd=self.repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
        return completed.stdout.strip()

    def resolve(self, baseline_ref: str) -> str:
        return self.run("rev-parse", f"{baseline_ref}^{{commit}}")

    def inventory(self, baseline_ref: str, tracked_paths: Iterable[str]) -> dict[str, Any]:
        git_sha = self.resolve(baseline_ref)
        files = []
        for relative_path in sorted(set(tracked_paths)):
            content = self.run("show", f"{git_sha}:{relative_path}")
            files.append(
                {
                    "path": relative_path,
                    "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                }
            )
        return {
            "baseline_ref": baseline_ref,
            "git_sha": git_sha,
            "tracked_configuration_files": files,
        }


class BigQueryReader:
    """Minimal query-only adapter; all SQL is checked before submission."""

    def __init__(self, project_id: str, location: str, client: Any = None):
        self.project_id = _validate_identifier(project_id, "project_id")
        self.location = _validate_identifier(location, "location")
        if client is None:
            from google.cloud import bigquery

            client = bigquery.Client(
                project=self.project_id,
                location=self.location,
                _http=build_authorized_session(),
            )
        self.client = client
        self.snapshot_fallback_tables: set[str] = set()

    def rows(self, sql: str) -> list[dict[str, Any]]:
        assert_read_only_sql(sql)
        query_job = self.client.query(sql, location=self.location)
        return [json_safe(dict(row.items())) for row in query_job.result()]

    def rows_at_snapshot(
        self,
        snapshot_sql: str,
        fallback_sql: str,
        source_table: str,
    ) -> list[dict[str, Any]]:
        """Use BigQuery time travel, recording explicit fallback for unsupported views."""

        if source_table in self.snapshot_fallback_tables:
            return self.rows(fallback_sql)
        try:
            return self.rows(snapshot_sql)
        except Exception:
            self.snapshot_fallback_tables.add(source_table)
            return self.rows(fallback_sql)

    def dry_run(self, sql: str) -> int:
        assert_read_only_sql(sql)
        from google.cloud import bigquery

        job = self.client.query(
            sql,
            location=self.location,
            job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False),
        )
        return int(job.total_bytes_processed or 0)


class CloudInventoryReader:
    """GET-only reader for Scheduler, Cloud Run and Dataform release metadata."""

    def __init__(self, project_id: str, location: str, session: Any = None):
        self.project_id = _validate_identifier(project_id, "project_id")
        self.location = _validate_identifier(location, "location")
        if session is None:
            session = build_authorized_session()
        self.session = session

    def _get_json(self, url: str) -> dict[str, Any]:
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return sanitize(response.json())

    def _paged(self, url: str, collection_key: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url = url
        while next_url:
            payload = self._get_json(next_url)
            items.extend(payload.get(collection_key, []))
            token = payload.get("nextPageToken")
            next_url = f"{url}&pageToken={token}" if token else ""
        return items

    def capture(
        self, dataform_repository: str, dataform_release: str
    ) -> dict[str, Any]:
        repository = _validate_identifier(dataform_repository, "dataform_repository")
        release = _validate_identifier(dataform_release, "dataform_release")
        base = f"projects/{self.project_id}/locations/{self.location}"
        scheduler_url = (
            f"https://cloudscheduler.googleapis.com/v1/{base}/jobs?pageSize=500"
        )
        run_url = f"https://run.googleapis.com/v2/{base}/services?pageSize=100"
        dataform_url = (
            "https://dataform.googleapis.com/v1beta1/"
            f"{base}/repositories/{repository}/releaseConfigs/{release}"
        )

        schedulers = [self._scheduler_view(row) for row in self._paged(scheduler_url, "jobs")]
        services = [self._service_view(row) for row in self._paged(run_url, "services")]
        dataform = self._dataform_view(self._get_json(dataform_url))
        return {
            "schedulers": sorted(schedulers, key=lambda row: row.get("name", "")),
            "services": sorted(services, key=lambda row: row.get("name", "")),
            "dataform_release": dataform,
        }

    @staticmethod
    def _scheduler_view(row: dict[str, Any]) -> dict[str, Any]:
        target = row.get("httpTarget", {})
        body = target.get("body")
        return {
            "name": row.get("name"),
            "state": row.get("state"),
            "schedule": row.get("schedule"),
            "timeZone": row.get("timeZone"),
            "attemptDeadline": row.get("attemptDeadline"),
            "retryConfig": row.get("retryConfig"),
            "httpTarget": {
                "uri": target.get("uri"),
                "httpMethod": target.get("httpMethod"),
                "oidcToken": target.get("oidcToken"),
                "body_sha256": checksum(body) if body is not None else None,
            },
        }

    @staticmethod
    def _service_view(row: dict[str, Any]) -> dict[str, Any]:
        template = row.get("template", {})
        containers = []
        for container in template.get("containers", []):
            containers.append(
                {
                    "name": container.get("name"),
                    "image": container.get("image"),
                    "command": container.get("command"),
                    "args": container.get("args"),
                    "env": sanitize(container.get("env", [])),
                    "resources": container.get("resources"),
                }
            )
        return {
            "name": row.get("name"),
            "uri": row.get("uri"),
            "generation": row.get("generation"),
            "latestReadyRevision": row.get("latestReadyRevision"),
            "updateTime": row.get("updateTime"),
            "ingress": row.get("ingress"),
            "invokerIamDisabled": row.get("invokerIamDisabled"),
            "template": {
                "serviceAccount": template.get("serviceAccount"),
                "timeout": template.get("timeout"),
                "maxInstanceRequestConcurrency": template.get("maxInstanceRequestConcurrency"),
                "scaling": template.get("scaling"),
                "containers": containers,
            },
        }

    @staticmethod
    def _dataform_view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": row.get("name"),
            "gitCommitish": row.get("gitCommitish"),
            "cronSchedule": row.get("cronSchedule"),
            "timeZone": row.get("timeZone"),
            "codeCompilationConfig": row.get("codeCompilationConfig"),
            "releaseCompilationResult": row.get("releaseCompilationResult"),
            "recentScheduledReleaseRecords": row.get("recentScheduledReleaseRecords"),
        }


def _windows_root_ssl_context() -> ssl.SSLContext:
    """Build a verified TLS context from the Windows ROOT certificate store."""

    if not hasattr(ssl, "enum_certificates"):
        return ssl.create_default_context()
    certificates = []
    for certificate, encoding, _trust in ssl.enum_certificates("ROOT"):
        if encoding == "x509_asn":
            certificates.append(ssl.DER_cert_to_PEM_cert(certificate))
    if not certificates:
        return ssl.create_default_context()
    return ssl.create_default_context(cadata="\n".join(certificates))


def build_authorized_session() -> Any:
    """Create an OAuth session with TLS verification, including Windows enterprise CAs."""

    import google.auth
    import requests
    from google.auth.transport.requests import AuthorizedSession, Request
    from requests.adapters import HTTPAdapter

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    if os.name != "nt":
        return AuthorizedSession(credentials)

    ssl_context = _windows_root_ssl_context()

    class WindowsTrustStoreAdapter(HTTPAdapter):
        def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
            kwargs["ssl_context"] = ssl_context
            super().init_poolmanager(*args, **kwargs)

        def proxy_manager_for(self, *args: Any, **kwargs: Any) -> Any:
            kwargs["ssl_context"] = ssl_context
            return super().proxy_manager_for(*args, **kwargs)

    adapter = WindowsTrustStoreAdapter()
    refresh_session = requests.Session()
    refresh_session.mount("https://", adapter)
    authorized = AuthorizedSession(
        credentials,
        auth_request=Request(session=refresh_session),
    )
    authorized.mount("https://", adapter)
    return authorized


CONFIGURATION_TABLES = (
    ("watchlist", "trading_watchlist", "ticker"),
    ("strategy_versions", "trading_strategy_versions", "strategy_version"),
    (
        "active_strategy_config",
        "trading_active_strategy_config",
        "ticker, strategy_version, context_similarity_key",
    ),
    ("champion_challenger_policy", "trading_champion_challenger_policy", "ticker"),
    ("backtest_context_variants", "trading_backtest_context_variants", "variant_id"),
)


RESULT_FAMILIES = (
    ("DIRECTIONAL_V1", "trading_directional_strategy_backtest", "strategy_version = 'v1'", "analysis_date", "outcome_date"),
    ("DIRECTIONAL_V2", "trading_directional_strategy_backtest", "strategy_version = 'v2'", "analysis_date", "outcome_date"),
    ("DIRECTIONAL_V3", "trading_directional_strategy_backtest", "strategy_version = 'v3'", "analysis_date", "outcome_date"),
    ("DIRECTIONAL_V4", "trading_directional_strategy_backtest", "strategy_version = 'v4'", "analysis_date", "outcome_date"),
    ("STRATEGY_BRAIN_RUNS", "trading_brain_runs", "TRUE", "DATE(created_at)", "DATE(created_at)"),
    ("STRATEGY_BRAIN_CANDIDATES", "trading_brain_weight_candidates", "TRUE", "DATE(created_at)", "DATE(created_at)"),
    ("STRATEGY_BRAIN_AUDITS", "trading_brain_ai_audits", "TRUE", "DATE(created_at)", "DATE(created_at)"),
    ("STRATEGY_BRAIN_SUMMARY", "trading_brain_candidate_summary", "TRUE", "DATE(calculated_at)", "DATE(calculated_at)"),
    ("STRATEGY_BRAIN_CAPITAL_CURVE", "trading_brain_candidate_capital_curve", "TRUE", "analysis_date", "outcome_date"),
    ("CHAMPION_CHALLENGER_POLICY", "trading_champion_challenger_policy", "TRUE", "NULL", "NULL"),
    ("CURRENT_SHADOW_SIGNALS", "trading_champion_challenger_signals", "TRUE", "analysis_date", "analysis_date"),
)


KNOWN_DEFECTS = {
    "DIRECTIONAL": [
        "financial available_at is not audit-grade",
        "raw/adjusted prices and corporate actions are not canonical",
        "gap-aware fills and locked final test are not implemented",
    ],
    "STRATEGY_BRAIN": [
        "candidate/run isolation and final-test separation await WP-06/WP-07",
        "legacy adaptive validation is not promotion evidence",
    ],
    "POLICY": ["policy snapshot predates independent promotion gates"],
    "SIGNALS": ["signals inherit legacy data and execution-model limitations"],
}


def _table_name(project_id: str, dataset_id: str, table_id: str) -> str:
    for value, field in (
        (project_id, "project_id"),
        (dataset_id, "dataset_id"),
        (table_id, "table_id"),
    ):
        _validate_identifier(value, field)
    return f"`{project_id}.{dataset_id}.{table_id}`"


def _snapshot_source(table: str, snapshot_as_of_utc: str) -> str:
    _parse_utc_timestamp(snapshot_as_of_utc, "bigquery_snapshot_as_of_utc")
    return f"{table} FOR SYSTEM_TIME AS OF TIMESTAMP('{snapshot_as_of_utc}')"


def _rows_from_source(
    reader: Any,
    *,
    table_id: str,
    table: str,
    snapshot_as_of_utc: str,
    sql_template: str,
) -> list[dict[str, Any]]:
    snapshot_sql = sql_template.format(
        source=_snapshot_source(table, snapshot_as_of_utc)
    )
    fallback_sql = sql_template.format(source=table)
    rows_at_snapshot = getattr(reader, "rows_at_snapshot", None)
    if rows_at_snapshot is None:
        return reader.rows(snapshot_sql)
    return rows_at_snapshot(snapshot_sql, fallback_sql, table_id)


def render_sqlx_query(path: Path, project_id: str, dataset_id: str) -> str:
    """Render the simple Dataform ref syntax used by the WP-00 model for dry-run."""

    text = path.read_text(encoding="utf-8")
    start = text.find("config")
    opening = text.find("{", start)
    if start < 0 or opening < 0:
        raise ValueError("SQLX config block was not found")
    depth = 0
    closing = -1
    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                closing = index
                break
    if closing < 0:
        raise ValueError("SQLX config block is not balanced")

    query = text[closing + 1 :].strip()

    def replace_ref(match: re.Match[str]) -> str:
        return _table_name(project_id, dataset_id, match.group(1))

    query = re.sub(r'\$\{ref\("([A-Za-z0-9_-]+)"\)\}', replace_ref, query)
    if "${" in query:
        raise ValueError("unsupported SQLX expression remains after rendering")
    assert_read_only_sql(query)
    return query


def capture_configuration(
    reader: BigQueryReader,
    project_id: str,
    dataset_id: str,
    snapshot_as_of_utc: str = "2026-08-08T00:00:00.000000Z",
    reverse_source_order: bool = False,
) -> dict[str, Any]:
    inventory: dict[str, Any] = {}
    for family, table_id, order_by in CONFIGURATION_TABLES:
        table = _table_name(project_id, dataset_id, table_id)
        rows = _rows_from_source(
            reader,
            table_id=table_id,
            table=table,
            snapshot_as_of_utc=snapshot_as_of_utc,
            sql_template=(
                f"SELECT * FROM {{source}} ORDER BY {order_by}"
                + (" DESC" if reverse_source_order else "")
            ),
        )
        canonical_rows = sorted(sanitize(rows), key=canonical_json)
        inventory[family] = {
            "source_table": table_id,
            "row_count": len(canonical_rows),
            "rows": canonical_rows,
            "checksum": checksum(canonical_rows),
        }
    return inventory


def _defect_family(result_family: str) -> str:
    if result_family.startswith("DIRECTIONAL"):
        return "DIRECTIONAL"
    if result_family.startswith("STRATEGY_BRAIN"):
        return "STRATEGY_BRAIN"
    if result_family == "CHAMPION_CHALLENGER_POLICY":
        return "POLICY"
    return "SIGNALS"


def capture_result_registry(
    reader: BigQueryReader,
    project_id: str,
    dataset_id: str,
    baseline_git_sha: str,
    snapshot_as_of_utc: str,
) -> list[dict[str, Any]]:
    registry: list[dict[str, Any]] = []
    for result_family, table_id, predicate, date_start, date_end in RESULT_FAMILIES:
        table = _table_name(project_id, dataset_id, table_id)
        metadata_template = f"""
SELECT
  COUNT(*) AS row_count,
  CAST(MIN({date_start}) AS STRING) AS date_start,
  CAST(MAX({date_end}) AS STRING) AS date_end
FROM {{source}}
WHERE {predicate}
""".strip()
        metadata_rows = _rows_from_source(
            reader,
            table_id=table_id,
            table=table,
            snapshot_as_of_utc=snapshot_as_of_utc,
            sql_template=metadata_template,
        )
        if len(metadata_rows) != 1:
            raise RuntimeError(f"unexpected metadata result for {result_family}")
        hash_rows = _rows_from_source(
            reader,
            table_id=table_id,
            table=table,
            snapshot_as_of_utc=snapshot_as_of_utc,
            sql_template=f"""
SELECT TO_HEX(SHA256(TO_JSON_STRING(t))) AS row_hash
FROM {{source}} AS t
WHERE {predicate}
ORDER BY row_hash
""".strip(),
        )
        row_hashes = [row["row_hash"] for row in hash_rows]
        metadata = metadata_rows[0]
        if len(row_hashes) != int(metadata.get("row_count", 0)):
            raise RuntimeError(f"row hash count mismatch for {result_family}")
        registry.append(
            {
                "result_family": result_family,
                "source_table": table_id,
                "row_count": int(metadata.get("row_count", 0)),
                "date_start": metadata.get("date_start"),
                "date_end": metadata.get("date_end"),
                "baseline_git_sha": baseline_git_sha,
                "data_snapshot_approximation": (
                    "READ_ONLY_LIVE_TABLE_STATE; sorted SHA256 of every selected row; "
                    "not an immutable point-in-time snapshot"
                ),
                "known_defects": KNOWN_DEFECTS[_defect_family(result_family)],
                "results_checksum": checksum(row_hashes),
            }
        )
    return registry


def _execution_modes_from_services(services: list[dict[str, Any]]) -> list[str]:
    modes: set[str] = set()
    for service in services:
        service_name = str(service.get("name", "")).rsplit("/", 1)[-1]
        if service_name not in {"papertradeexecutor", "papertraderiskmonitor"}:
            continue
        for container in service.get("template", {}).get("containers", []):
            for env in container.get("env", []):
                if env.get("name") == "PAPER_EXECUTION_MODE" and env.get("value") != "<redacted>":
                    modes.add(str(env.get("value", "")).lower())
    return sorted(modes)


def capture_policy(
    reader: BigQueryReader,
    project_id: str,
    dataset_id: str,
    cloud_inventory: dict[str, Any],
    snapshot_as_of_utc: str,
) -> dict[str, Any]:
    policy_table = _table_name(project_id, dataset_id, "trading_champion_challenger_policy")
    candidates_table = _table_name(project_id, dataset_id, "trading_brain_weight_candidates")
    runs_table = _table_name(project_id, dataset_id, "trading_brain_runs")
    audits_table = _table_name(project_id, dataset_id, "trading_brain_ai_audits")

    policy_rows = _rows_from_source(
        reader,
        table_id="trading_champion_challenger_policy",
        table=policy_table,
        snapshot_as_of_utc=snapshot_as_of_utc,
        sql_template=(
            "SELECT ticker, champion_strategy_version, execution_mode, policy_reason "
            "FROM {source} ORDER BY ticker"
        ),
    )
    status_rows = _rows_from_source(
        reader,
        table_id="trading_brain_weight_candidates",
        table=candidates_table,
        snapshot_as_of_utc=snapshot_as_of_utc,
        sql_template=(
            "SELECT DISTINCT candidate_status FROM {source} ORDER BY candidate_status"
        ),
    )
    run_production_rows = _rows_from_source(
        reader,
        table_id="trading_brain_runs",
        table=runs_table,
        snapshot_as_of_utc=snapshot_as_of_utc,
        sql_template="SELECT DISTINCT production_change_allowed FROM {source}",
    )
    audit_production_rows = _rows_from_source(
        reader,
        table_id="trading_brain_ai_audits",
        table=audits_table,
        snapshot_as_of_utc=snapshot_as_of_utc,
        sql_template="SELECT DISTINCT production_change_allowed FROM {source}",
    )
    production_values = sorted(
        {
            row["production_change_allowed"]
            for row in run_production_rows + audit_production_rows
        }
    )
    return {
        "rows": sorted(policy_rows, key=canonical_json),
        "policy_checksum": checksum(sorted(policy_rows, key=canonical_json)),
        "strategy_brain_statuses": [row["candidate_status"] for row in status_rows],
        "production_change_allowed_values": production_values,
        "alpaca_execution_modes": _execution_modes_from_services(
            cloud_inventory.get("services", [])
        ),
    }


TRACKED_CONFIGURATION_FILES = (
    "dataform/workflow_settings.yaml",
    "dataform/package.json",
    "dataform/definitions/trading_watchlist.sqlx",
    "dataform/definitions/trading_strategy_versions.sqlx",
    "dataform/definitions/trading_active_strategy_config.sqlx",
    "dataform/definitions/trading_champion_challenger_policy.sqlx",
    "cloud-functions/strategy_brain/conf/conf.py",
    "cloud-functions/paper_trade_executor/conf/conf.py",
    "cloud-functions/paper_trade_risk_monitor/conf/conf.py",
    ".github/workflows/deploy.yml",
)


def capture_live_baseline(
    *,
    repo_root: Path,
    baseline_ref: str,
    project_id: str,
    dataset_id: str,
    location: str,
    dataform_repository: str,
    dataform_release: str,
    bigquery_client: Any = None,
    http_session: Any = None,
    reverse_configuration_source_order: bool = False,
) -> dict[str, Any]:
    capture_started_at_utc = utc_timestamp()
    bigquery_snapshot_as_of_utc = capture_started_at_utc
    git = GitReader(repo_root)
    repository_git = git.inventory(baseline_ref, TRACKED_CONFIGURATION_FILES)
    baseline_git_sha = repository_git["git_sha"]
    shared_session = http_session
    if shared_session is None and bigquery_client is None:
        shared_session = build_authorized_session()
    if bigquery_client is None:
        from google.cloud import bigquery

        bigquery_client = bigquery.Client(
            project=project_id,
            location=location,
            _http=shared_session,
        )
    bq = BigQueryReader(project_id, location, client=bigquery_client)
    cloud = CloudInventoryReader(project_id, location, session=shared_session).capture(
        dataform_repository, dataform_release
    )
    configuration = capture_configuration(
        bq,
        project_id,
        dataset_id,
        bigquery_snapshot_as_of_utc,
        reverse_configuration_source_order,
    )
    results = capture_result_registry(
        bq,
        project_id,
        dataset_id,
        baseline_git_sha,
        bigquery_snapshot_as_of_utc,
    )
    policy = capture_policy(
        bq, project_id, dataset_id, cloud, bigquery_snapshot_as_of_utc
    )
    repository = {
        "git": repository_git,
        "configuration": configuration,
        "configuration_checksum": checksum(configuration),
    }
    capture_completed_at_utc = utc_timestamp()
    fallback_tables = sorted(bq.snapshot_fallback_tables)
    capture_atomicity = {
        "bigquery": (
            "SINGLE_SYSTEM_TIME_AS_OF"
            if not fallback_tables
            else "SYSTEM_TIME_AS_OF_WITH_RECORDED_LIVE_FALLBACKS"
        ),
        "bigquery_live_fallback_tables": fallback_tables,
        "non_atomic_surfaces": [
            "Cloud Scheduler REST inventory",
            "Cloud Run REST inventory",
            "Dataform release REST inventory",
        ],
        "repository": "IMMUTABLE_GIT_COMMIT",
    }
    manifest = build_manifest(
        baseline_ref=baseline_ref,
        baseline_git_sha=baseline_git_sha,
        repository=repository,
        cloud=cloud,
        results=results,
        policy=policy,
        capture_started_at_utc=capture_started_at_utc,
        capture_completed_at_utc=capture_completed_at_utc,
        bigquery_snapshot_as_of_utc=bigquery_snapshot_as_of_utc,
        capture_atomicity=capture_atomicity,
    )
    validate_manifest(manifest)
    return manifest


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    parser.add_argument("--baseline-ref", default=DEFAULT_BASELINE_REF)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--dataset-id", default=DEFAULT_DATASET_ID)
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    parser.add_argument("--dataform-repository", default=DEFAULT_DATAFORM_REPOSITORY)
    parser.add_argument("--dataform-release", default=DEFAULT_DATAFORM_RELEASE)
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "docs" / "audit-grade" / "evidence" / "baseline_manifest.json",
    )
    parser.add_argument(
        "--verify",
        type=Path,
        help="compare the captured checksum with an existing manifest instead of writing",
    )
    parser.add_argument(
        "--dry-run-registry",
        action="store_true",
        help="BigQuery dry-run legacy_result_registry.sqlx and exit without capture",
    )
    parser.add_argument(
        "--reverse-configuration-source-order",
        action="store_true",
        help="request configuration rows in reverse source order to test canonicalization",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.dry_run_registry:
            query = render_sqlx_query(
                args.repo_root.resolve()
                / "dataform"
                / "definitions"
                / "legacy_result_registry.sqlx",
                args.project_id,
                args.dataset_id,
            )
            bytes_processed = BigQueryReader(args.project_id, args.location).dry_run(query)
            print(f"LEGACY_REGISTRY_DRY_RUN_OK bytes_processed={bytes_processed}")
            return 0
        manifest = capture_live_baseline(
            repo_root=args.repo_root.resolve(),
            baseline_ref=args.baseline_ref,
            project_id=args.project_id,
            dataset_id=args.dataset_id,
            location=args.location,
            dataform_repository=args.dataform_repository,
            dataform_release=args.dataform_release,
            reverse_configuration_source_order=args.reverse_configuration_source_order,
        )
        if args.verify:
            expected = json.loads(args.verify.read_text(encoding="utf-8"))
            validate_manifest(expected)
            if expected.get("manifest_checksum") != manifest.get("manifest_checksum"):
                print(
                    "BASELINE_DRIFT "
                    f"expected={expected.get('manifest_checksum')} "
                    f"actual={manifest.get('manifest_checksum')}",
                    file=sys.stderr,
                )
                return 2
            print(f"BASELINE_VERIFIED checksum={manifest['manifest_checksum']}")
            return 0
        write_manifest(args.output, manifest)
        print(f"BASELINE_CAPTURED path={args.output} checksum={manifest['manifest_checksum']}")
        return 0
    except Exception as exc:
        print(f"BASELINE_CAPTURE_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
