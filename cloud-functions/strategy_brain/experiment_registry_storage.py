"""WP-02 persistence and audit-record helpers for Strategy Brain."""

from __future__ import annotations

import json

from experiment_identity import (
    ALLOWED_TRANSITIONS,
    CANDIDATE_ID,
    HEX64,
    RegistryAdapterError,
    build_candidate_id,
    candidate_configuration,
    canonical_json,
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
      SELECT experiment_id, run_id, status, strategy_version, universe_version
      FROM `{config['audit_runs_table']}`
      WHERE run_id = @run_id
      ORDER BY created_at DESC
      LIMIT 2
    """
    params = [legacy.bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
    rows = [dict(row.items()) for row in _query(client, sql, legacy, params)]
    if len(rows) > 1:
        raise RegistryAdapterError(f"run_id resolves to multiple experiments: {run_id}")
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
    completed=False,
):
    current = _experiment_for_run(client, config, legacy, context["run_id"])
    if not current or current["experiment_id"] != context["experiment_id"]:
        raise RegistryAdapterError("experiment status update could not resolve one run")
    current_status = current["status"]
    if current_status != status and status not in ALLOWED_TRANSITIONS.get(
        current_status, set()
    ):
        raise RegistryAdapterError(
            f"invalid experiment transition: {current_status} -> {status}"
        )
    sql = f"""
      UPDATE `{config['audit_runs_table']}`
      SET status = @status,
          hypothesis_count = COALESCE(@hypothesis_count, hypothesis_count),
          results_checksum = COALESCE(@results_checksum, results_checksum),
          completed_at = IF(@completed, CURRENT_TIMESTAMP(), completed_at)
      WHERE experiment_id = @experiment_id AND run_id = @run_id
    """
    params = [
        legacy.bigquery.ScalarQueryParameter("status", "STRING", status),
        legacy.bigquery.ScalarQueryParameter(
            "hypothesis_count", "INT64", hypothesis_count
        ),
        legacy.bigquery.ScalarQueryParameter(
            "results_checksum", "STRING", results_checksum
        ),
        legacy.bigquery.ScalarQueryParameter("completed", "BOOL", completed),
        legacy.bigquery.ScalarQueryParameter(
            "experiment_id", "STRING", context["experiment_id"]
        ),
        legacy.bigquery.ScalarQueryParameter("run_id", "STRING", context["run_id"]),
    ]
    _query(client, sql, legacy, params)


def validate_snapshot_row(row, context):
    if not row:
        raise RegistryAdapterError(
            f"data snapshot does not exist: {context['data_snapshot_id']}"
        )
    if row.get("snapshot_status") != "PUBLISHED":
        raise RegistryAdapterError("data snapshot is not PUBLISHED")
    if row.get("immutable") is not True:
        raise RegistryAdapterError("data snapshot is not immutable")
    if row.get("data_contract_version") != context["data_contract_version"]:
        raise RegistryAdapterError("data snapshot contract version mismatch")
    if row.get("contract_set_hash") != context["contract_set_hash"]:
        raise RegistryAdapterError("data snapshot contract-set hash mismatch")
    if row.get("schema_snapshot_hash") != context["schema_snapshot_hash"]:
        raise RegistryAdapterError("data snapshot schema hash mismatch")
    checksum = str(row.get("content_checksum") or "")
    if not HEX64.fullmatch(checksum):
        raise RegistryAdapterError("data snapshot content checksum is invalid")
    return checksum


def _validate_snapshot(client, config, legacy, context):
    sql = f"""
      SELECT
        data_snapshot_id,
        data_contract_version,
        contract_set_hash,
        schema_snapshot_hash,
        snapshot_status,
        immutable,
        content_checksum
      FROM `{config['audit_snapshots_table']}`
      WHERE data_snapshot_id = @data_snapshot_id
      LIMIT 2
    """
    params = [
        legacy.bigquery.ScalarQueryParameter(
            "data_snapshot_id", "STRING", context["data_snapshot_id"]
        )
    ]
    rows = [dict(row.items()) for row in _query(client, sql, legacy, params)]
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
    params = [
        legacy.bigquery.ScalarQueryParameter(
            "experiment_id", "STRING", context["experiment_id"]
        ),
        legacy.bigquery.ScalarQueryParameter("run_id", "STRING", context["run_id"]),
    ]
    rows = [dict(row.items()) for row in _query(client, sql, legacy, params)]
    if not rows or int(rows[0].get("row_count") or 0) != 0:
        raise RegistryAdapterError("experiment_id or run_id already exists")


def _insert_experiment(client, config, context):
    configuration = context["configuration"]
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
        "train_start": configuration["training_start"],
        "train_end": configuration["training_end"],
        "validation_start": configuration["validation_start"],
        "validation_end": configuration["validation_end"],
        "test_start": None,
        "test_end": None,
        "hypothesis_count": context["hypothesis_count"],
        "production_change_allowed": False,
        "results_checksum": None,
        "completed_at": None,
    }
    _insert(
        client,
        config["audit_runs_table"],
        [row],
        row_ids=[f"{context['experiment_id']}:{context['run_id']}"],
    )


def _link_operational_run(client, config, legacy, context):
    sql = f"""
      UPDATE `{config['runs_table']}`
      SET experiment_id = @experiment_id,
          parent_experiment_id = @parent_experiment_id,
          environment = @environment,
          data_contract_version = @data_contract_version,
          contract_set_hash = @contract_set_hash,
          data_snapshot_id = @data_snapshot_id,
          data_snapshot_checksum = @data_snapshot_checksum,
          configuration_hash = @configuration_hash,
          dependency_lock_hash = @dependency_lock_hash,
          feature_set_version = @feature_set_version,
          execution_model_version = @execution_model_version,
          cost_model_version = @cost_model_version,
          hypothesis_count = @hypothesis_count
      WHERE run_id = @run_id
    """
    values = [
        ("experiment_id", "STRING", context["experiment_id"]),
        ("parent_experiment_id", "STRING", context["parent_experiment_id"]),
        ("environment", "STRING", context["environment"]),
        ("data_contract_version", "STRING", context["data_contract_version"]),
        ("contract_set_hash", "STRING", context["contract_set_hash"]),
        ("data_snapshot_id", "STRING", context["data_snapshot_id"]),
        ("data_snapshot_checksum", "STRING", context["data_snapshot_checksum"]),
        ("configuration_hash", "STRING", context["configuration_hash"]),
        ("dependency_lock_hash", "STRING", context["dependency_lock_hash"]),
        ("feature_set_version", "STRING", context["feature_set_version"]),
        ("execution_model_version", "STRING", context["execution_model_version"]),
        ("cost_model_version", "STRING", context["cost_model_version"]),
        ("hypothesis_count", "INT64", context["hypothesis_count"]),
        ("run_id", "STRING", context["run_id"]),
    ]
    params = [legacy.bigquery.ScalarQueryParameter(*value) for value in values]
    _query(client, sql, legacy, params)


def _audit_candidate_rows(context, candidates):
    rows = []
    for index, candidate in enumerate(candidates, start=1):
        configuration = candidate_configuration(candidate)
        rows.append(
            {
                "experiment_id": context["experiment_id"],
                "run_id": context["run_id"],
                "candidate_id": candidate["candidate_id"],
                "generation": int(candidate.get("generation") or 1),
                "hypothesis_index": index,
                "parent_candidate_id": candidate.get("parent_candidate_id"),
                "candidate_status": "CREATED",
                "configuration_json": canonical_json(configuration),
                "configuration_hash": sha256_value(configuration),
                "production_change_allowed": False,
                "created_at": candidate["created_at"],
                "completed_at": None,
                "result_checksum": None,
            }
        )
    return rows


def rewrite_candidate_rows(records, context):
    rewritten = []
    for index, original in enumerate(records, start=1):
        record = dict(original)
        configuration = candidate_configuration(record)
        record["experiment_id"] = context["experiment_id"]
        record["configuration_hash"] = sha256_value(configuration)
        record["hypothesis_index"] = index
        record["candidate_id"] = build_candidate_id(
            context["experiment_id"],
            context["run_id"],
            int(record.get("generation") or 1),
            record.get("parent_candidate_id"),
            configuration,
        )
        rewritten.append(record)
    ids = [record["candidate_id"] for record in rewritten]
    if len(ids) != len(set(ids)):
        raise RegistryAdapterError("candidate ID collision inside experiment")
    return rewritten


def _table_ddl_extensions(config):
    columns = {
        config["runs_table"]: [
            ("experiment_id", "STRING"),
            ("parent_experiment_id", "STRING"),
            ("environment", "STRING"),
            ("data_contract_version", "STRING"),
            ("contract_set_hash", "STRING"),
            ("data_snapshot_id", "STRING"),
            ("data_snapshot_checksum", "STRING"),
            ("configuration_hash", "STRING"),
            ("dependency_lock_hash", "STRING"),
            ("feature_set_version", "STRING"),
            ("execution_model_version", "STRING"),
            ("cost_model_version", "STRING"),
            ("hypothesis_count", "INT64"),
        ],
        config["candidates_table"]: [
            ("experiment_id", "STRING"),
            ("configuration_hash", "STRING"),
            ("hypothesis_index", "INT64"),
        ],
        config["audits_table"]: [("experiment_id", "STRING")],
    }
    return [
        f"ALTER TABLE `{table}` ADD COLUMN IF NOT EXISTS {name} {type_name}"
        for table, definitions in columns.items()
        for name, type_name in definitions
    ]


def candidate_rows_for_audit(client, config, legacy, run_id):
    sql = f"""
      SELECT *
      FROM `{config['candidates_table']}`
      WHERE run_id = @run_id
      ORDER BY candidate_id
    """
    params = [legacy.bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
    return [dict(row.items()) for row in _query(client, sql, legacy, params)]


def candidate_results_for_audit(client, config, legacy, run_id):
    sql = f"""
      SELECT
        candidate_id,
        TO_JSON_STRING(ARRAY_AGG(STRUCT(
          strategy_version,
          evaluation_split,
          closed_trades,
          ticker_count,
          wins,
          losses,
          win_rate_pct,
          net_pnl_clp,
          avg_net_pnl_clp,
          profit_factor,
          pnl_p05_clp,
          avg_net_return_pct,
          initial_capital_clp,
          final_capital_clp,
          final_return_pct,
          max_drawdown_clp,
          max_drawdown_pct,
          mechanical_verdict
        ) ORDER BY evaluation_split, strategy_version)) AS result_json
      FROM `{config['summary_table']}`
      WHERE run_id = @run_id
      GROUP BY candidate_id
      ORDER BY candidate_id
    """
    params = [legacy.bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
    rows = [dict(row.items()) for row in _query(client, sql, legacy, params)]
    results = {}
    for row in rows:
        try:
            parsed = json.loads(row["result_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise RegistryAdapterError("candidate result JSON is invalid") from exc
        results[row["candidate_id"]] = parsed
    return results


def _complete_audit_candidates(client, config, legacy, context, candidates, results):
    candidate_ids = {row["candidate_id"] for row in candidates}
    if candidate_ids != set(results):
        raise RegistryAdapterError(
            "candidate results do not cover the complete experiment candidate set"
        )
    completed = []
    for candidate_id in sorted(candidate_ids):
        result = results[candidate_id]
        checksum = sha256_value(result)
        sql = f"""
          UPDATE `{config['audit_candidates_table']}`
          SET candidate_status = "COMPLETED",
              result_checksum = @result_checksum,
              completed_at = CURRENT_TIMESTAMP()
          WHERE experiment_id = @experiment_id
            AND run_id = @run_id
            AND candidate_id = @candidate_id
        """
        params = [
            legacy.bigquery.ScalarQueryParameter(
                "result_checksum", "STRING", checksum
            ),
            legacy.bigquery.ScalarQueryParameter(
                "experiment_id", "STRING", context["experiment_id"]
            ),
            legacy.bigquery.ScalarQueryParameter("run_id", "STRING", context["run_id"]),
            legacy.bigquery.ScalarQueryParameter(
                "candidate_id", "STRING", candidate_id
            ),
        ]
        _query(client, sql, legacy, params)
        completed.append(
            {
                "candidate_id": candidate_id,
                "result_checksum": checksum,
                "result": result,
            }
        )
    return completed


def link_audit_to_experiment(client, config, legacy, context, run_id):
    sql = f"""
      UPDATE `{config['audits_table']}`
      SET experiment_id = @experiment_id
      WHERE run_id = @run_id AND experiment_id IS NULL
    """
    params = [
        legacy.bigquery.ScalarQueryParameter(
            "experiment_id", "STRING", context["experiment_id"]
        ),
        legacy.bigquery.ScalarQueryParameter("run_id", "STRING", run_id),
    ]
    _query(client, sql, legacy, params)


