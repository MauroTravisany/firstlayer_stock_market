"""Read-only aggregate prerequisite audit for the WP-03 BigQuery shadow graph.

The command checks every external operational input in one pass, validates the
isolated shadow dataset boundary, and verifies that the frozen legacy
invalidation is repository-static. It never issues SQL or mutates GCP.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from tools.wp03_shadow_backfill import verify_clean_checkout


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9-]{4,62}$")
DATASET_ID = re.compile(r"^[A-Za-z0-9_]+$")
SHADOW_DATASET_ID = re.compile(
    r"^[A-Za-z0-9_]*shadow[A-Za-z0-9_]*$", re.IGNORECASE
)
ALLOWED_TABLE_TYPES = {"TABLE", "VIEW", "MATERIALIZED_VIEW", "SNAPSHOT"}
WP03_OUTPUTS = (
    "financial_statements_pit_raw",
    "financial_statements_pit",
    "financial_quarters_pit",
    "financial_ttm_pit",
    "earnings_events_pit",
    "trading_financial_context_pit",
    "trading_earnings_context_pit",
    "portfolio_valuation_pit_shadow",
    "trading_historical_context_pit",
    "wp03_legacy_vs_pit_shadow",
    "wp03_legacy_invalidation",
    "audit_no_lookahead",
)
OPERATIONAL_INPUTS: Mapping[str, Mapping[str, Any]] = {
    "macro_earnings_calendar": {
        "consumers": ["earnings_events_pit"],
        "required_columns": [
            "snapshot_date",
            "signal_hour",
            "ticker",
            "earnings_date",
            "earnings_time",
            "eps_estimate",
            "reported_eps",
            "surprise_pct",
            "event_status",
            "source",
            "loaded_at",
        ],
    },
    "trading_price_features": {
        "consumers": [
            "financial_quarters_pit",
            "trading_earnings_context_pit",
            "portfolio_valuation_pit_shadow",
        ],
        "required_columns": [
            "analysis_date",
            "signal_hour",
            "signal_timestamp",
            "ticker",
            "asset_type",
            "previous_close",
        ],
    },
    "asset_profile": {
        "consumers": ["portfolio_valuation_pit_shadow"],
        "required_columns": ["ticker", "sector", "industry", "peer_group"],
    },
    "valuation_model_profile": {
        "consumers": ["portfolio_valuation_pit_shadow"],
        "required_columns": [
            "peer_group",
            "valuation_model",
            "pe_cheap",
            "pe_fair",
            "pe_expensive",
            "pe_extreme",
            "pe_weight",
            "ps_cheap",
            "ps_fair",
            "ps_expensive",
            "ps_extreme",
            "ps_weight",
            "pb_cheap",
            "pb_fair",
            "pb_expensive",
            "pb_extreme",
            "pb_weight",
            "profit_margin_good",
            "profit_margin_bad",
            "profit_margin_weight",
            "operating_margin_good",
            "operating_margin_bad",
            "operating_margin_weight",
        ],
    },
    "trading_historical_context": {
        "consumers": [
            "trading_historical_context_pit",
            "wp03_legacy_vs_pit_shadow",
        ],
        "required_columns": [
            "analysis_date",
            "signal_hour",
            "ticker",
            "asset_type",
            "monetary_regime_proxy",
            "historical_fear_regime",
            "political_regime_proxy",
            "crypto_context_regime",
            "period_end_date",
            "report_date",
            "revenue_yoy",
            "net_margin_asof",
            "fcf_margin_asof",
            "debt_to_equity_asof",
            "company_lifecycle_context",
            "company_status",
            "status_group",
            "classification",
            "risk_level",
            "technical_trend",
            "fundamental_final_score",
            "fundamental_quality_score",
            "fundamental_valuation_score",
            "fundamental_risk_score",
            "earnings_date",
            "days_to_earnings",
            "earnings_event_status",
            "earnings_event_score",
            "earnings_context_note",
            "context_similarity_key",
            "calculated_at",
        ],
    },
    "portfolio_valuation_daily": {
        "consumers": ["wp03_legacy_vs_pit_shadow"],
        "required_columns": [
            "analysis_date",
            "ticker",
            "classification",
            "valuation_score",
        ],
    },
}
FROZEN_AFFECTED_RESULTS = (
    (
        "CURRENT_SHADOW_SIGNALS",
        "trading_champion_challenger_signals",
        "b2e1b74c49e1a266feb79d6a4945b2e45053a099202454af723350772797b87c",
    ),
    (
        "DIRECTIONAL_V1",
        "trading_directional_strategy_backtest",
        "a859f5de90a0009fcd95ed45aba758f3b806cb870ec3dc234035b3fb92dcc9b3",
    ),
    (
        "DIRECTIONAL_V2",
        "trading_directional_strategy_backtest",
        "e6432399a9dabeddfeb381d7168caf082d5cabdbc1995f93f38e078bacdc7763",
    ),
    (
        "DIRECTIONAL_V3",
        "trading_directional_strategy_backtest",
        "4b29478ee8b0d694becce51b464aa7c821cb48b724daa9c79676b8ae31c01aff",
    ),
    (
        "DIRECTIONAL_V4",
        "trading_directional_strategy_backtest",
        "6fc151773989e02c1b45c0b534d6487a0aa676225a6eda4ceed869f968073b8e",
    ),
    (
        "STRATEGY_BRAIN_AUDITS",
        "trading_brain_ai_audits",
        "0fa017b782cf89aac324fcdb158d8888edfd6713994bd9fb4f7e2c4bdca3504b",
    ),
    (
        "STRATEGY_BRAIN_CANDIDATES",
        "trading_brain_weight_candidates",
        "c2e35224d7b095758996071f6566165ff1e51c58b44f6af7fabfada7865125ca",
    ),
    (
        "STRATEGY_BRAIN_CAPITAL_CURVE",
        "trading_brain_candidate_capital_curve",
        "df3926b0b31d5336f6b9421cd9fb9231505cc008a964a64d37ce44d1fe6881d4",
    ),
    (
        "STRATEGY_BRAIN_RUNS",
        "trading_brain_runs",
        "7a9c93a277b470212632c022034b0a0a512a98881fc154b6ca6c78ef7aff4864",
    ),
    (
        "STRATEGY_BRAIN_SUMMARY",
        "trading_brain_candidate_summary",
        "9d670e907d0246c794b69a2cf6c765701ded3c232c043e4dc281397e3bc9297d",
    ),
)


class PreflightError(ValueError):
    """The requested preflight scope is invalid."""


def _json_default(value: Any):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(f"Unsupported evidence value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_scope(
    project_id: str,
    operational_dataset: str,
    shadow_dataset: str,
    location: str,
) -> tuple[str, str, str, str]:
    project_id = str(project_id or "").strip()
    operational_dataset = str(operational_dataset or "").strip()
    shadow_dataset = str(shadow_dataset or "").strip()
    location = str(location or "").strip()
    if not PROJECT_ID.fullmatch(project_id):
        raise PreflightError("project_id is invalid")
    if not DATASET_ID.fullmatch(operational_dataset):
        raise PreflightError("operational_dataset is invalid")
    if not SHADOW_DATASET_ID.fullmatch(shadow_dataset):
        raise PreflightError(
            "shadow_dataset must be isolated and its name must contain 'shadow'"
        )
    if operational_dataset == shadow_dataset:
        raise PreflightError("operational and shadow datasets must be different")
    if not re.fullmatch(r"^[A-Za-z0-9-]+$", location):
        raise PreflightError("location is invalid")
    return project_id, operational_dataset, shadow_dataset, location


def _schema_snapshot(table: Any) -> list[dict[str, str]]:
    return [
        {
            "name": field.name,
            "type": field.field_type,
            "mode": field.mode,
        }
        for field in table.schema
    ]


def _safe_error(exc: Exception) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": str(exc).replace("\n", " ")[:240],
    }


def inspect_repository_static_registry(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    legacy_path = (
        repo_root / "dataform" / "definitions" / "legacy_result_registry.sqlx"
    )
    invalidation_path = (
        repo_root / "dataform" / "definitions" / "wp03_legacy_invalidation.sqlx"
    )
    problems: list[str] = []
    try:
        legacy_text = legacy_path.read_text(encoding="utf-8")
        invalidation_text = invalidation_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "status": "FAIL",
            "resolution_mode": "FROZEN_REPOSITORY_SNAPSHOT",
            "problems": [f"READ_ERROR:{type(exc).__name__}"],
        }

    if '${ref("legacy_result_registry")}' in invalidation_text:
        problems.append("LIVE_LEGACY_REGISTRY_REF_PRESENT")
    if 'dependencies: ["legacy_result_registry"]' in invalidation_text:
        problems.append("LIVE_LEGACY_REGISTRY_DEPENDENCY_PRESENT")
    if "FROZEN_REPOSITORY_SNAPSHOT" not in invalidation_text:
        problems.append("FROZEN_RESOLUTION_MARKER_MISSING")

    missing_rows = []
    for result_family, source_table, checksum in FROZEN_AFFECTED_RESULTS:
        if not all(
            marker in legacy_text
            for marker in (result_family, source_table, checksum)
        ):
            problems.append(f"BASELINE_SOURCE_ROW_MISSING:{result_family}")
        if not all(
            marker in invalidation_text
            for marker in (result_family, source_table, checksum)
        ):
            missing_rows.append(result_family)
    if missing_rows:
        problems.append(
            "FROZEN_INVALIDATION_ROWS_MISSING:" + ",".join(sorted(missing_rows))
        )

    return {
        "status": "PASS" if not problems else "FAIL",
        "resolution_mode": "FROZEN_REPOSITORY_SNAPSHOT",
        "source_path": str(legacy_path.relative_to(repo_root)),
        "consumer_path": str(invalidation_path.relative_to(repo_root)),
        "source_sha256": hashlib.sha256(legacy_text.encode("utf-8")).hexdigest(),
        "consumer_sha256": hashlib.sha256(
            invalidation_text.encode("utf-8")
        ).hexdigest(),
        "affected_result_count": len(FROZEN_AFFECTED_RESULTS),
        "problems": problems,
    }


def inspect_operational_inputs(
    client: Any,
    *,
    project_id: str,
    operational_dataset: str,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for table_name, contract in OPERATIONAL_INPUTS.items():
        table_id = f"{project_id}.{operational_dataset}.{table_name}"
        try:
            table = client.get_table(table_id)
        except Exception as exc:  # BigQuery client exceptions vary by runtime.
            results[table_name] = {
                "status": "FAIL",
                "access": "READ_ONLY",
                "table_id": table_id,
                "consumers": contract["consumers"],
                "error": _safe_error(exc),
            }
            continue

        schema = _schema_snapshot(table)
        available_columns = {field["name"] for field in schema}
        required_columns = set(contract["required_columns"])
        missing_columns = sorted(required_columns - available_columns)
        table_type = str(getattr(table, "table_type", "") or "").upper()
        problems = []
        if table_type not in ALLOWED_TABLE_TYPES:
            problems.append(f"UNSUPPORTED_TABLE_TYPE:{table_type or 'UNKNOWN'}")
        if missing_columns:
            problems.append("MISSING_COLUMNS:" + ",".join(missing_columns))
        results[table_name] = {
            "status": "PASS" if not problems else "FAIL",
            "access": "READ_ONLY",
            "table_id": table_id,
            "table_type": table_type,
            "num_rows": getattr(table, "num_rows", None),
            "modified": getattr(table, "modified", None),
            "schema_sha256": sha256_json(schema),
            "required_columns": sorted(required_columns),
            "missing_columns": missing_columns,
            "consumers": contract["consumers"],
            "problems": problems,
        }
    return results


def run_preflight(
    *,
    client: Any,
    project_id: str,
    operational_dataset: str,
    shadow_dataset: str,
    location: str,
    git_sha: str,
) -> dict[str, Any]:
    project_id, operational_dataset, shadow_dataset, location = validate_scope(
        project_id,
        operational_dataset,
        shadow_dataset,
        location,
    )
    dataset_results: dict[str, Any] = {}
    problems = []

    try:
        operational = client.get_dataset(
            f"{project_id}.{operational_dataset}"
        )
        operational_location = str(
            getattr(operational, "location", "") or ""
        )
        dataset_results["operational"] = {
            "status": (
                "PASS"
                if operational_location.lower() == location.lower()
                else "FAIL"
            ),
            "dataset_id": f"{project_id}.{operational_dataset}",
            "location": operational_location,
            "access": "READ_ONLY",
        }
        if dataset_results["operational"]["status"] != "PASS":
            problems.append("OPERATIONAL_DATASET_LOCATION_MISMATCH")
    except Exception as exc:
        dataset_results["operational"] = {
            "status": "FAIL",
            "dataset_id": f"{project_id}.{operational_dataset}",
            "error": _safe_error(exc),
        }
        problems.append("OPERATIONAL_DATASET_UNAVAILABLE")

    try:
        shadow = client.get_dataset(f"{project_id}.{shadow_dataset}")
        shadow_location = str(getattr(shadow, "location", "") or "")
        labels = dict(getattr(shadow, "labels", None) or {})
        shadow_problems = []
        if shadow_location.lower() != location.lower():
            shadow_problems.append("LOCATION_MISMATCH")
        if labels.get("environment") != "shadow":
            shadow_problems.append("ENVIRONMENT_LABEL_MISMATCH")
        if labels.get("work_package") != "wp03":
            shadow_problems.append("WORK_PACKAGE_LABEL_MISMATCH")
        existing_tables = sorted(
            item.table_id
            for item in client.list_tables(
                f"{project_id}.{shadow_dataset}"
            )
        )
        unexpected_tables = sorted(
            table
            for table in existing_tables
            if table not in WP03_OUTPUTS
            and not table.startswith("assertions_")
        )
        if unexpected_tables:
            shadow_problems.append(
                "UNEXPECTED_EXISTING_TABLES:" + ",".join(unexpected_tables)
            )
        dataset_results["shadow"] = {
            "status": "PASS" if not shadow_problems else "FAIL",
            "dataset_id": f"{project_id}.{shadow_dataset}",
            "location": shadow_location,
            "labels": labels,
            "access": "WRITE_WP03_OUTPUTS_ONLY",
            "existing_tables": existing_tables,
            "unexpected_tables": unexpected_tables,
            "problems": shadow_problems,
        }
        if shadow_problems:
            problems.extend(f"SHADOW_{item}" for item in shadow_problems)
    except Exception as exc:
        dataset_results["shadow"] = {
            "status": "FAIL",
            "dataset_id": f"{project_id}.{shadow_dataset}",
            "error": _safe_error(exc),
        }
        problems.append("SHADOW_DATASET_UNAVAILABLE")

    operational_inputs = inspect_operational_inputs(
        client,
        project_id=project_id,
        operational_dataset=operational_dataset,
    )
    for table_name, result in operational_inputs.items():
        if result["status"] != "PASS":
            problems.append(f"OPERATIONAL_INPUT_INVALID:{table_name}")

    static_registry = inspect_repository_static_registry()
    if static_registry["status"] != "PASS":
        problems.append("STATIC_LEGACY_REGISTRY_INVALID")

    stable_payload = {
        "schema_version": 1,
        "operation": "WP03_SHADOW_PREREQUISITE_PREFLIGHT",
        "git_sha": git_sha,
        "project_id": project_id,
        "location": location,
        "operational_dataset": operational_dataset,
        "shadow_dataset": shadow_dataset,
        "datasets": dataset_results,
        "operational_inputs": operational_inputs,
        "repository_static_inputs": {
            "legacy_result_registry": static_registry
        },
        "wp03_outputs": list(WP03_OUTPUTS),
        "problems": sorted(problems),
        "production_change_allowed": False,
    }
    return {
        **stable_payload,
        "status": "PASS" if not problems else "FAIL",
        "preflight_checksum": sha256_json(stable_payload),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def _write_output(document: Mapping[str, Any], output: Path | None) -> None:
    text = json.dumps(
        document,
        indent=2,
        sort_keys=True,
        default=_json_default,
    ) + "\n"
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-git-sha", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--operational-dataset", required=True)
    parser.add_argument("--shadow-dataset", required=True)
    parser.add_argument("--location", default="us-east1")
    parser.add_argument("--environment", default="shadow")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        if args.environment != "shadow":
            raise PreflightError("WP-03 preflight is restricted to shadow")
        git_sha = verify_clean_checkout(args.expected_git_sha)
        try:
            from google.cloud import bigquery
        except ImportError as exc:
            raise PreflightError(
                "google-cloud-bigquery is required for live preflight"
            ) from exc
        client = bigquery.Client(
            project=args.project_id,
            location=args.location,
        )
        result = run_preflight(
            client=client,
            project_id=args.project_id,
            operational_dataset=args.operational_dataset,
            shadow_dataset=args.shadow_dataset,
            location=args.location,
            git_sha=git_sha,
        )
        _write_output(result, args.output)
        return 0 if result["status"] == "PASS" else 2
    except (
        OSError,
        PreflightError,
        RuntimeError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            json.dumps(
                {"status": "FAIL", "error": str(exc)},
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
