"""Candidate persistence and visibility helpers for WP-02."""

from experiment_identity import (
    RegistryAdapterError,
    build_candidate_id,
    candidate_configuration,
    canonical_json,
    sha256_value,
)
from _experiment_registry_storage_core import _query


def rewrite_candidate_rows(records, context):
    rewritten = []
    for index, original in enumerate(records, start=1):
        record = dict(original)
        configuration = candidate_configuration(record)
        record.update(
            {
                "experiment_id": context["experiment_id"],
                "configuration_hash": sha256_value(configuration),
                "hypothesis_index": index,
                "candidate_status": "REGISTRY_PENDING",
                "production_change_allowed": False,
                "candidate_id": build_candidate_id(
                    context["experiment_id"],
                    context["run_id"],
                    int(record.get("generation") or 1),
                    record.get("parent_candidate_id"),
                    configuration,
                ),
            }
        )
        rewritten.append(record)
    ids = [row["candidate_id"] for row in rewritten]
    if len(ids) != len(set(ids)):
        raise RegistryAdapterError("candidate ID collision inside experiment")
    return rewritten


def _audit_candidate_rows(context, candidates):
    rows = []
    for row in candidates:
        configuration = candidate_configuration(row)
        rows.append(
            {
                "experiment_id": context["experiment_id"],
                "run_id": context["run_id"],
                "candidate_id": row["candidate_id"],
                "generation": int(row.get("generation") or 1),
                "hypothesis_index": int(row["hypothesis_index"]),
                "parent_candidate_id": row.get("parent_candidate_id"),
                "candidate_status": "CREATED",
                "configuration_json": canonical_json(configuration),
                "configuration_hash": row["configuration_hash"],
                "production_change_allowed": False,
                "created_at": row["created_at"],
                "completed_at": None,
                "result_checksum": None,
            }
        )
    return rows


def _link_operational_run(client, config, legacy, context):
    sql = f"""
      UPDATE `{config['runs_table']}`
      SET experiment_id = @experiment_id,
          parent_experiment_id = @parent_experiment_id,
          environment = @environment,
          data_contract_version = @data_contract_version,
          contract_set_hash = @contract_set_hash,
          schema_snapshot_hash = @schema_snapshot_hash,
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
        ("schema_snapshot_hash", "STRING", context["schema_snapshot_hash"]),
        ("data_snapshot_id", "STRING", context["data_snapshot_id"]),
        ("data_snapshot_checksum", "STRING", context["data_snapshot_checksum"]),
        ("configuration_hash", "STRING", context["configuration_hash"]),
        ("dependency_lock_hash", "STRING", context["dependency_lock_hash"]),
        ("feature_set_version", "STRING", context["feature_set_version"]),
        (
            "execution_model_version",
            "STRING",
            context["execution_model_version"],
        ),
        ("cost_model_version", "STRING", context["cost_model_version"]),
        ("hypothesis_count", "INT64", context["hypothesis_count"]),
        ("run_id", "STRING", context["run_id"]),
    ]
    parameters = [legacy.bigquery.ScalarQueryParameter(*value) for value in values]
    _query(client, sql, legacy, parameters)
    verify_sql = f"""
      SELECT COUNT(*) AS row_count
      FROM `{config['runs_table']}`
      WHERE run_id = @run_id
        AND experiment_id = @experiment_id
        AND data_snapshot_id = @data_snapshot_id
        AND configuration_hash = @configuration_hash
    """
    verify_parameters = [
        legacy.bigquery.ScalarQueryParameter(
            "run_id", "STRING", context["run_id"]
        ),
        legacy.bigquery.ScalarQueryParameter(
            "experiment_id", "STRING", context["experiment_id"]
        ),
        legacy.bigquery.ScalarQueryParameter(
            "data_snapshot_id", "STRING", context["data_snapshot_id"]
        ),
        legacy.bigquery.ScalarQueryParameter(
            "configuration_hash", "STRING", context["configuration_hash"]
        ),
    ]
    rows = [
        dict(row.items())
        for row in _query(client, verify_sql, legacy, verify_parameters)
    ]
    if len(rows) != 1 or int(rows[0].get("row_count") or 0) != 1:
        raise RegistryAdapterError(
            "operational run lineage was not linked exactly once"
        )


def _activate_operational_candidates(
    client, config, legacy, context, expected_count
):
    sql = f"""
      UPDATE `{config['candidates_table']}`
      SET candidate_status = 'BACKTEST_ONLY'
      WHERE experiment_id = @experiment_id
        AND run_id = @run_id
        AND candidate_status = 'REGISTRY_PENDING'
        AND production_change_allowed IS FALSE
    """
    parameters = [
        legacy.bigquery.ScalarQueryParameter(
            "experiment_id", "STRING", context["experiment_id"]
        ),
        legacy.bigquery.ScalarQueryParameter(
            "run_id", "STRING", context["run_id"]
        ),
    ]
    _query(client, sql, legacy, parameters)
    verify = f"""
      SELECT COUNTIF(candidate_status = 'BACKTEST_ONLY') AS active_count,
             COUNTIF(candidate_status = 'REGISTRY_PENDING') AS pending_count
      FROM `{config['candidates_table']}`
      WHERE experiment_id = @experiment_id AND run_id = @run_id
    """
    rows = [dict(row.items()) for row in _query(client, verify, legacy, parameters)]
    if (
        len(rows) != 1
        or int(rows[0].get("active_count") or 0) != expected_count
        or int(rows[0].get("pending_count") or 0) != 0
    ):
        raise RegistryAdapterError(
            "operational candidate activation did not match the complete registry set"
        )


def _mark_operational_run_failed(client, config, legacy, context):
    run_parameter = legacy.bigquery.ScalarQueryParameter(
        "run_id", "STRING", context["run_id"]
    )
    _query(
        client,
        f"""
          UPDATE `{config['runs_table']}`
          SET status = 'FAILED'
          WHERE run_id = @run_id
        """,
        legacy,
        [run_parameter],
    )
    _query(
        client,
        f"""
          UPDATE `{config['candidates_table']}`
          SET candidate_status = 'REGISTRY_FAILED'
          WHERE run_id = @run_id
            AND experiment_id = @experiment_id
            AND candidate_status IN ('REGISTRY_PENDING', 'BACKTEST_ONLY')
        """,
        legacy,
        [
            run_parameter,
            legacy.bigquery.ScalarQueryParameter(
                "experiment_id", "STRING", context["experiment_id"]
            ),
        ],
    )


def _table_ddl_extensions(config):
    columns = {
        config["runs_table"]: [
            ("experiment_id", "STRING"),
            ("parent_experiment_id", "STRING"),
            ("environment", "STRING"),
            ("data_contract_version", "STRING"),
            ("contract_set_hash", "STRING"),
            ("schema_snapshot_hash", "STRING"),
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
            ("production_change_allowed", "BOOL"),
        ],
        config["audits_table"]: [("experiment_id", "STRING")],
    }
    return [
        f"ALTER TABLE `{table}` ADD COLUMN IF NOT EXISTS {name} {type_name}"
        for table, definitions in columns.items()
        for name, type_name in definitions
    ]
