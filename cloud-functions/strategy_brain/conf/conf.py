import os

from google.cloud import secretmanager


def access_secret_version(secret_id, required=True):
    project_id = os.environ.get("PROJECT_ID")
    if not project_id:
        raise RuntimeError("PROJECT_ID environment variable is required")

    value = os.environ.get(secret_id)
    if value:
        return value.strip()

    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    try:
        response = secretmanager.SecretManagerServiceClient().access_secret_version(name=name)
        return response.payload.data.decode("utf-8").strip()
    except Exception:
        if required:
            raise
        return None


def load_config():
    project_id = access_secret_version("project_id")
    dataset_id = access_secret_version("dataset_id")
    table_prefix = f"{project_id}.{dataset_id}"
    return {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "runs_table": f"{table_prefix}.trading_brain_runs",
        "candidates_table": f"{table_prefix}.trading_brain_weight_candidates",
        "audits_table": f"{table_prefix}.trading_brain_ai_audits",
        "summary_table": f"{table_prefix}.trading_brain_candidate_summary",
        "variants_table": f"{table_prefix}.trading_backtest_context_variants",
        "audit_snapshots_table": f"{table_prefix}.audit_data_snapshots",
        "audit_runs_table": f"{table_prefix}.audit_experiment_runs",
        "audit_candidates_table": f"{table_prefix}.audit_experiment_candidates",
        "audit_artifacts_table": f"{table_prefix}.audit_experiment_artifacts",
        "audit_decisions_table": f"{table_prefix}.audit_experiment_decisions",
        "environment": os.environ.get("BRAIN_ENVIRONMENT", "shadow").strip().lower(),
        "data_contract_version": os.environ.get(
            "DATA_CONTRACT_VERSION", "audit-contracts-v1"
        ).strip(),
        "feature_set_version": os.environ.get(
            "FEATURE_SET_VERSION", "legacy-feature-set-v1"
        ).strip(),
        "execution_model_version": os.environ.get(
            "EXECUTION_MODEL_VERSION", "legacy-daily-execution-v1"
        ).strip(),
        "cost_model_version": os.environ.get(
            "COST_MODEL_VERSION", "legacy-estimated-cost-v1"
        ).strip(),
        "release_git_sha": os.environ.get("RELEASE_GIT_SHA", "").strip().lower(),
        "release_image_digest": os.environ.get(
            "RELEASE_IMAGE_DIGEST", ""
        ).strip().lower(),
        "dataform_compilation_id": os.environ.get(
            "DATAFORM_COMPILATION_ID", ""
        ).strip(),
        "openai_api_key": access_secret_version(
            os.environ.get("OPENAI_API_KEY_SECRET", "OPENAI_API_KEY"),
            required=False,
        ),
        "openai_model": os.environ.get("OPENAI_MODEL", "gpt-5-mini"),
        "ai_review_enabled": os.environ.get(
            "BRAIN_AI_REVIEW_ENABLED", "true"
        ).strip().lower()
        in {"1", "true", "yes"},
    }
