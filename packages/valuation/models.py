"""Typed contracts for probabilistic, audit-grade valuation research."""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from packages.common.hashing import sha256_json

SNAPSHOT_ID = re.compile(r"^snapshot_[0-9a-f]{64}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
CURRENCY = re.compile(r"^[A-Z]{3}$")


class ValuationError(ValueError):
    """Valuation inputs, lineage, policy or outputs violate a hard invariant."""


class ValuationState(str, Enum):
    ECONOMICA = "ECONOMICA"
    PRECIO_JUSTO = "PRECIO_JUSTO"
    CARA = "CARA"
    DATOS_INSUFICIENTES = "DATOS_INSUFICIENTES"


class QualityState(str, Enum):
    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAJA = "BAJA"
    DATOS_INSUFICIENTES = "DATOS_INSUFICIENTES"


class RiskState(str, Enum):
    BAJO = "BAJO"
    MEDIO = "MEDIO"
    ALTO = "ALTO"
    DESCONOCIDO = "DESCONOCIDO"


class Applicability(str, Enum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class CalibrationStatus(str, Enum):
    PASS = "PASS"
    INSUFFICIENT = "INSUFFICIENT"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValuationError(f"{name} must be finite")
    return number


def _positive(name: str, value: float) -> float:
    number = _finite(name, value)
    if number <= 0:
        raise ValuationError(f"{name} must be positive")
    return number


def _probability(name: str, value: float) -> float:
    number = _finite(name, value)
    if not 0.0 <= number <= 1.0:
        raise ValuationError(f"{name} must be between 0 and 1")
    return number


def _aware_utc(name: str, value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValuationError(f"{name} must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


@dataclass(frozen=True)
class PriceObservation:
    """Point-in-time price and its immutable source lineage."""

    price: float
    observed_at: dt.datetime
    available_at: dt.datetime
    currency: str
    data_snapshot_id: str
    source_hash: str

    def __post_init__(self) -> None:
        _positive("price", self.price)
        observed = _aware_utc("observed_at", self.observed_at)
        available = _aware_utc("available_at", self.available_at)
        if available < observed:
            raise ValuationError("available_at cannot precede observed_at")
        if not CURRENCY.fullmatch(str(self.currency)):
            raise ValuationError("currency must be a three-letter uppercase code")
        if not SNAPSHOT_ID.fullmatch(str(self.data_snapshot_id)):
            raise ValuationError("data_snapshot_id must use snapshot_<sha256>")
        if not SHA256.fullmatch(str(self.source_hash)):
            raise ValuationError("source_hash must be SHA-256")

    @property
    def observation_hash(self) -> str:
        return sha256_json(
            {
                "price": self.price,
                "observed_at": self.observed_at,
                "available_at": self.available_at,
                "currency": self.currency,
                "data_snapshot_id": self.data_snapshot_id,
                "source_hash": self.source_hash,
            }
        )


@dataclass(frozen=True)
class ValuationLineage:
    """Immutable identity of the data and configuration used by a model."""

    data_snapshot_id: str
    feature_set_version: str
    model_version: str
    source_cutoff_at: dt.datetime
    currency: str
    configuration_hash: str
    peer_universe_hash: str | None = None

    def __post_init__(self) -> None:
        if not SNAPSHOT_ID.fullmatch(str(self.data_snapshot_id)):
            raise ValuationError("data_snapshot_id must use snapshot_<sha256>")
        for label, value in (
            ("feature_set_version", self.feature_set_version),
            ("model_version", self.model_version),
        ):
            if not VERSION.fullmatch(str(value)):
                raise ValuationError(f"{label} is invalid")
        _aware_utc("source_cutoff_at", self.source_cutoff_at)
        if not CURRENCY.fullmatch(str(self.currency)):
            raise ValuationError("currency must be a three-letter uppercase code")
        if not SHA256.fullmatch(str(self.configuration_hash)):
            raise ValuationError("configuration_hash must be SHA-256")
        if self.peer_universe_hash is not None and not SHA256.fullmatch(
            str(self.peer_universe_hash)
        ):
            raise ValuationError("peer_universe_hash must be SHA-256")

    @property
    def compatibility_key(self) -> tuple[str, str, dt.datetime, str]:
        return (
            self.data_snapshot_id,
            self.feature_set_version,
            self.source_cutoff_at.astimezone(dt.timezone.utc),
            self.currency,
        )

    @property
    def lineage_hash(self) -> str:
        return sha256_json(
            {
                "data_snapshot_id": self.data_snapshot_id,
                "feature_set_version": self.feature_set_version,
                "model_version": self.model_version,
                "source_cutoff_at": self.source_cutoff_at,
                "currency": self.currency,
                "configuration_hash": self.configuration_hash,
                "peer_universe_hash": self.peer_universe_hash,
            }
        )

    def assert_price_compatible(self, price: PriceObservation) -> None:
        if price.data_snapshot_id != self.data_snapshot_id:
            raise ValuationError("price and model must use the same data snapshot")
        if price.currency != self.currency:
            raise ValuationError("price and model currencies are incompatible")
        if price.available_at.astimezone(dt.timezone.utc) > self.source_cutoff_at.astimezone(
            dt.timezone.utc
        ):
            raise ValuationError("price was not available at the model source cutoff")


@dataclass(frozen=True)
class ModelDistribution:
    """Five-quantile fair-value distribution produced by one model."""

    model_name: str
    model_family: str
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    confidence: float
    lineage: ValuationLineage
    applicability: Applicability = Applicability.APPLICABLE
    score: float | None = None
    calibration_status: CalibrationStatus = CalibrationStatus.UNVERIFIED
    calibration_hash: str | None = None
    reason_codes: tuple[str, ...] = ()
    production_change_allowed: bool = False

    def __post_init__(self) -> None:
        if not VERSION.fullmatch(str(self.model_name)):
            raise ValuationError("model_name is invalid")
        if not VERSION.fullmatch(str(self.model_family)):
            raise ValuationError("model_family is invalid")
        quantiles = tuple(
            _positive(label, value)
            for label, value in (
                ("p10", self.p10),
                ("p25", self.p25),
                ("p50", self.p50),
                ("p75", self.p75),
                ("p90", self.p90),
            )
        )
        if quantiles != tuple(sorted(quantiles)):
            raise ValuationError("fair-value quantiles must be monotonic")
        _probability("confidence", self.confidence)
        if self.score is not None:
            _finite("score", self.score)
        if not isinstance(self.applicability, Applicability):
            raise ValuationError("applicability is invalid")
        if not isinstance(self.calibration_status, CalibrationStatus):
            raise ValuationError("calibration_status is invalid")
        if self.calibration_hash is not None and not SHA256.fullmatch(
            str(self.calibration_hash)
        ):
            raise ValuationError("calibration_hash must be SHA-256")
        if (
            self.calibration_status is not CalibrationStatus.UNVERIFIED
            and self.calibration_hash is None
        ):
            raise ValuationError("verified calibration status requires calibration_hash")
        if self.production_change_allowed:
            raise ValuationError("valuation research cannot permit production changes")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValuationError("reason_codes must be unique")

    @property
    def interval_width_ratio(self) -> float:
        return (self.p90 - self.p10) / self.p50

    @property
    def model_spec_hash(self) -> str:
        """Identity of the forecast before attaching calibration evidence."""

        return sha256_json(
            {
                "model_name": self.model_name,
                "model_family": self.model_family,
                "quantiles": [self.p10, self.p25, self.p50, self.p75, self.p90],
                "confidence": self.confidence,
                "lineage_hash": self.lineage.lineage_hash,
                "applicability": self.applicability.value,
                "score": self.score,
                "reason_codes": self.reason_codes,
                "production_change_allowed": self.production_change_allowed,
            }
        )

    @property
    def model_hash(self) -> str:
        return sha256_json(
            {
                "model_spec_hash": self.model_spec_hash,
                "calibration_status": self.calibration_status.value,
                "calibration_hash": self.calibration_hash,
            }
        )


@dataclass(frozen=True)
class QualityAssessment:
    """Quality and value-trap risk are deliberately separate from price."""

    quality_score: float
    quality_state: QualityState
    value_trap_probability: float
    risk_state: RiskState
    feature_coverage: float
    risk_feature_coverage: float
    lineage: ValuationLineage
    risk_calibration_status: CalibrationStatus = CalibrationStatus.UNVERIFIED
    risk_calibration_hash: str | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _probability("quality_score", self.quality_score)
        _probability("value_trap_probability", self.value_trap_probability)
        _probability("feature_coverage", self.feature_coverage)
        _probability("risk_feature_coverage", self.risk_feature_coverage)
        if not isinstance(self.quality_state, QualityState):
            raise ValuationError("quality_state is invalid")
        if not isinstance(self.risk_state, RiskState):
            raise ValuationError("risk_state is invalid")
        if not isinstance(self.risk_calibration_status, CalibrationStatus):
            raise ValuationError("risk_calibration_status is invalid")
        if self.risk_calibration_hash is not None and not SHA256.fullmatch(
            str(self.risk_calibration_hash)
        ):
            raise ValuationError("risk_calibration_hash must be SHA-256")
        if (
            self.risk_calibration_status is not CalibrationStatus.UNVERIFIED
            and self.risk_calibration_hash is None
        ):
            raise ValuationError(
                "verified risk calibration status requires risk_calibration_hash"
            )
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValuationError("reason_codes must be unique")

    @property
    def risk_model_spec_hash(self) -> str:
        return sha256_json(
            {
                "model_version": self.lineage.model_version,
                "configuration_hash": self.lineage.configuration_hash,
                "feature_set_version": self.lineage.feature_set_version,
            }
        )

    @property
    def assessment_hash(self) -> str:
        return sha256_json(
            {
                "quality_score": self.quality_score,
                "quality_state": self.quality_state.value,
                "value_trap_probability": self.value_trap_probability,
                "risk_state": self.risk_state.value,
                "feature_coverage": self.feature_coverage,
                "risk_feature_coverage": self.risk_feature_coverage,
                "lineage_hash": self.lineage.lineage_hash,
                "risk_calibration_status": self.risk_calibration_status.value,
                "risk_calibration_hash": self.risk_calibration_hash,
                "reason_codes": self.reason_codes,
            }
        )


@dataclass(frozen=True)
class ValuationResult:
    """Combined fair-value distribution and auditable classification."""

    current_price: float
    price_observation_hash: str
    data_snapshot_id: str
    currency: str
    valuation_as_of: dt.datetime
    distribution_available: bool
    fair_value_p10: float | None
    fair_value_p25: float | None
    fair_value_p50: float | None
    fair_value_p75: float | None
    fair_value_p90: float | None
    expected_return_p10: float | None
    expected_return_p50: float | None
    expected_return_p90: float | None
    probability_economic: float | None
    probability_expensive: float | None
    relative_valuation_score: float | None
    intrinsic_valuation_score: float | None
    quality_score: float
    value_trap_probability: float
    model_agreement_score: float
    valuation_confidence: float
    valuation_state: ValuationState
    quality_state: QualityState
    risk_state: RiskState
    entity_type: str
    policy_version: str
    policy_hash: str
    quality_assessment_hash: str
    model_count: int
    model_hashes: tuple[str, ...]
    reason_codes: tuple[str, ...]
    result_hash: str
    production_change_allowed: bool = False

    def __post_init__(self) -> None:
        current_price = _positive("current_price", self.current_price)
        if not SHA256.fullmatch(str(self.price_observation_hash)):
            raise ValuationError("price_observation_hash must be SHA-256")
        if not SNAPSHOT_ID.fullmatch(str(self.data_snapshot_id)):
            raise ValuationError("data_snapshot_id must use snapshot_<sha256>")
        if not CURRENCY.fullmatch(str(self.currency)):
            raise ValuationError("currency must be a three-letter uppercase code")
        _aware_utc("valuation_as_of", self.valuation_as_of)
        if not isinstance(self.distribution_available, bool):
            raise ValuationError("distribution_available must be boolean")

        distribution_fields = (
            self.fair_value_p10,
            self.fair_value_p25,
            self.fair_value_p50,
            self.fair_value_p75,
            self.fair_value_p90,
            self.expected_return_p10,
            self.expected_return_p50,
            self.expected_return_p90,
            self.probability_economic,
            self.probability_expensive,
        )
        if self.distribution_available:
            if any(value is None for value in distribution_fields):
                raise ValuationError(
                    "available distribution requires quantiles, returns and probabilities"
                )
            quantiles = tuple(
                _positive("fair_value", value)
                for value in (
                    self.fair_value_p10,
                    self.fair_value_p25,
                    self.fair_value_p50,
                    self.fair_value_p75,
                    self.fair_value_p90,
                )
            )
            if quantiles != tuple(sorted(quantiles)):
                raise ValuationError("fair values must be monotonic")
            returns = (
                self.expected_return_p10,
                self.expected_return_p50,
                self.expected_return_p90,
            )
            expected = (
                quantiles[0] / current_price - 1.0,
                quantiles[2] / current_price - 1.0,
                quantiles[4] / current_price - 1.0,
            )
            for actual, calculated in zip(returns, expected):
                _finite("expected_return", actual)
                if not math.isclose(
                    float(actual), calculated, rel_tol=0.0, abs_tol=1e-12
                ):
                    raise ValuationError(
                        "expected returns do not match price and fair-value quantiles"
                    )
            _probability("probability_economic", self.probability_economic)
            _probability("probability_expensive", self.probability_expensive)
        else:
            if any(value is not None for value in distribution_fields):
                raise ValuationError(
                    "unavailable distribution must not fabricate fair-value outputs"
                )
            if self.valuation_state is not ValuationState.DATOS_INSUFICIENTES:
                raise ValuationError(
                    "missing distribution requires DATOS_INSUFICIENTES"
                )

        for label, value in (
            ("relative_valuation_score", self.relative_valuation_score),
            ("intrinsic_valuation_score", self.intrinsic_valuation_score),
        ):
            if value is not None:
                _finite(label, value)
        for label, value in (
            ("quality_score", self.quality_score),
            ("value_trap_probability", self.value_trap_probability),
            ("model_agreement_score", self.model_agreement_score),
            ("valuation_confidence", self.valuation_confidence),
        ):
            _probability(label, value)
        if not isinstance(self.valuation_state, ValuationState):
            raise ValuationError("valuation_state is invalid")
        if not isinstance(self.quality_state, QualityState):
            raise ValuationError("quality_state is invalid")
        if not isinstance(self.risk_state, RiskState):
            raise ValuationError("risk_state is invalid")
        if self.model_count < 0:
            raise ValuationError("model_count cannot be negative")
        if len(self.model_hashes) != self.model_count:
            raise ValuationError("model_hashes length must equal model_count")
        if any(not SHA256.fullmatch(value) for value in self.model_hashes):
            raise ValuationError("model_hashes must be SHA-256")
        if len(set(self.model_hashes)) != len(self.model_hashes):
            raise ValuationError("model_hashes must be unique")
        if not str(self.entity_type).strip():
            raise ValuationError("entity_type is required")
        if not VERSION.fullmatch(self.policy_version):
            raise ValuationError("policy_version is invalid")
        for label, digest in (
            ("policy_hash", self.policy_hash),
            ("quality_assessment_hash", self.quality_assessment_hash),
            ("result_hash", self.result_hash),
        ):
            if not SHA256.fullmatch(str(digest)):
                raise ValuationError(f"{label} must be SHA-256")
        if self.production_change_allowed:
            raise ValuationError("valuation result cannot permit production changes")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValuationError("reason_codes must be unique")
        if self.result_hash != valuation_result_payload_hash(self.to_hash_payload()):
            raise ValuationError("result_hash does not match valuation result payload")

    def to_hash_payload(self) -> dict[str, Any]:
        return {
            "current_price": self.current_price,
            "price_observation_hash": self.price_observation_hash,
            "data_snapshot_id": self.data_snapshot_id,
            "currency": self.currency,
            "valuation_as_of": self.valuation_as_of,
            "distribution_available": self.distribution_available,
            "fair_value_p10": self.fair_value_p10,
            "fair_value_p25": self.fair_value_p25,
            "fair_value_p50": self.fair_value_p50,
            "fair_value_p75": self.fair_value_p75,
            "fair_value_p90": self.fair_value_p90,
            "expected_return_p10": self.expected_return_p10,
            "expected_return_p50": self.expected_return_p50,
            "expected_return_p90": self.expected_return_p90,
            "probability_economic": self.probability_economic,
            "probability_expensive": self.probability_expensive,
            "relative_valuation_score": self.relative_valuation_score,
            "intrinsic_valuation_score": self.intrinsic_valuation_score,
            "quality_score": self.quality_score,
            "value_trap_probability": self.value_trap_probability,
            "model_agreement_score": self.model_agreement_score,
            "valuation_confidence": self.valuation_confidence,
            "valuation_state": self.valuation_state.value,
            "quality_state": self.quality_state.value,
            "risk_state": self.risk_state.value,
            "entity_type": self.entity_type,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "quality_assessment_hash": self.quality_assessment_hash,
            "model_count": self.model_count,
            "model_hashes": self.model_hashes,
            "reason_codes": self.reason_codes,
            "production_change_allowed": self.production_change_allowed,
        }


def valuation_result_payload_hash(payload: Mapping[str, Any]) -> str:
    """Hash a result payload before instantiating :class:`ValuationResult`."""

    document = dict(payload)
    document.pop("result_hash", None)
    return sha256_json(document)


# Backward-compatible alias retained inside the new package API.
result_payload_hash = valuation_result_payload_hash
