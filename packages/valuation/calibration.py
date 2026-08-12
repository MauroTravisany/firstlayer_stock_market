"""Calibration diagnostics and immutable evidence binding for valuation models."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from packages.common.hashing import sha256_json

from .models import (
    CalibrationStatus,
    ModelDistribution,
    QualityAssessment,
    RiskState,
    SHA256,
    SNAPSHOT_ID,
    VERSION,
    ValuationError,
)


def _effective_sample_size(weights: Sequence[float]) -> float:
    total = sum(float(weight) for weight in weights)
    squared = sum(float(weight) ** 2 for weight in weights)
    return total**2 / squared if squared > 0 else 0.0


@dataclass(frozen=True)
class ProbabilityForecast:
    probability: float
    outcome: bool
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.probability)) or not 0 <= self.probability <= 1:
            raise ValuationError("probability must be between 0 and 1")
        if not isinstance(self.outcome, bool):
            raise ValuationError("outcome must be boolean")
        if not math.isfinite(float(self.weight)) or self.weight <= 0:
            raise ValuationError("forecast weight must be positive")


@dataclass(frozen=True)
class IntervalForecast:
    lower: float
    upper: float
    realized: float
    weight: float = 1.0

    def __post_init__(self) -> None:
        for label, value in (
            ("lower", self.lower),
            ("upper", self.upper),
            ("realized", self.realized),
            ("weight", self.weight),
        ):
            if not math.isfinite(float(value)):
                raise ValuationError(f"{label} must be finite")
        if self.lower <= 0 or self.upper <= 0 or self.realized <= 0:
            raise ValuationError("valuation interval observations must be positive")
        if self.lower > self.upper:
            raise ValuationError("interval lower cannot exceed upper")
        if self.weight <= 0:
            raise ValuationError("interval weight must be positive")


@dataclass(frozen=True)
class CalibrationBin:
    lower_bound: float
    upper_bound: float
    count: int
    total_weight: float
    mean_probability: float
    empirical_frequency: float
    absolute_gap: float


@dataclass(frozen=True)
class ProbabilityCalibrationReport:
    sample_size: int
    effective_sample_size: float
    total_weight: float
    positive_rate: float
    brier_score: float
    log_loss: float
    expected_calibration_error: float
    maximum_calibration_error: float
    bins: tuple[CalibrationBin, ...]
    status: CalibrationStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.sample_size < 0 or self.effective_sample_size < 0:
            raise ValuationError("calibration sample sizes cannot be negative")
        if not isinstance(self.status, CalibrationStatus):
            raise ValuationError("calibration report status is invalid")

    @property
    def report_hash(self) -> str:
        return sha256_json(self)


@dataclass(frozen=True)
class IntervalCalibrationReport:
    sample_size: int
    effective_sample_size: float
    total_weight: float
    empirical_coverage: float
    target_coverage: float
    coverage_gap: float
    mean_interval_width: float
    status: CalibrationStatus
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.sample_size < 0 or self.effective_sample_size < 0:
            raise ValuationError("calibration sample sizes cannot be negative")
        if not isinstance(self.status, CalibrationStatus):
            raise ValuationError("calibration report status is invalid")

    @property
    def report_hash(self) -> str:
        return sha256_json(self)


@dataclass(frozen=True)
class ModelCalibrationEvidence:
    """OOS evidence cryptographically bound to one model specification."""

    evidence_version: str
    model_spec_hash: str
    calibration_snapshot_id: str
    evaluation_split_id: str
    target_definition_hash: str
    calibration_cutoff_at: dt.datetime
    probability_report: ProbabilityCalibrationReport
    interval_report: IntervalCalibrationReport

    def __post_init__(self) -> None:
        if not VERSION.fullmatch(str(self.evidence_version)):
            raise ValuationError("evidence_version is invalid")
        if not SHA256.fullmatch(str(self.model_spec_hash)):
            raise ValuationError("model_spec_hash must be SHA-256")
        if not SNAPSHOT_ID.fullmatch(str(self.calibration_snapshot_id)):
            raise ValuationError("calibration_snapshot_id must use snapshot_<sha256>")
        if not VERSION.fullmatch(str(self.evaluation_split_id)):
            raise ValuationError("evaluation_split_id is invalid")
        if not SHA256.fullmatch(str(self.target_definition_hash)):
            raise ValuationError("target_definition_hash must be SHA-256")
        if (
            self.calibration_cutoff_at.tzinfo is None
            or self.calibration_cutoff_at.utcoffset() is None
        ):
            raise ValuationError("calibration_cutoff_at must be timezone-aware")
        if self.probability_report.status is not CalibrationStatus.PASS:
            raise ValuationError("probability calibration evidence must PASS")
        if self.interval_report.status is not CalibrationStatus.PASS:
            raise ValuationError("interval calibration evidence must PASS")

    @property
    def compatibility_key(self) -> tuple[str, str, str, dt.datetime]:
        return (
            self.calibration_snapshot_id,
            self.evaluation_split_id,
            self.target_definition_hash,
            self.calibration_cutoff_at.astimezone(dt.timezone.utc),
        )

    @property
    def evidence_hash(self) -> str:
        return sha256_json(
            {
                "evidence_version": self.evidence_version,
                "model_spec_hash": self.model_spec_hash,
                "calibration_snapshot_id": self.calibration_snapshot_id,
                "evaluation_split_id": self.evaluation_split_id,
                "target_definition_hash": self.target_definition_hash,
                "calibration_cutoff_at": self.calibration_cutoff_at,
                "probability_report_hash": self.probability_report.report_hash,
                "interval_report_hash": self.interval_report.report_hash,
            }
        )


@dataclass(frozen=True)
class RiskCalibrationEvidence:
    """OOS probability calibration bound to the value-trap model spec."""

    evidence_version: str
    risk_model_spec_hash: str
    calibration_snapshot_id: str
    evaluation_split_id: str
    target_definition_hash: str
    calibration_cutoff_at: dt.datetime
    probability_report: ProbabilityCalibrationReport

    def __post_init__(self) -> None:
        if not VERSION.fullmatch(str(self.evidence_version)):
            raise ValuationError("evidence_version is invalid")
        if not SHA256.fullmatch(str(self.risk_model_spec_hash)):
            raise ValuationError("risk_model_spec_hash must be SHA-256")
        if not SNAPSHOT_ID.fullmatch(str(self.calibration_snapshot_id)):
            raise ValuationError("calibration_snapshot_id must use snapshot_<sha256>")
        if not VERSION.fullmatch(str(self.evaluation_split_id)):
            raise ValuationError("evaluation_split_id is invalid")
        if not SHA256.fullmatch(str(self.target_definition_hash)):
            raise ValuationError("target_definition_hash must be SHA-256")
        if (
            self.calibration_cutoff_at.tzinfo is None
            or self.calibration_cutoff_at.utcoffset() is None
        ):
            raise ValuationError("calibration_cutoff_at must be timezone-aware")
        if self.probability_report.status is not CalibrationStatus.PASS:
            raise ValuationError("risk probability calibration evidence must PASS")

    @property
    def evidence_hash(self) -> str:
        return sha256_json(
            {
                "evidence_version": self.evidence_version,
                "risk_model_spec_hash": self.risk_model_spec_hash,
                "calibration_snapshot_id": self.calibration_snapshot_id,
                "evaluation_split_id": self.evaluation_split_id,
                "target_definition_hash": self.target_definition_hash,
                "calibration_cutoff_at": self.calibration_cutoff_at,
                "probability_report_hash": self.probability_report.report_hash,
            }
        )


def bind_model_calibration(
    model: ModelDistribution,
    evidence: ModelCalibrationEvidence,
) -> ModelDistribution:
    if model.model_spec_hash != evidence.model_spec_hash:
        raise ValuationError("calibration evidence is bound to another model spec")
    # Calibration metadata must not mutate the forecast specification that the
    # evidence was bound to. In particular, do not add a reason code here: it
    # would change ``model_spec_hash`` after the evidence was created.
    return replace(
        model,
        calibration_status=CalibrationStatus.PASS,
        calibration_hash=evidence.evidence_hash,
    )


def bind_risk_calibration(
    assessment: QualityAssessment,
    evidence: RiskCalibrationEvidence,
) -> QualityAssessment:
    if assessment.risk_model_spec_hash != evidence.risk_model_spec_hash:
        raise ValuationError("risk calibration evidence is bound to another model spec")
    if assessment.risk_feature_coverage < 0.40:
        risk_state = RiskState.DESCONOCIDO
    elif assessment.value_trap_probability >= 0.65:
        risk_state = RiskState.ALTO
    elif assessment.value_trap_probability >= 0.35:
        risk_state = RiskState.MEDIO
    else:
        risk_state = RiskState.BAJO
    reasons = {
        reason
        for reason in assessment.reason_codes
        if reason
        not in {
            "VALUE_TRAP_MODEL_UNCALIBRATED",
            "VALUE_TRAP_LOW_RISK_NOT_CALIBRATED",
        }
    }
    reasons.add("VALUE_TRAP_OOS_CALIBRATION_EVIDENCE_BOUND")
    return replace(
        assessment,
        risk_state=risk_state,
        risk_calibration_status=CalibrationStatus.PASS,
        risk_calibration_hash=evidence.evidence_hash,
        reason_codes=tuple(sorted(reasons)),
    )


def calibration_evidence_hash(
    probability_report: ProbabilityCalibrationReport,
    interval_report: IntervalCalibrationReport,
) -> str:
    """Low-level hash helper retained for report archival."""

    if (
        probability_report.status is not CalibrationStatus.PASS
        or interval_report.status is not CalibrationStatus.PASS
    ):
        raise ValuationError("calibration evidence hash requires PASS reports")
    return sha256_json(
        {
            "probability_report_hash": probability_report.report_hash,
            "interval_report_hash": interval_report.report_hash,
        }
    )


def probability_calibration_report(
    forecasts: Sequence[ProbabilityForecast],
    *,
    bins: int = 10,
    min_samples: int = 100,
    min_effective_samples: float | None = None,
    max_ece: float = 0.10,
    max_brier: float = 0.25,
) -> ProbabilityCalibrationReport:
    if bins < 2:
        raise ValuationError("bins must be >= 2")
    if min_samples < 1:
        raise ValuationError("min_samples must be positive")
    effective_floor = float(
        min_samples if min_effective_samples is None else min_effective_samples
    )
    if not math.isfinite(effective_floor) or effective_floor <= 0:
        raise ValuationError("min_effective_samples must be positive")
    if not 0 <= max_ece <= 1 or not 0 <= max_brier <= 1:
        raise ValuationError("calibration thresholds must be between 0 and 1")
    if not forecasts:
        return ProbabilityCalibrationReport(
            sample_size=0,
            effective_sample_size=0.0,
            total_weight=0.0,
            positive_rate=0.0,
            brier_score=0.0,
            log_loss=0.0,
            expected_calibration_error=0.0,
            maximum_calibration_error=0.0,
            bins=(),
            status=CalibrationStatus.INSUFFICIENT,
            reason_codes=("NO_CALIBRATION_OBSERVATIONS",),
        )

    weights = [item.weight for item in forecasts]
    total_weight = sum(weights)
    effective_size = _effective_sample_size(weights)
    positive_rate = (
        sum(item.weight * float(item.outcome) for item in forecasts) / total_weight
    )
    brier = (
        sum(
            item.weight * (item.probability - float(item.outcome)) ** 2
            for item in forecasts
        )
        / total_weight
    )
    epsilon = 1e-15
    log_loss = -sum(
        item.weight
        * (
            float(item.outcome) * math.log(max(item.probability, epsilon))
            + (1.0 - float(item.outcome))
            * math.log(max(1.0 - item.probability, epsilon))
        )
        for item in forecasts
    ) / total_weight

    calibration_bins: list[CalibrationBin] = []
    ece = 0.0
    maximum_gap = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        members = [
            item
            for item in forecasts
            if (
                lower <= item.probability < upper
                or (index == bins - 1 and item.probability == 1.0)
            )
        ]
        if not members:
            continue
        member_weight = sum(item.weight for item in members)
        mean_probability = (
            sum(item.weight * item.probability for item in members) / member_weight
        )
        empirical_frequency = (
            sum(item.weight * float(item.outcome) for item in members)
            / member_weight
        )
        gap = abs(mean_probability - empirical_frequency)
        ece += member_weight / total_weight * gap
        maximum_gap = max(maximum_gap, gap)
        calibration_bins.append(
            CalibrationBin(
                lower_bound=lower,
                upper_bound=upper,
                count=len(members),
                total_weight=member_weight,
                mean_probability=mean_probability,
                empirical_frequency=empirical_frequency,
                absolute_gap=gap,
            )
        )

    reasons: list[str] = []
    if len(forecasts) < min_samples:
        reasons.append("CALIBRATION_SAMPLE_TOO_SMALL")
    if effective_size < effective_floor:
        reasons.append("CALIBRATION_EFFECTIVE_SAMPLE_TOO_SMALL")
    if reasons:
        status = CalibrationStatus.INSUFFICIENT
    else:
        if ece > max_ece:
            reasons.append("EXPECTED_CALIBRATION_ERROR_TOO_HIGH")
        if brier > max_brier:
            reasons.append("BRIER_SCORE_TOO_HIGH")
        status = CalibrationStatus.PASS if not reasons else CalibrationStatus.FAIL
    return ProbabilityCalibrationReport(
        sample_size=len(forecasts),
        effective_sample_size=effective_size,
        total_weight=total_weight,
        positive_rate=positive_rate,
        brier_score=brier,
        log_loss=log_loss,
        expected_calibration_error=ece,
        maximum_calibration_error=maximum_gap,
        bins=tuple(calibration_bins),
        status=status,
        reason_codes=tuple(reasons),
    )


def interval_calibration_report(
    forecasts: Sequence[IntervalForecast],
    *,
    target_coverage: float = 0.80,
    min_samples: int = 100,
    min_effective_samples: float | None = None,
    tolerance: float = 0.05,
) -> IntervalCalibrationReport:
    if not 0 < target_coverage < 1:
        raise ValuationError("target_coverage must be between 0 and 1")
    if min_samples < 1:
        raise ValuationError("min_samples must be positive")
    effective_floor = float(
        min_samples if min_effective_samples is None else min_effective_samples
    )
    if not math.isfinite(effective_floor) or effective_floor <= 0:
        raise ValuationError("min_effective_samples must be positive")
    if not 0 <= tolerance < 1:
        raise ValuationError("tolerance must be in [0, 1)")
    if not forecasts:
        return IntervalCalibrationReport(
            sample_size=0,
            effective_sample_size=0.0,
            total_weight=0.0,
            empirical_coverage=0.0,
            target_coverage=target_coverage,
            coverage_gap=-target_coverage,
            mean_interval_width=0.0,
            status=CalibrationStatus.INSUFFICIENT,
            reason_codes=("NO_INTERVAL_OBSERVATIONS",),
        )
    weights = [item.weight for item in forecasts]
    total_weight = sum(weights)
    effective_size = _effective_sample_size(weights)
    covered_weight = sum(
        item.weight
        for item in forecasts
        if item.lower <= item.realized <= item.upper
    )
    empirical_coverage = covered_weight / total_weight
    mean_width = (
        sum(item.weight * (item.upper - item.lower) for item in forecasts)
        / total_weight
    )
    gap = empirical_coverage - target_coverage
    reasons: list[str] = []
    if len(forecasts) < min_samples:
        reasons.append("INTERVAL_CALIBRATION_SAMPLE_TOO_SMALL")
    if effective_size < effective_floor:
        reasons.append("INTERVAL_EFFECTIVE_SAMPLE_TOO_SMALL")
    if reasons:
        status = CalibrationStatus.INSUFFICIENT
    elif abs(gap) > tolerance:
        status = CalibrationStatus.FAIL
        reasons.append("INTERVAL_COVERAGE_OUTSIDE_TOLERANCE")
    else:
        status = CalibrationStatus.PASS
    return IntervalCalibrationReport(
        sample_size=len(forecasts),
        effective_sample_size=effective_size,
        total_weight=total_weight,
        empirical_coverage=empirical_coverage,
        target_coverage=target_coverage,
        coverage_gap=gap,
        mean_interval_width=mean_width,
        status=status,
        reason_codes=tuple(reasons),
    )


def conformal_absolute_error(
    realized: Sequence[float],
    predicted_median: Sequence[float],
    *,
    coverage: float = 0.80,
) -> float:
    if len(realized) != len(predicted_median) or not realized:
        raise ValuationError(
            "realized and predicted_median must be non-empty and equally sized"
        )
    if not 0 < coverage < 1:
        raise ValuationError("coverage must be between 0 and 1")
    pairs = [(float(actual), float(predicted)) for actual, predicted in zip(
        realized, predicted_median
    )]
    if any(
        not math.isfinite(actual)
        or not math.isfinite(predicted)
        or actual <= 0
        or predicted <= 0
        for actual, predicted in pairs
    ):
        raise ValuationError("conformal valuation inputs must be positive and finite")
    errors = sorted(abs(actual - predicted) for actual, predicted in pairs)
    rank = math.ceil((len(errors) + 1) * coverage) - 1
    rank = max(0, min(rank, len(errors) - 1))
    return errors[rank]


def apply_conformal_interval(
    *,
    median: float,
    raw_lower: float,
    raw_upper: float,
    absolute_error: float,
) -> tuple[float, float]:
    for label, value in (
        ("median", median),
        ("raw_lower", raw_lower),
        ("raw_upper", raw_upper),
        ("absolute_error", absolute_error),
    ):
        if not math.isfinite(float(value)):
            raise ValuationError(f"{label} must be finite")
    if median <= 0 or raw_lower <= 0 or raw_upper <= 0:
        raise ValuationError("fair-value conformal inputs must be positive")
    if raw_lower > median or raw_upper < median:
        raise ValuationError("raw interval must contain the median")
    if absolute_error < 0:
        raise ValuationError("absolute_error cannot be negative")
    lower = min(raw_lower, median - absolute_error)
    upper = max(raw_upper, median + absolute_error)
    if lower <= 0:
        raise ValuationError("conformal interval implies non-positive fair value")
    return lower, upper


def verify_model_calibration_registry(
    models: Sequence[ModelDistribution],
    registry: Mapping[str, ModelCalibrationEvidence],
) -> tuple[ModelCalibrationEvidence, ...]:
    evidence_rows: list[ModelCalibrationEvidence] = []
    for model in models:
        if (
            model.calibration_status is not CalibrationStatus.PASS
            or model.calibration_hash is None
        ):
            raise ValuationError("model calibration is not PASS")
        evidence = registry.get(model.calibration_hash)
        if evidence is None or evidence.evidence_hash != model.calibration_hash:
            raise ValuationError("model calibration evidence is absent from registry")
        if evidence.model_spec_hash != model.model_spec_hash:
            raise ValuationError("model calibration evidence spec mismatch")
        evidence_rows.append(evidence)
    if len({row.compatibility_key for row in evidence_rows}) != 1:
        raise ValuationError("model calibration evidence uses incompatible OOS splits")
    return tuple(evidence_rows)


def verify_risk_calibration_registry(
    assessment: QualityAssessment,
    registry: Mapping[str, RiskCalibrationEvidence],
) -> RiskCalibrationEvidence:
    if (
        assessment.risk_calibration_status is not CalibrationStatus.PASS
        or assessment.risk_calibration_hash is None
    ):
        raise ValuationError("value-trap calibration is not PASS")
    evidence = registry.get(assessment.risk_calibration_hash)
    if evidence is None or evidence.evidence_hash != assessment.risk_calibration_hash:
        raise ValuationError("risk calibration evidence is absent from registry")
    if evidence.risk_model_spec_hash != assessment.risk_model_spec_hash:
        raise ValuationError("risk calibration evidence spec mismatch")
    return evidence
