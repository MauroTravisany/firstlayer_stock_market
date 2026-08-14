"""Separate enterprise quality from valuation and estimate value-trap risk."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from packages.common.hashing import sha256_json

from .models import (
    CalibrationStatus,
    QualityAssessment,
    QualityState,
    RiskState,
    ValuationError,
    ValuationLineage,
)

QUALITY_MODEL_VERSION = "wp07a-quality-risk-v2"
QUALITY_CONFIGURATION = {
    "quality": {
        "gross_profitability": {"bad": 0.10, "good": 0.50, "weight": 0.15},
        "roic_minus_wacc": {"bad": -0.05, "good": 0.15, "weight": 0.25},
        "free_cash_flow_margin": {"bad": -0.05, "good": 0.20, "weight": 0.15},
        "cash_conversion": {"bad": 0.40, "good": 1.10, "weight": 0.15},
        "margin_stability": {"weight": 0.10},
        "interest_coverage": {"bad": 1.0, "good": 10.0, "weight": 0.10},
        "net_debt_to_ebitda": {"good": 0.5, "bad": 5.0, "weight": 0.10},
        "minimum_coverage": 0.50,
        "high_threshold": 0.70,
        "medium_threshold": 0.45,
    },
    "value_trap": {
        "intercept": -1.75,
        "negative_earnings_revision": {"scale": 0.20, "weight": 1.25},
        "margin_deterioration": {"scale": 0.10, "weight": 1.10},
        "leverage_risk": {"start": 2.0, "scale": 4.0, "weight": 1.10},
        "coverage_risk": {"start": 3.0, "scale": 3.0, "weight": 1.00},
        "accruals_risk": {"start": 0.05, "scale": 0.15, "weight": 0.90},
        "negative_free_cash_flow": {"scale": 0.15, "weight": 1.00},
        "revenue_contraction": {"scale": 0.20, "weight": 0.80},
        "minimum_coverage": 0.40,
        "high_threshold": 0.65,
        "medium_threshold": 0.35,
    },
}
QUALITY_CONFIGURATION_HASH = sha256_json(QUALITY_CONFIGURATION)


@dataclass(frozen=True)
class QualityInputs:
    gross_profitability: float | None = None
    roic: float | None = None
    wacc: float | None = None
    free_cash_flow_margin: float | None = None
    cash_conversion: float | None = None
    margin_stability: float | None = None
    net_debt_to_ebitda: float | None = None
    interest_coverage: float | None = None
    accruals_ratio: float | None = None
    revenue_growth: float | None = None
    earnings_revision: float | None = None
    operating_margin_change: float | None = None

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if value is not None and not math.isfinite(float(value)):
                raise ValuationError(f"{name} must be finite")


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _scale(value: float, bad: float, good: float) -> float:
    if good <= bad:
        raise ValuationError("quality scale requires good > bad")
    return _clamp((float(value) - bad) / (good - bad))


def _inverse_scale(value: float, good: float, bad: float) -> float:
    if bad <= good:
        raise ValuationError("inverse quality scale requires bad > good")
    return _clamp((bad - float(value)) / (bad - good))


def _sigmoid(value: float) -> float:
    if value >= 0:
        denominator = 1.0 + math.exp(-value)
        return 1.0 / denominator
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


def assess_quality(
    inputs: QualityInputs,
    lineage: ValuationLineage,
) -> QualityAssessment:
    """Score quality and value-trap risk on independent, versioned axes.

    The value-trap output remains ``UNVERIFIED`` until independent OOS
    calibration evidence is bound. An uncalibrated low score is never labeled
    low risk; high or medium warning signals may still fail closed.
    """

    if lineage.model_version != QUALITY_MODEL_VERSION:
        raise ValuationError("quality lineage model_version is incompatible")
    if lineage.configuration_hash != QUALITY_CONFIGURATION_HASH:
        raise ValuationError("quality lineage configuration_hash is incompatible")
    if lineage.peer_universe_hash is not None:
        raise ValuationError("quality assessment cannot carry peer_universe_hash")

    quality_policy = QUALITY_CONFIGURATION["quality"]
    quality_components: dict[str, tuple[float, float]] = {}
    if inputs.gross_profitability is not None:
        config = quality_policy["gross_profitability"]
        quality_components["gross_profitability"] = (
            _scale(inputs.gross_profitability, config["bad"], config["good"]),
            config["weight"],
        )
    if inputs.roic is not None and inputs.wacc is not None:
        config = quality_policy["roic_minus_wacc"]
        quality_components["roic_minus_wacc"] = (
            _scale(inputs.roic - inputs.wacc, config["bad"], config["good"]),
            config["weight"],
        )
    if inputs.free_cash_flow_margin is not None:
        config = quality_policy["free_cash_flow_margin"]
        quality_components["free_cash_flow_margin"] = (
            _scale(inputs.free_cash_flow_margin, config["bad"], config["good"]),
            config["weight"],
        )
    if inputs.cash_conversion is not None:
        config = quality_policy["cash_conversion"]
        quality_components["cash_conversion"] = (
            _scale(inputs.cash_conversion, config["bad"], config["good"]),
            config["weight"],
        )
    if inputs.margin_stability is not None:
        quality_components["margin_stability"] = (
            _clamp(inputs.margin_stability),
            quality_policy["margin_stability"]["weight"],
        )
    if inputs.interest_coverage is not None:
        config = quality_policy["interest_coverage"]
        quality_components["interest_coverage"] = (
            _scale(inputs.interest_coverage, config["bad"], config["good"]),
            config["weight"],
        )
    if inputs.net_debt_to_ebitda is not None:
        config = quality_policy["net_debt_to_ebitda"]
        quality_components["leverage"] = (
            _inverse_scale(
                inputs.net_debt_to_ebitda,
                config["good"],
                config["bad"],
            ),
            config["weight"],
        )

    total_weight = sum(weight for _, weight in quality_components.values())
    quality_score = (
        sum(score * weight for score, weight in quality_components.values())
        / total_weight
        if total_weight
        else 0.0
    )
    expected_quality_features = 7
    feature_coverage = min(
        1.0, len(quality_components) / expected_quality_features
    )

    reasons: list[str] = []
    if feature_coverage < quality_policy["minimum_coverage"]:
        quality_state = QualityState.DATOS_INSUFICIENTES
        reasons.append("QUALITY_FEATURE_COVERAGE_LOW")
    elif quality_score >= quality_policy["high_threshold"]:
        quality_state = QualityState.ALTA
    elif quality_score >= quality_policy["medium_threshold"]:
        quality_state = QualityState.MEDIA
    else:
        quality_state = QualityState.BAJA

    risk_policy = QUALITY_CONFIGURATION["value_trap"]
    risk_terms: dict[str, tuple[float, float]] = {}
    if inputs.earnings_revision is not None:
        config = risk_policy["negative_earnings_revision"]
        risk_terms["negative_earnings_revision"] = (
            _clamp(-inputs.earnings_revision / config["scale"]),
            config["weight"],
        )
    if inputs.operating_margin_change is not None:
        config = risk_policy["margin_deterioration"]
        risk_terms["margin_deterioration"] = (
            _clamp(-inputs.operating_margin_change / config["scale"]),
            config["weight"],
        )
    if inputs.net_debt_to_ebitda is not None:
        config = risk_policy["leverage_risk"]
        risk_terms["leverage_risk"] = (
            _clamp(
                (inputs.net_debt_to_ebitda - config["start"])
                / config["scale"]
            ),
            config["weight"],
        )
    if inputs.interest_coverage is not None:
        config = risk_policy["coverage_risk"]
        risk_terms["coverage_risk"] = (
            _clamp(
                (config["start"] - inputs.interest_coverage)
                / config["scale"]
            ),
            config["weight"],
        )
    if inputs.accruals_ratio is not None:
        config = risk_policy["accruals_risk"]
        risk_terms["accruals_risk"] = (
            _clamp(
                (inputs.accruals_ratio - config["start"])
                / config["scale"]
            ),
            config["weight"],
        )
    if inputs.free_cash_flow_margin is not None:
        config = risk_policy["negative_free_cash_flow"]
        risk_terms["negative_free_cash_flow"] = (
            _clamp(-inputs.free_cash_flow_margin / config["scale"]),
            config["weight"],
        )
    if inputs.revenue_growth is not None:
        config = risk_policy["revenue_contraction"]
        risk_terms["revenue_contraction"] = (
            _clamp(-inputs.revenue_growth / config["scale"]),
            config["weight"],
        )

    risk_signal = risk_policy["intercept"] + sum(
        score * weight for score, weight in risk_terms.values()
    )
    value_trap_probability = _sigmoid(risk_signal)
    risk_feature_coverage = min(1.0, len(risk_terms) / 7.0)
    if risk_feature_coverage < risk_policy["minimum_coverage"]:
        risk_state = RiskState.DESCONOCIDO
        reasons.append("VALUE_TRAP_FEATURE_COVERAGE_LOW")
    elif value_trap_probability >= risk_policy["high_threshold"]:
        risk_state = RiskState.ALTO
        reasons.append("VALUE_TRAP_RISK_HIGH")
    elif value_trap_probability >= risk_policy["medium_threshold"]:
        risk_state = RiskState.MEDIO
    else:
        risk_state = RiskState.DESCONOCIDO
        reasons.append("VALUE_TRAP_LOW_RISK_NOT_CALIBRATED")

    reasons.append("VALUE_TRAP_MODEL_UNCALIBRATED")
    if inputs.roic is not None and inputs.wacc is not None and inputs.roic < inputs.wacc:
        reasons.append("ROIC_BELOW_WACC")
    if inputs.free_cash_flow_margin is not None and inputs.free_cash_flow_margin < 0:
        reasons.append("NEGATIVE_FREE_CASH_FLOW_MARGIN")
    if inputs.earnings_revision is not None and inputs.earnings_revision < -0.10:
        reasons.append("MATERIAL_NEGATIVE_EARNINGS_REVISION")

    return QualityAssessment(
        quality_score=round(_clamp(quality_score), 12),
        quality_state=quality_state,
        value_trap_probability=round(_clamp(value_trap_probability), 12),
        risk_state=risk_state,
        feature_coverage=round(feature_coverage, 12),
        risk_feature_coverage=round(risk_feature_coverage, 12),
        lineage=lineage,
        risk_calibration_status=CalibrationStatus.UNVERIFIED,
        risk_calibration_hash=None,
        reason_codes=tuple(sorted(set(reasons))),
    )


def quality_components(inputs: QualityInputs) -> Mapping[str, float | None]:
    """Return an auditable, non-scoring view of the supplied quality inputs."""

    return dict(inputs.__dict__)
