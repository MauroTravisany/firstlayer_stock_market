"""Persistence and fail-closed visibility rules for Strategy Brain WP-02."""

from __future__ import annotations

import json

from experiment_identity import (
    ALLOWED_TRANSITIONS,
    HEX64,
    RegistryAdapterError,
    build_snapshot_id,
    snapshot_content_checksum,
    sha256_value,
)


def _insert(client, table, rows, *, row_ids=None):
    errors = client.insert_rows_json(table, rows, row_ids=row_ids)
    if errors:
        raise RegistryAdapterError(f"could not insert into {table}: {errors}")


def _query(client, sql, legacy, parameters=()):
    job_config = legacy.bigquery.QueryJobConfig(query_parameters=list(parameters))
    return client.query(sql, job_config=job_config).result()


def _experiment_for_run(client, config, legacy, run_id):
    sql = f"""
      SELECT *
      FROM `{config['audit_runs_table']}`
      WHERE run_id = @run_id
      ORDER BY created_at DESC
      LIMIT 2
    """
    rows = [
        dict(row.items())
        for row in _query(
            client,
            sql,
            legacy,
            [legacy.bigquery.ScalarQueryParameter("run_id", "STRING", run_id)],
        )
    ]
    if len(rows) > 1:
        raise RegistryAdapterError(
            f"run_id resolves to multiple experiments: {run_id}"
        )
    return rows[0] if rows else None


def _set_run_status(
    client,
    config,
    legacy,
    context,
    status,
    *,
    hypothesis_count=None,
    results_checksum=None,
    failure_reason=None,
    completed=False,
):
    current = _experiment_for_run(client, config, legacy, context["run_id"])
    if not current or current["experiment_id"] != context["experiment_id"]:
        raise RegistryAdapterError(
            "experiment status update could not resolve one run"
        )
    current_status = current["status"]
    if current_status != status and status not in ALLOWED_TRANSITIONS.get(
        current_status, set()
    ):
        raise RegistryAdapterError(
            f"invalid experiment transition: {current_status} -> {status}"
        )
    if current_status in {"COMPLETED", "REJECTED", "FAILED", "CANCELLED"}:
        expected_values = {
            "hypothesis_count": hypothesis_count,
            "results_checksum": results_checksum,
            "failure_reason": failure_reason,
        }
        changed = [
            field
            for field, value in expected_values.items()
            if value is not None and current.get(field) != value
        ]
        if changed:
            raise RegistryAdapterError(
                "terminal experiment state is immutable: " + ",".join(changed)
            )
        if completed and not current.get("completed_at"):
            raise RegistryAdapterError(
                "terminal experiment is missing its completion timestamp"
            )
        return
    sql = f"""
      UPDATE `{config['audit_runs_table']}`
      SET status = @status,
          hypothesis_count = COALESCE(@hypothesis_count, hypothesis_count),
          results_checksum = COALESCE(@results_checksum, results_checksum),
          failure_reason = COALESCE(@failure_reason, failure_reason),
          completed_at = IF(@completed, CURRENT_TIMESTAMP(), completed_at)
      WHERE experiment_id = @experiment_id AND run_id = @run_id
    """
    parameters = [
        legacy.bigquery.ScalarQueryParameter("status", "STRING", status),
        legacy.bigquery.ScalarQueryParameter(
            "hypothesis_count", "INT64", hypothesis_count
        ),
        legacy.bigquery.ScalarQueryParameter(
            "results_checksum", "STRING", results_checksum
        ),
        legacy.bigquery.ScalarQueryParameter(
            "failure_reason", "STRING", failure_reason
        ),
        legacy.bigquery.ScalarQueryParameter("completed", "BOOL", completed),
        legacy.bigquery.ScalarQueryParameter(
            "experiment_id", "STRING", context["experiment_id"]
        ),
        legacy.bigquery.ScalarQueryParameter(
            "run_id", "STRING", context["run_id"]
        ),
    ]
    _query(client, sql, legacy, parameters)
    updated = _experiment_for_run(client, config, legacy, context["run_id"])
    if (
        not updated
        or updated.get("experiment_id") != context["experiment_id"]
        or updated.get("status") != status
    ):
        raise RegistryAdapterError(
            "experiment status update was not persisted exactly"
        )
    if hypothesis_count is not None and int(
        updated.get("hypothesis_count") or 0
    ) != int(hypothesis_count):
        raise RegistryAdapterError(
            "experiment hypothesis count update was not persisted"
        )
    if (
        results_checksum is not None
        and updated.get("results_checksum") != results_checksum
    ):
        raise RegistryAdapterError(
            "experiment result checksum update was not persisted"
        )
    if failure_reason is not None and updated.get("failure_reason") != failure_reason:
        raise RegistryAdapterError(
            "experiment failure reason update was not persisted"
        )
    if completed and not updated.get("completed_at"):
        raise RegistryAdapterError(
            "experiment completion timestamp was not persisted"
        )


