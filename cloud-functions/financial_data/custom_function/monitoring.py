from datetime import datetime, timezone

import requests
from google.cloud import bigquery


DISCORD_RED = 0xE74C3C
DISCORD_GOLD = 0xF1C40F


def _table_ref(table):
    return f"`{table}`"


def ensure_quality_table(config):
    client = bigquery.Client(project=config["project_id"])
    sql = f"""
    CREATE TABLE IF NOT EXISTS {_table_ref(config["quality_table"])} (
      run_date DATE NOT NULL,
      pipeline STRING NOT NULL,
      ticker STRING NOT NULL,
      data_status STRING NOT NULL,
      severity STRING NOT NULL,
      rows_loaded INT64,
      message STRING,
      created_at TIMESTAMP NOT NULL
    )
    PARTITION BY run_date
    CLUSTER BY pipeline, severity, ticker
    """
    client.query(sql).result()


def persist_quality_events(config, pipeline, run_date, results):
    ensure_quality_table(config)
    client = bigquery.Client(project=config["project_id"])
    now = datetime.now(timezone.utc).isoformat()
    for result in results:
        row = {
            "run_date": str(run_date),
            "pipeline": pipeline,
            "ticker": result.get("ticker"),
            "data_status": result.get("data_status") or result.get("status", "unknown"),
            "severity": result.get("severity") or ("ERROR" if result.get("status") == "error" else "OK"),
            "rows_loaded": result.get("rows_loaded"),
            "message": result.get("message"),
            "created_at": now,
        }
        sql = f"""
        MERGE {_table_ref(config["quality_table"])} T
        USING (
          SELECT
            @run_date AS run_date,
            @pipeline AS pipeline,
            @ticker AS ticker,
            @data_status AS data_status,
            @severity AS severity,
            @rows_loaded AS rows_loaded,
            @message AS message,
            @created_at AS created_at
        ) S
        ON T.run_date = S.run_date
          AND T.pipeline = S.pipeline
          AND T.ticker = S.ticker
        WHEN MATCHED THEN UPDATE SET
          data_status = S.data_status,
          severity = S.severity,
          rows_loaded = S.rows_loaded,
          message = S.message,
          created_at = S.created_at
        WHEN NOT MATCHED THEN INSERT ROW
        """
        params = [
            bigquery.ScalarQueryParameter("run_date", "DATE", row["run_date"]),
            bigquery.ScalarQueryParameter("pipeline", "STRING", row["pipeline"]),
            bigquery.ScalarQueryParameter("ticker", "STRING", row["ticker"]),
            bigquery.ScalarQueryParameter("data_status", "STRING", row["data_status"]),
            bigquery.ScalarQueryParameter("severity", "STRING", row["severity"]),
            bigquery.ScalarQueryParameter("rows_loaded", "INT64", row["rows_loaded"]),
            bigquery.ScalarQueryParameter("message", "STRING", row["message"]),
            bigquery.ScalarQueryParameter("created_at", "TIMESTAMP", row["created_at"]),
        ]
        client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


def _detect_webhook_type(config):
    webhook_type = config.get("alert_webhook_type") or "auto"
    url = config.get("alert_webhook_url") or ""
    if webhook_type != "auto":
        return webhook_type
    if "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
        return "discord"
    return "slack"


def _problem_rows(results):
    return [row for row in results if row.get("severity") in {"ERROR", "WARNING"} or row.get("status") == "error"]


def send_quality_alert(config, pipeline, run_date, results):
    url = config.get("alert_webhook_url")
    problems = _problem_rows(results)
    if not url or not problems:
        return False, None

    title = f"Alerta de datos Yahoo - {pipeline} - {run_date}"
    lines = []
    for row in problems[:15]:
        lines.append(
            "- {ticker}: {severity} / {status}. {message}".format(
                ticker=row.get("ticker"),
                severity=row.get("severity") or "ERROR",
                status=row.get("data_status") or row.get("status"),
                message=row.get("message") or "Sin detalle.",
            )
        )

    webhook_type = _detect_webhook_type(config)
    if webhook_type == "discord":
        payload = {
            "embeds": [
                {
                    "title": title,
                    "description": "\n".join(lines),
                    "color": DISCORD_RED if any(row.get("severity") == "ERROR" for row in problems) else DISCORD_GOLD,
                    "footer": {"text": "El analisis puede quedar parcial si faltan precios o ratios."},
                }
            ]
        }
    else:
        payload = {"text": f"*{title}*\n" + "\n".join(lines)}

    response = requests.post(url, json=payload, timeout=30)
    if response.status_code >= 300:
        return False, f"Webhook error {response.status_code}: {response.text}"
    return True, None


def quality_summary(results):
    total = len(results)
    errors = len([row for row in results if row.get("severity") == "ERROR" or row.get("status") == "error"])
    warnings = len([row for row in results if row.get("severity") == "WARNING"])
    ok = total - errors - warnings
    return {"total": total, "ok": ok, "warnings": warnings, "errors": errors}
