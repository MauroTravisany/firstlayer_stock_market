"""Separate enterprise quality from valuation and estimate value-trap risk."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from .models import QualityAssessment, QualityState, RiskState, ValuationError


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


def assess_quality(inputs: QualityInputs) -> QualityAssessment:
    """Score business quality and value-trap risk on independent axes.

    Missing data reduces feature coverage. The score never changes fair value;
    it is used only for confidence, risk state and potential abstention.
    """

    quality_components: dict[str, tuple[float, float]] = {}
    if inputs.gross_profitability is not None:
        quality_components["gross_profitability"] = (
            _scale(inputs.gross_profitability, 0.10, 0.50),
            0.15,
        )
    if inputs.roic is not None and inputs.wacc is not None:
        quality_components["roic_minus_wacc"] = (
            _scale(inputs.roic - inputs.wacc, -0.05, 0.15),
            0.25,
        )
    if inputs.free_cash_flow_margin is not None:
        quality_components["free_cash_flow_margin"] = (
            _scale(inputs.free_cash_flow_margin, -0.05, 0.20),
            0.15,
        )
    if inputs.cash_conversion is not None:
        quality_components["cash_conversion"] = (
            _scale(inputs.cash_conversion, 0.40, 1.10),
            0.15,
        )
    if inputs.margin_stability is not None:
        quality_components["margin_stability"] = (
            _clamp(inputs.margin_stability),
            0.10,
        )
    if inputs.interest_coverage is not None:
        quality_components["interest_coverage"] = (
            _scale(inputs.interest_coverage, 1.0, 10.0),
            0.10,
        )
    if inputs.net_debt_to_ebitda is not None:
        quality_components["leverage"] = (
            _inverse_scale(inputs.net_debt_to_ebitda, 0.5, 5.0),
            0.10,
        )

    total_weight = sum(weight for _, weight in quality_components.values())
    quality_score = (
        sum(score * weight for score, weight in quality_components.values())
        / total_weight
        if total_weight
        else 0.0
    )
    expected_features = 7
    feature_coverage = min(1.0, len(quality_components) / expected_features)

    reasons: list[str] = []
    if feature_coverage < 0.50:
        quality_state = QualityState.DATOS_INSUFICIENTES
        reasons.append("QUALITY_FEATURE_COVERAGE_LOW")
    elif quality_score >= 0.70:
        quality_state = QualityState.ALTA
    elif quality_score >= 0.45:
        quality_state = QualityState.MEDIA
    else:
        quality_state = QualityState.BAJA

    risk_terms: dict[str, tuple[float, float]] = {}
    if inputs.earnings_revision is not None:
        risk_terms["negative_earnings_revision"] = (
            _clamp(-inputs.earnings_revision / 0.20),
            1.25,
        )
    if inputs.operating_margin_change is not None:
        risk_terms["margin_deterioration"] = (
            _clamp(-inputs.operating_margin_change / 0.10),
            1.10,
        )
    if inputs.net_debt_to_ebitda is not None:
        risk_terms["leverage_risk"] = (
            _clamp((inputs.net_debt_to_ebitda - 2.0) / 4.0),
            1.10,
        )
    if inputs.interest_coverage is not None:
        risk_terms["coverage_risk"] = (
            _clamp((3.0 - inputs.interest_coverage) / 3.0),
            1.00,
        )
    if inputs.accruals_ratio is not None:
        risk_terms["accruals_risk"] = (
            _clamp((inputs.accruals_ratio - 0.05) / 0.15),
            0.90,
        )
    if inputs.free_cash_flow_margin is not None:
        risk_terms["negative_free_cash_flow"] = (
            _clamp(-inputs.free_cash_flow_margin / 0.15),
            1.00,
        )
    if inputs.revenue_growth is not None:
        risk_terms["revenue_contraction"] = (
            _clamp(-inputs.revenue_growth / 0.20),
            0.80,
        )

    risk_signal = -1.75 + sum(score * weight for score, weight in risk_terms.values())
    value_trap_probability = _sigmoid(risk_signal)
    risk_coverage = len(risk_terms) / 7.0
    if risk_coverage < 0.40:
        risk_state = RiskState.DESCONOCIDO
        reasons.append("VALUE_TRAP_FEATURE_COVERAGE_LOW")
    elif value_trap_probability >= 0.65:
        risk_state = RiskState.ALTO
        reasons.append("VALUE_TRAP_RISK_HIGH")
    elif value_trap_probability >= 0.35:
        risk_state = RiskState.MEDIO
    else:
        risk_state = RiskState.BAJO

    if (
        inputs.roic is not None
        and inputs.wacc is not None
        and inputs.roic < inputs.wacc
    ):
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
        reason_codes=tuple(sorted(set(reasons))),
    )


def quality_components(inputs: QualityInputs) -> Mapping[str, float | None]:
    """Return an auditable, non-scoring view of the supplied quality inputs."""

    return dict(inputs.__dict__)