def validate_snapshot_row(row, context):
    if not row:
        raise RegistryAdapterError(
            f"data snapshot does not exist: {context['data_snapshot_id']}"
        )
    checks = {
        "snapshot_status": row.get("snapshot_status") == "PUBLISHED",
        "quality_gate_status": row.get("quality_gate_status") == "PASS",
        "immutable": row.get("immutable") is True,
        "production_change_allowed": (
            row.get("production_change_allowed") is False
        ),
        "data_contract_version": (
            row.get("data_contract_version") == context["data_contract_version"]
        ),
        "contract_set_hash": (
            row.get("contract_set_hash") == context["contract_set_hash"]
        ),
        "schema_snapshot_hash": (
            row.get("schema_snapshot_hash") == context["schema_snapshot_hash"]
        ),
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise RegistryAdapterError(
            "data snapshot is not eligible: " + ",".join(failed)
        )
    checksum = str(row.get("content_checksum") or "")
    if not HEX64.fullmatch(checksum):
        raise RegistryAdapterError("data snapshot content checksum is invalid")
    source_hash = str(row.get("source_manifest_hash") or "")
    if not HEX64.fullmatch(source_hash):
        raise RegistryAdapterError(
            "data snapshot source manifest hash is invalid"
        )
    try:
        source_manifest = json.loads(str(row.get("source_manifest_json") or ""))
    except (TypeError, json.JSONDecodeError) as exc:
        raise RegistryAdapterError(
            "data snapshot source manifest JSON is invalid"
        ) from exc
    if sha256_value(source_manifest) != source_hash:
        raise RegistryAdapterError("data snapshot source manifest hash mismatch")
    try:
        quality_gate = json.loads(str(row.get("quality_gate_json") or ""))
    except (TypeError, json.JSONDecodeError) as exc:
        raise RegistryAdapterError(
            "data snapshot quality gate JSON is invalid"
        ) from exc
    if quality_gate.get("status") != "PASS":
        raise RegistryAdapterError(
            "data snapshot quality gate evidence is not PASS"
        )
    expected_id = build_snapshot_id(
        context["contract_set_hash"],
        context["schema_snapshot_hash"],
        row.get("source_cutoff_at"),
        source_hash,
    )
    if expected_id != context["data_snapshot_id"] or expected_id != row.get(
        "data_snapshot_id"
    ):
        raise RegistryAdapterError(
            "data snapshot content-addressed identity mismatch"
        )
    expected_checksum = snapshot_content_checksum(
        expected_id,
        context["contract_set_hash"],
        context["schema_snapshot_hash"],
        row.get("source_cutoff_at"),
        source_hash,
    )
    if checksum != expected_checksum:
        raise RegistryAdapterError("data snapshot content checksum mismatch")
    return checksum


def _validate_snapshot(client, config, legacy, context):
    sql = f"""
      SELECT *
      FROM `{config['audit_snapshots_table']}`
      WHERE data_snapshot_id = @data_snapshot_id
      LIMIT 2
    """
    rows = [
        dict(row.items())
        for row in _query(
            client,
            sql,
            legacy,
            [
                legacy.bigquery.ScalarQueryParameter(
                    "data_snapshot_id", "STRING", context["data_snapshot_id"]
                )
            ],
        )
    ]
    if len(rows) != 1:
        raise RegistryAdapterError(
            "data snapshot identity must resolve to exactly one row"
        )
    context["data_snapshot_checksum"] = validate_snapshot_row(rows[0], context)


def _resolve_parent_experiment(client, config, legacy, context):
    if context["parent_run_id"] is None:
        return
    parent = _experiment_for_run(client, config, legacy, context["parent_run_id"])
    if not parent:
        raise RegistryAdapterError("parent_run_id has no audit experiment")
    if parent["status"] != "COMPLETED":
        raise RegistryAdapterError("parent experiment must be COMPLETED")
    if parent["strategy_version"] != context["strategy_version"]:
        raise RegistryAdapterError("parent experiment strategy version mismatch")
    if parent["universe_version"] != context["universe_version"]:
        raise RegistryAdapterError("parent experiment universe version mismatch")
    context["parent_experiment_id"] = parent["experiment_id"]


def _ensure_experiment_identity_available(client, config, legacy, context):
    sql = f"""
      SELECT COUNT(*) AS row_count
      FROM `{config['audit_runs_table']}`
      WHERE experiment_id = @experiment_id OR run_id = @run_id
    """
    parameters = [
        legacy.bigquery.ScalarQueryParameter(
            "experiment_id", "STRING", context["experiment_id"]
        ),
        legacy.bigquery.ScalarQueryParameter(
            "run_id", "STRING", context["run_id"]
        ),
    ]
    rows = [dict(row.items()) for row in _query(client, sql, legacy, parameters)]
    if not rows or int(rows[0].get("row_count") or 0) != 0:
        raise RegistryAdapterError("experiment_id or run_id already exists")


def _insert_experiment(client, config, context):
    cfg = context["configuration"]
    row = {
        "experiment_id": context["experiment_id"],
        "run_id": context["run_id"],
        "parent_experiment_id": context["parent_experiment_id"],
        "created_at": context["created_at"],
        "status": "CREATED",
        "hypothesis": context["hypothesis"],
        "git_sha": context["git_sha"],
        "image_digest": context["image_digest"],
        "dataform_compilation_id": context["dataform_compilation_id"],
        "environment": context["environment"],
        "data_contract_version": context["data_contract_version"],
        "contract_set_hash": context["contract_set_hash"],
        "schema_snapshot_hash": context["schema_snapshot_hash"],
        "data_snapshot_id": context["data_snapshot_id"],
        "data_snapshot_checksum": context["data_snapshot_checksum"],
        "universe_version": context["universe_version"],
        "feature_set_version": context["feature_set_version"],
        "strategy_version": context["strategy_version"],
        "execution_model_version": context["execution_model_version"],
        "cost_model_version": context["cost_model_version"],
        "configuration_json": context["configuration_json"],
        "configuration_hash": context["configuration_hash"],
        "dependency_lock_hash": context["dependency_lock_hash"],
        "random_seed": context["random_seed"],
        "train_start": cfg["training_start"],
        "train_end": cfg["training_end"],
        "validation_start": cfg["validation_start"],
        "validation_end": cfg["validation_end"],
        "test_start": None,
        "test_end": None,
        "hypothesis_count": context["hypothesis_count"],
        "production_change_allowed": False,
        "results_checksum": None,
        "completed_at": None,
        "failure_reason": None,
    }
    _insert(
        client,
        config["audit_runs_table"],
        [row],
        row_ids=[f"{context['experiment_id']}:{context['run_id']}"],
    )
