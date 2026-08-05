import os

from google.cloud import secretmanager


def access_secret_version(secret_id, version_id="latest", required=True):
    project_id = os.environ.get("PROJECT_ID")
    if not project_id:
        raise RuntimeError("PROJECT_ID environment variable is required")

    env_value = os.environ.get(secret_id)
    if env_value:
        return env_value.strip()

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
    try:
        response = client.access_secret_version(name=name)
        return response.payload.data.decode("UTF-8").strip()
    except Exception:
        if required:
            raise
        return None


def load_config():
    project_id = access_secret_version("project_id")
    dataset_id = access_secret_version("dataset_id")

    return {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "summary_table": f"{project_id}.{dataset_id}.{os.environ.get('TRADING_SUMMARY_TABLE_ID', 'trading_daily_summary')}",
        "signals_table": f"{project_id}.{dataset_id}.{os.environ.get('TRADING_SIGNALS_TABLE_ID', 'trading_paper_signals')}",
        "results_table": f"{project_id}.{dataset_id}.{os.environ.get('TRADING_RESULTS_TABLE_ID', 'trading_paper_trade_results')}",
        "strategy_backtest_table": f"{project_id}.{dataset_id}.{os.environ.get('TRADING_STRATEGY_BACKTEST_TABLE_ID', 'trading_directional_strategy_backtest')}",
        "v5_backtest_table": f"{project_id}.{dataset_id}.{os.environ.get('TRADING_V5_BACKTEST_TABLE_ID', 'trading_v5_high_turnover_portfolio')}",
        "alpaca_executions_table": f"{project_id}.{dataset_id}.{os.environ.get('ALPACA_EXECUTIONS_TABLE_ID', 'trading_alpaca_paper_executions')}",
        "alpaca_positions_table": f"{project_id}.{dataset_id}.{os.environ.get('ALPACA_POSITIONS_TABLE_ID', 'trading_alpaca_paper_positions')}",
        "alerts_table": f"{project_id}.{dataset_id}.{os.environ.get('TRADING_ALERTS_TABLE_ID', 'trading_alerts_sent')}",
        "feedback_table": f"{project_id}.{dataset_id}.{os.environ.get('TRADING_FEEDBACK_TABLE_ID', 'trading_ai_feedback_daily')}",
        "weekly_review_table": f"{project_id}.{dataset_id}.{os.environ.get('TRADING_WEEKLY_REVIEW_TABLE_ID', 'trading_weekly_ai_strategy_review')}",
        "openai_api_key": access_secret_version(os.environ.get("OPENAI_API_KEY_SECRET", "OPENAI_API_KEY"), required=False),
        "openai_model": os.environ.get("OPENAI_MODEL", "gpt-5-mini"),
        "prompt_version": os.environ.get("TRADING_PROMPT_VERSION", "paper-trading-feedback-v1"),
        "ai_feedback_enabled": os.environ.get("TRADING_AI_FEEDBACK", "true").strip().lower() in {"1", "true", "yes", "y", "si"},
        "alert_webhook_url": os.environ.get("ALERT_WEBHOOK_URL")
        or access_secret_version(os.environ.get("ALERT_WEBHOOK_URL_SECRET", "ALERT_WEBHOOK_URL"), required=False),
        "alert_webhook_type": os.environ.get("ALERT_WEBHOOK_TYPE", "auto").lower(),
    }
