"""WP-02 canonical experiment identity and configuration primitives."""

from __future__ import annotations

import contextvars
import datetime as dt
import hashlib
import json
import math
import re
import uuid
from pathlib import Path
from typing import Any, Mapping


_CURRENT = contextvars.ContextVar("strategy_brain_experiment", default=None)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
UUID_CANONICAL = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
RUN_ID = re.compile(r"^run_[0-9a-f]{64}$")
CANDIDATE_ID = re.compile(r"^cand_[0-9a-f]{64}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
ENVIRONMENTS = {"research", "shadow", "paper", "staging"}
ALLOWED_TRANSITIONS = {
    "CREATED": {"CANDIDATES_READY", "FAILED", "CANCELLED"},
    "CANDIDATES_READY": {"RUNNING", "REJECTED", "FAILED", "CANCELLED"},
    "RUNNING": {"COMPLETED", "REJECTED", "FAILED", "CANCELLED"},
    "COMPLETED": set(),
    "REJECTED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
}
CANDIDATE_CONFIGURATION_FIELDS = (
    "formula_version",
    "training_start",
    "training_end",
    "validation_start",
    "validation_end",
    "fear_weight",
    "monetary_weight",
    "earnings_weight",
    "trend_weight",
    "momentum_weight",
    "volume_weight",
    "volatility_weight",
    "regime_weight",
    "company_lifecycle_weight",
    "quality_weight",
    "valuation_state_weight",
    "political_risk_weight",
    "crypto_cycle_weight",
    "min_trade_score_add",
    "position_size_multiplier",
    "asset_scope",
    "asset_tickers",
    "target_strategy_version",
)


class RegistryAdapterError(RuntimeError):
    """Experiment lineage could not be created or persisted safely."""


def canonical_json(value: Any) -> str:
    def normalize(item):
        if item is None or isinstance(item, (str, bool, int)):
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise RegistryAdapterError("non-finite configuration value")
            return item
        if isinstance(item, dt.datetime):
            if item.tzinfo is None:
                raise RegistryAdapterError("datetime values must be timezone-aware")
            return item.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        if isinstance(item, dt.date):
            return item.isoformat()
        if isinstance(item, Mapping):
            if any(not isinstance(key, str) for key in item):
                raise RegistryAdapterError("configuration mapping keys must be strings")
            return {key: normalize(item[key]) for key in sorted(item)}
        if isinstance(item, (list, tuple)):
            return [normalize(child) for child in item]
        raise RegistryAdapterError(
            f"unsupported configuration value: {type(item).__name__}"
        )

    return json.dumps(
        normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def dependency_lock_hash(path: Path) -> str:
    if not path.is_file():
        raise RegistryAdapterError(f"dependency file missing: {path}")
    data = path.read_bytes()
    manifest = [
        {
            "path": path.name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }
    ]
    return sha256_value(manifest)


def load_contract_manifest(path: Path | None = None) -> dict[str, str]:
    candidate = path or Path(__file__).with_name("contract_set_manifest.json")
    try:
        document = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryAdapterError("contract-set manifest is missing or invalid") from exc
    required = {"data_contract_version", "contract_set_hash", "schema_snapshot_hash"}
    if not isinstance(document, dict) or not required.issubset(document):
        raise RegistryAdapterError("contract-set manifest is incomplete")
    for field in ("contract_set_hash", "schema_snapshot_hash"):
        if not HEX64.fullmatch(str(document[field])):
            raise RegistryAdapterError(f"contract-set manifest {field} is invalid")
    return {field: str(document[field]) for field in sorted(required)}


def new_experiment_id() -> str:
    return str(uuid.uuid4())


def build_run_id(experiment_id: str, attempt_id: str | None = None) -> str:
    if not UUID_CANONICAL.fullmatch(str(experiment_id)):
        raise RegistryAdapterError("experiment_id must be a canonical UUID")
    return "run_" + sha256_value(
        {"experiment_id": experiment_id, "attempt_id": attempt_id or str(uuid.uuid4())}
    )


def candidate_configuration(record: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in CANDIDATE_CONFIGURATION_FIELDS if field not in record]
    if missing:
        raise RegistryAdapterError(
            f"candidate configuration is missing fields: {','.join(missing)}"
        )
    return {field: record[field] for field in CANDIDATE_CONFIGURATION_FIELDS}


def build_candidate_id(
    experiment_id: str,
    run_id: str,
    generation: int,
    parent_candidate_id: str | None,
    configuration: Mapping[str, Any],
) -> str:
    if not UUID_CANONICAL.fullmatch(str(experiment_id)):
        raise RegistryAdapterError("experiment_id must be a canonical UUID")
    if not RUN_ID.fullmatch(str(run_id)):
        raise RegistryAdapterError("run_id must use run_<sha256>")
    if int(generation) < 1:
        raise RegistryAdapterError("candidate generation must be >= 1")
    if parent_candidate_id is not None and not CANDIDATE_ID.fullmatch(
        str(parent_candidate_id)
    ):
        raise RegistryAdapterError("parent_candidate_id must use cand_<sha256>")
    return "cand_" + sha256_value(
        {
            "experiment_id": experiment_id,
            "run_id": run_id,
            "generation": int(generation),
            "parent_candidate_id": parent_candidate_id,
            "candidate_configuration_hash": sha256_value(configuration),
        }
    )


def _require_payload(payload, field):
    value = payload.get(field)
    if value is None or not str(value).strip():
        raise RegistryAdapterError(
            f"{field} is required for every audit-grade Strategy Brain experiment"
        )
    return str(value).strip()


def create_context(payload, config, legacy) -> dict[str, Any]:
    experiment_id = str(payload.get("experiment_id") or new_experiment_id()).lower()
    if not UUID_CANONICAL.fullmatch(experiment_id):
        raise RegistryAdapterError("experiment_id must be a canonical UUID")
    run_id = str(payload.get("run_id") or build_run_id(experiment_id)).lower()
    if not RUN_ID.fullmatch(run_id):
        raise RegistryAdapterError("run_id must use run_<sha256>")
    payload["experiment_id"] = experiment_id
    payload["run_id"] = run_id

    git_sha = str(config.get("release_git_sha") or "").strip().lower()
    if not GIT_SHA.fullmatch(git_sha):
        raise RegistryAdapterError("RELEASE_GIT_SHA must be a full lowercase git SHA")
    image_digest = str(config.get("release_image_digest") or "").strip().lower()
    if image_digest and not DIGEST.fullmatch(image_digest):
        raise RegistryAdapterError("RELEASE_IMAGE_DIGEST must be sha256:<64 hex>")
    environment = str(config.get("environment") or "").strip().lower()
    if environment not in ENVIRONMENTS:
        raise RegistryAdapterError(f"unsupported experiment environment: {environment}")

    contract_manifest = load_contract_manifest()
    if config["data_contract_version"] != contract_manifest["data_contract_version"]:
        raise RegistryAdapterError("runtime data-contract version differs from build manifest")

    data_snapshot_id = _require_payload(payload, "data_snapshot_id")
    hypothesis = _require_payload(payload, "hypothesis")
    asset_scope = str(payload.get("asset_scope") or "MEGACAP_TECH").upper()
    scope = legacy.ASSET_SCOPES.get(asset_scope)
    if not scope:
        raise RegistryAdapterError(f"unsupported asset_scope: {asset_scope}")
    parent_run_id = payload.get("parent_run_id")
    if parent_run_id is not None:
        parent_run_id = str(parent_run_id).lower()
        if not RUN_ID.fullmatch(parent_run_id):
            raise RegistryAdapterError("parent_run_id must use run_<sha256>")
        payload["parent_run_id"] = parent_run_id

    requested_hypothesis_count = int(
        payload.get("hypothesis_count") or legacy.MAX_CANDIDATES_PER_GENERATION
    )
    if requested_hypothesis_count < 1:
        raise RegistryAdapterError("hypothesis_count must be >= 1")

    configuration = {
        "formula_version": legacy.FORMULA_VERSION,
        "asset_scope": asset_scope,
        "strategy_version": scope["strategy_version"],
        "tickers": list(scope["tickers"]),
        "training_start": payload.get("training_start", "2019-01-01"),
        "training_end": payload.get("training_end", "2024-12-31"),
        "validation_start": payload.get("validation_start", "2025-01-01"),
        "validation_end": payload.get("validation_end")
        or str(dt.date.today() - dt.timedelta(days=1)),
        "parent_run_id": parent_run_id,
        "generation_override": payload.get("generation_override"),
        "force": bool(payload.get("force", False)),
        "random_seed": payload.get("random_seed"),
    }
    return {
        "experiment_id": experiment_id,
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "parent_experiment_id": None,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "hypothesis": hypothesis,
        "git_sha": git_sha,
        "image_digest": image_digest or None,
        "dataform_compilation_id": config.get("dataform_compilation_id") or None,
        "environment": environment,
        "data_contract_version": config["data_contract_version"],
        "contract_set_hash": contract_manifest["contract_set_hash"],
        "schema_snapshot_hash": contract_manifest["schema_snapshot_hash"],
        "data_snapshot_id": data_snapshot_id,
        "data_snapshot_checksum": None,
        "universe_version": str(
            payload.get("universe_version") or f"{asset_scope.lower()}-v1"
        ),
        "feature_set_version": config["feature_set_version"],
        "strategy_version": scope["strategy_version"],
        "execution_model_version": config["execution_model_version"],
        "cost_model_version": config["cost_model_version"],
        "configuration": configuration,
        "configuration_json": canonical_json(configuration),
        "configuration_hash": sha256_value(configuration),
        "dependency_lock_hash": dependency_lock_hash(
            Path(__file__).with_name("requirements.txt")
        ),
        "random_seed": payload.get("random_seed"),
        "hypothesis_count": requested_hypothesis_count,
        "asset_scope": asset_scope,
    }


