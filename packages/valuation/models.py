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


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValuationError(f"{name} must be finite")
    return number


def _probability(name: str, value: float) -> float:
    number = _finite(name, value)
    if not 0.0 <= number <= 1.0:
        raise ValuationError(f"{name} must be between 0 and 1")
    return number


@dataclass(frozen=True)
class ValuationLineage:
    """Immutable identity of the data and configuration used by a model."""

    data_snapshot_id: str
    feature_set_version: str
    model_version: str
    source_cutoff_at: dt.datetime
    currency: str
    peer_universe_hash: str | None = None
    configuration_hash: str | None = None

    def __post_init__(self) -> None:
        if not SNAPSHOT_ID.fullmatch(str(self.data_snapshot_id)):
            raise ValuationError("data_snapshot_id must use snapshot_<sha256>")
        for label, value in (
            ("feature_set_version", self.feature_set_version),
            ("model_version", self.model_version),
        ):
            if not VERSION.fullmatch(str(value)):
                raise ValuationError(f"{label} is invalid")
        if self.source_cutoff_at.tzinfo is None or self.source_cutoff_at.utcoffset() is None:
            raise ValuationError("source_cutoff_at must be timezone-aware")
        if not CURRENCY.fullmatch(str(self.currency)):
            raise ValuationError("currency must be a three-letter uppercase code")
        for label, value in (
            ("peer_universe_hash", self.peer_universe_hash),
            ("configuration_hash", self.configuration_hash),
        ):
            if value is not None and not SHA256.fullmatch(str(value)):
                raise ValuationError(f"{label} must be SHA-256")

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
                "peer_universe_hash": self.peer_universe_hash,
                "configuration_hash": self.configuration_hash,
            }
        )


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
    weight: float = 1.0
    score: float | None = None
    reason_codes: tuple[str, ...] = ()
    production_change_allowed: bool = False

    def __post_init__(self) -> None:
        if not VERSION.fullmatch(str(self.model_name)):
            raise ValuationError("model_name is invalid")
        if not VERSION.fullmatch(str(self.model_family)):
            raise ValuationError("model_family is invalid")
        quantiles = tuple(
            _finite(label, value)
            for label, value in (
                ("p10", self.p10),
                ("p25", self.p25),
                ("p50", self.p50),
                ("p75", self.p75),
                ("p90", self.p90),
            )
        )
        if any(value <= 0 for value in quantiles):
            raise ValuationError("fair-value quantiles must be positive")
        if quantiles != tuple(sorted(quantiles)):
            raise ValuationError("fair-value quantiles must be monotonic")
        _probability("confidence", self.confidence)
        if _finite("weight", self.weight) <= 0:
            raise ValuationError("weight must be positive")
        if self.score is not None:
            _finite("score", self.score)
        if self.production_change_allowed:
            raise ValuationError("valuation research cannot permit production changes")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValuationError("reason_codes must be unique")

    @property
    def interval_width_ratio(self) -> float:
        return (self.p90 - self.p10) / self.p50

    @property
    def model_hash(self) -> str:
        return sha256_json(
            {
                "model_name": self.model_name,
                "model_family": self.model_family,
                "quantiles": [self.p10, self.p25, self.p50, self.p75, self.p90],
                "confidence": self.confidence,
                "lineage_hash": self.lineage.lineage_hash,
                "applicability": self.applicability.value,
                "weight": self.weight,
                "score": self.score,
                "reason_codes": self.reason_codes,
                "production_change_allowed": self.production_change_allowed,
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
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _probability("quality_score", self.quality_score)
        _probability("value_trap_probability", self.value_trap_probability)
        _probability("feature_coverage", self.feature_coverage)
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValuationError("reason_codes must be unique")

    @property
    def assessment_hash(self) -> str:
        return sha256_json(
            {
                "quality_score": self.quality_score,
                "quality_state": self.quality_state.value,
                "value_trap_probability": self.value_trap_probability,
                "risk_state": self.risk_state.value,
                "feature_coverage": self.feature_coverage,
                "reason_codes": self.reason_codes,
            }
        )


@dataclass(frozen=True)
class ValuationResult:
    """Combined fair-value distribution and auditable classification."""

    current_price: float
    fair_value_p10: float
    fair_value_p25: float
    fair_value_p50: float
    fair_value_p75: float
    fair_value_p90: float
    expected_return_p10: float
    expected_return_p50: float
    expected_return_p90: float
    probability_economic: float
    probability_expensive: float
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
    model_count: int
    model_hashes: tuple[str, ...]
    reason_codes: tuple[str, ...]
    result_hash: str
    production_change_allowed: bool = False

    def __post_init__(self) -> None:
        current_price = _finite("current_price", self.current_price)
        if current_price <= 0:
            raise ValuationError("current_price must be positive")
        quantiles = (
            self.fair_value_p10,
            self.fair_value_p25,
            self.fair_value_p50,
            self.fair_value_p75,
            self.fair_value_p90,
        )
        if any(_finite("fair_value", value) <= 0 for value in quantiles):
            raise ValuationError("fair values must be positive")
        if quantiles != tuple(sorted(quantiles)):
            raise ValuationError("fair values must be monotonic")
        for label, value in (
            ("expected_return_p10", self.expected_return_p10),
            ("expected_return_p50", self.expected_return_p50),
            ("expected_return_p90", self.expected_return_p90),
        ):
            _finite(label, value)
        for label, value in (
            ("probability_economic", self.probability_economic),
            ("probability_expensive", self.probability_expensive),
            ("quality_score", self.quality_score),
            ("value_trap_probability", self.value_trap_probability),
            ("model_agreement_score", self.model_agreement_score),
            ("valuation_confidence", self.valuation_confidence),
        ):
            _probability(label, value)
        for label, value in (
            ("relative_valuation_score", self.relative_valuation_score),
            ("intrinsic_valuation_score", self.intrinsic_valuation_score),
        ):
            if value is not None:
                _finite(label, value)
        if self.model_count < 0:
            raise ValuationError("model_count cannot be negative")
        if len(self.model_hashes) != self.model_count:
            raise ValuationError("model_hashes length must equal model_count")
        if any(not SHA256.fullmatch(value) for value in self.model_hashes):
            raise ValuationError("model_hashes must be SHA-256")
        if not str(self.entity_type).strip():
            raise ValuationError("entity_type is required")
        if not VERSION.fullmatch(self.policy_version):
            raise ValuationError("policy_version is invalid")
        if not SHA256.fullmatch(self.result_hash):
            raise ValuationError("result_hash must be SHA-256")
        if self.production_change_allowed:
            raise ValuationError("valuation result cannot permit production changes")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValuationError("reason_codes must be unique")


def result_payload_hash(payload: Mapping[str, Any]) -> str:
    """Hash a result payload before instantiating :class:`ValuationResult`."""

    document = dict(payload)
    document.pop("result_hash", None)
    return sha256_json(document)
