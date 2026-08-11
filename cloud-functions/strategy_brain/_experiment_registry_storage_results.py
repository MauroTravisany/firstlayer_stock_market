"""Result and audit-link persistence helpers for WP-02."""

import json

from experiment_identity import RegistryAdapterError, sha256_value
from _experiment_registry_storage_core import _query


def candidate_rows_for_audit(client, config, legacy, run_id):
    sql = (
        f"SELECT * FROM `{config['candidates_table']}` "
        "WHERE run_id = @run_id ORDER BY candidate_id"
    )
    return [
        dict(row.items())
        for row in _query(
            client,
            sql,
            legacy,
            [legacy.bigquery.ScalarQueryParameter("run_id", "STRING", run_id)],
        )
    ]


def candidate_results_for_audit(client, config, legacy, run_id):
    sql = f"""
      SELECT candidate_id, TO_JSON_STRING(ARRAY_AGG(STRUCT(
        strategy_version, evaluation_split, closed_trades, ticker_count, wins, losses,
        win_rate_pct, net_pnl_clp, avg_net_pnl_clp, profit_factor, pnl_p05_clp,
        avg_net_return_pct, initial_capital_clp, final_capital_clp, final_return_pct,
        max_drawdown_clp, max_drawdown_pct, mechanical_verdict
      ) ORDER BY evaluation_split, strategy_version)) AS result_json
      FROM `{config['summary_table']}`
      WHERE run_id = @run_id
      GROUP BY candidate_id
      ORDER BY candidate_id
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
    result = {}
    for row in rows:
        try:
            result[row["candidate_id"]] = json.loads(row["result_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise RegistryAdapterError(
                "candidate result JSON is invalid"
            ) from exc
    return result


def _complete_audit_candidates(
    client, config, legacy, context, candidates, results
):
    candidate_ids = {row["candidate_id"] for row in candidates}
    if candidate_ids != set(results):
        raise RegistryAdapterError(
            "candidate results do not cover the complete experiment candidate set"
        )
    completed = []
    for candidate_id in sorted(candidate_ids):
        checksum = sha256_value(results[candidate_id])
        sql = f"""
          UPDATE `{config['audit_candidates_table']}`
          SET candidate_status = 'COMPLETED', result_checksum = @checksum,
              completed_at = CURRENT_TIMESTAMP()
          WHERE experiment_id = @experiment_id AND run_id = @run_id
            AND candidate_id = @candidate_id AND candidate_status = 'CREATED'
        """
        parameters = [
            legacy.bigquery.ScalarQueryParameter(
                "checksum", "STRING", checksum
            ),
            legacy.bigquery.ScalarQueryParameter(
                "experiment_id", "STRING", context["experiment_id"]
            ),
            legacy.bigquery.ScalarQueryParameter(
                "run_id", "STRING", context["run_id"]
            ),
            legacy.bigquery.ScalarQueryParameter(
                "candidate_id", "STRING", candidate_id
            ),
        ]
        _query(client, sql, legacy, parameters)
        completed.append(
            {
                "candidate_id": candidate_id,
                "result_checksum": checksum,
                "result": results[candidate_id],
            }
        )
    verify_sql = f"""
      SELECT COUNT(*) AS candidate_count,
             COUNTIF(candidate_status = 'COMPLETED'
                     AND result_checksum IS NOT NULL
                     AND completed_at IS NOT NULL) AS completed_count
      FROM `{config['audit_candidates_table']}`
      WHERE experiment_id = @experiment_id AND run_id = @run_id
    """
    verify_parameters = [
        legacy.bigquery.ScalarQueryParameter(
            "experiment_id", "STRING", context["experiment_id"]
        ),
        legacy.bigquery.ScalarQueryParameter(
            "run_id", "STRING", context["run_id"]
        ),
    ]
    rows = [
        dict(row.items())
        for row in _query(client, verify_sql, legacy, verify_parameters)
    ]
    expected = len(candidate_ids)
    if (
        len(rows) != 1
        or int(rows[0].get("candidate_count") or 0) != expected
        or int(rows[0].get("completed_count") or 0) != expected
    ):
        raise RegistryAdapterError(
            "audit candidate completion did not cover the complete experiment"
        )
    return completed


def link_audit_to_experiment(client, config, legacy, context, run_id):
    sql = f"""
      UPDATE `{config['audits_table']}`
      SET experiment_id = @experiment_id
      WHERE run_id = @run_id AND experiment_id IS NULL
    """
    parameters = [
        legacy.bigquery.ScalarQueryParameter(
            "experiment_id", "STRING", context["experiment_id"]
        ),
        legacy.bigquery.ScalarQueryParameter("run_id", "STRING", run_id),
    ]
    _query(client, sql, legacy, parameters)
    verify_sql = f"""
      SELECT COUNT(*) AS total_count,
             COUNTIF(experiment_id = @experiment_id) AS linked_count
      FROM `{config['audits_table']}`
      WHERE run_id = @run_id
    """
    rows = [
        dict(row.items())
        for row in _query(client, verify_sql, legacy, parameters)
    ]
    if (
        len(rows) != 1
        or int(rows[0].get("total_count") or 0) < 1
        or int(rows[0].get("linked_count") or 0)
        != int(rows[0].get("total_count") or 0)
    ):
        raise RegistryAdapterError(
            "operational audit lineage was not linked completely"
        )
