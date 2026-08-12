"""Versioned, fail-closed policy for probabilistic valuation classification."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from packages.common.hashing import sha256_json

from .models import VERSION, ValuationError


@dataclass(frozen=True)
class ValuationPolicy:
    policy_version: str
    cheap_upside_threshold: float = 0.15
    expensive_downside_threshold: float = 0.15
    probability_threshold: float = 0.65
    fair_value_band: float = 0.10
    min_model_count: int = 2
    min_confidence: float = 0.45
    max_interval_width_ratio: float = 1.50
    max_value_trap_for_economic: float = 0.35
    value_trap_abstain_threshold: float = 0.75
    min_risk_coverage_for_economic: float = 0.50
    min_peer_count: int = 8
    min_peer_observations_per_parameter: int = 3
    relative_feature_z_limit: float = 4.0
    ridge_penalty: float = 1.0
    require_calibrated_models: bool = True
    require_calibrated_value_trap: bool = True
    model_weights: Mapping[str, float] = field(
        default_factory=lambda: {
            "relative": 1.0,
            "fcff": 1.0,
            "residual_income": 1.0,
            "reverse_dcf": 0.5,
        }
    )

    def __post_init__(self) -> None:
        if not VERSION.fullmatch(str(self.policy_version)):
            raise ValuationError("policy_version is invalid")
        for label, value in (
            ("cheap_upside_threshold", self.cheap_upside_threshold),
            ("expensive_downside_threshold", self.expensive_downside_threshold),
            ("probability_threshold", self.probability_threshold),
            ("fair_value_band", self.fair_value_band),
            ("min_confidence", self.min_confidence),
            ("max_value_trap_for_economic", self.max_value_trap_for_economic),
            ("value_trap_abstain_threshold", self.value_trap_abstain_threshold),
            ("min_risk_coverage_for_economic", self.min_risk_coverage_for_economic),
        ):
            number = float(value)
            if not math.isfinite(number) or not 0 <= number <= 1:
                raise ValuationError(f"{label} must be between 0 and 1")
        if self.cheap_upside_threshold <= 0:
            raise ValuationError("cheap_upside_threshold must be positive")
        if self.expensive_downside_threshold <= 0:
            raise ValuationError("expensive_downside_threshold must be positive")
        if not 0.5 < self.probability_threshold < 1:
            raise ValuationError("probability_threshold must be greater than 0.5")
        if self.min_model_count < 1:
            raise ValuationError("min_model_count must be >= 1")
        if self.min_peer_count < 4:
            raise ValuationError("min_peer_count must be >= 4")
        if self.min_peer_observations_per_parameter < 2:
            raise ValuationError(
                "min_peer_observations_per_parameter must be >= 2"
            )
        if (
            not math.isfinite(self.relative_feature_z_limit)
            or self.relative_feature_z_limit <= 0
        ):
            raise ValuationError("relative_feature_z_limit must be positive")
        if (
            not math.isfinite(self.max_interval_width_ratio)
            or self.max_interval_width_ratio <= 0
        ):
            raise ValuationError("max_interval_width_ratio must be positive")
        if not math.isfinite(self.ridge_penalty) or self.ridge_penalty < 0:
            raise ValuationError("ridge_penalty cannot be negative")
        if self.max_value_trap_for_economic >= self.value_trap_abstain_threshold:
            raise ValuationError(
                "max_value_trap_for_economic must be below abstain threshold"
            )
        for label, value in (
            ("require_calibrated_models", self.require_calibrated_models),
            ("require_calibrated_value_trap", self.require_calibrated_value_trap),
        ):
            if not isinstance(value, bool):
                raise ValuationError(f"{label} must be boolean")
        if not self.model_weights:
            raise ValuationError("model_weights cannot be empty")
        normalized_keys = [str(key).strip().lower() for key in self.model_weights]
        if len(set(normalized_keys)) != len(normalized_keys):
            raise ValuationError("model weight keys must be unique case-insensitively")
        for family, value in self.model_weights.items():
            if not str(family).strip():
                raise ValuationError("model weight key cannot be empty")
            number = float(value)
            if not math.isfinite(number) or number <= 0:
                raise ValuationError("model weights must be positive")

    @property
    def policy_hash(self) -> str:
        return sha256_json(self.to_mapping())

    def weight_for(self, model_family: str) -> float:
        normalized = str(model_family).strip().lower()
        matches = [
            (str(key).strip().lower(), float(value))
            for key, value in self.model_weights.items()
            if normalized == str(key).strip().lower()
            or normalized.startswith(str(key).strip().lower())
        ]
        if not matches:
            return 1.0
        longest = max(len(key) for key, _ in matches)
        best = [value for key, value in matches if len(key) == longest]
        if len(set(best)) != 1:
            raise ValuationError(
                f"ambiguous model weight policy for family {model_family}"
            )
        return best[0]

    def minimum_peer_observations(self, feature_count: int) -> int:
        if feature_count < 1:
            raise ValuationError("feature_count must be positive")
        # The +1 ensures each leave-one-out training fold still satisfies the
        # observations-per-parameter floor, including the unpenalized intercept.
        return max(
            self.min_peer_count,
            1
            + self.min_peer_observations_per_parameter * (feature_count + 1),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "cheap_upside_threshold": self.cheap_upside_threshold,
            "expensive_downside_threshold": self.expensive_downside_threshold,
            "probability_threshold": self.probability_threshold,
            "fair_value_band": self.fair_value_band,
            "min_model_count": self.min_model_count,
            "min_confidence": self.min_confidence,
            "max_interval_width_ratio": self.max_interval_width_ratio,
            "max_value_trap_for_economic": self.max_value_trap_for_economic,
            "value_trap_abstain_threshold": self.value_trap_abstain_threshold,
            "min_risk_coverage_for_economic": self.min_risk_coverage_for_economic,
            "min_peer_count": self.min_peer_count,
            "min_peer_observations_per_parameter": (
                self.min_peer_observations_per_parameter
            ),
            "relative_feature_z_limit": self.relative_feature_z_limit,
            "ridge_penalty": self.ridge_penalty,
            "require_calibrated_models": self.require_calibrated_models,
            "require_calibrated_value_trap": self.require_calibrated_value_trap,
            "model_weights": dict(sorted(self.model_weights.items())),
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ValuationPolicy":
        allowed = {
            "policy_version",
            "cheap_upside_threshold",
            "expensive_downside_threshold",
            "probability_threshold",
            "fair_value_band",
            "min_model_count",
            "min_confidence",
            "max_interval_width_ratio",
            "max_value_trap_for_economic",
            "value_trap_abstain_threshold",
            "min_risk_coverage_for_economic",
            "min_peer_count",
            "min_peer_observations_per_parameter",
            "relative_feature_z_limit",
            "ridge_penalty",
            "require_calibrated_models",
            "require_calibrated_value_trap",
            "model_weights",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValuationError(f"unknown policy fields: {unknown}")
        if "policy_version" not in payload:
            raise ValuationError("policy_version is required")
        return cls(**dict(payload))


def load_policy(path: str | Path) -> ValuationPolicy:
    policy_path = Path(path)
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValuationError(f"unable to load policy {policy_path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ValuationError("policy JSON must be an object")
    return ValuationPolicy.from_mapping(payload)
