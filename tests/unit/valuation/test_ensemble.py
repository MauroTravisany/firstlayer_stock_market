import datetime as dt
import unittest

from packages.valuation.calibration import (
    IntervalForecast,
    ModelCalibrationEvidence,
    ProbabilityForecast,
    RiskCalibrationEvidence,
    bind_model_calibration,
    bind_risk_calibration,
    interval_calibration_report,
    probability_calibration_report,
)
from packages.valuation.ensemble import combine_valuation_models
from packages.valuation.models import (
    ModelDistribution,
    PriceObservation,
    QualityAssessment,
    QualityState,
    RiskState,
    ValuationLineage,
    ValuationState,
)
from packages.valuation.policy import ValuationPolicy
from packages.valuation.routing import EntityType

SNAPSHOT = "snapshot_" + "a" * 64
CALIBRATION_SNAPSHOT = "snapshot_" + "d" * 64
TARGET_HASH = "e" * 64


def price(snapshot=SNAPSHOT):
    return PriceObservation(
        price=100.0,
        observed_at=dt.datetime(2026, 8, 11, 20, tzinfo=dt.timezone.utc),
        available_at=dt.datetime(2026, 8, 11, 20, 1, tzinfo=dt.timezone.utc),
        currency="USD",
        data_snapshot_id=snapshot,
        source_hash="f" * 64,
    )


def lineage(model_version, snapshot=SNAPSHOT, config_char="c"):
    return ValuationLineage(
        data_snapshot_id=snapshot,
        feature_set_version="valuation-features-v1",
        model_version=model_version,
        source_cutoff_at=dt.datetime(2026, 8, 12, tzinfo=dt.timezone.utc),
        currency="USD",
        configuration_hash=config_char * 64,
        peer_universe_hash=("b" * 64 if model_version.startswith("relative") else None),
    )


def probability_report():
    rows = []
    for _ in range(30):
        rows.extend(
            [
                ProbabilityForecast(0.2, False),
                ProbabilityForecast(0.2, False),
                ProbabilityForecast(0.2, False),
                ProbabilityForecast(0.2, False),
                ProbabilityForecast(0.2, True),
                ProbabilityForecast(0.8, True),
                ProbabilityForecast(0.8, True),
                ProbabilityForecast(0.8, True),
                ProbabilityForecast(0.8, True),
                ProbabilityForecast(0.8, False),
            ]
        )
    return probability_calibration_report(rows, min_samples=100)


def interval_report():
    rows = [IntervalForecast(80, 120, 100) for _ in range(240)] + [
        IntervalForecast(80, 120, 140) for _ in range(60)
    ]
    return interval_calibration_report(
        rows,
        target_coverage=0.80,
        min_samples=100,
        tolerance=0.01,
    )


def raw_model(name, family, quantiles, *, confidence=0.95, score=1.0, snapshot=SNAPSHOT):
    return ModelDistribution(
        model_name=name,
        model_family=family,
        p10=quantiles[0],
        p25=quantiles[1],
        p50=quantiles[2],
        p75=quantiles[3],
        p90=quantiles[4],
        confidence=confidence,
        lineage=lineage(name, snapshot=snapshot),
        score=score,
    )


def calibrate_models(models):
    registry = {}
    bound = []
    for model in models:
        evidence = ModelCalibrationEvidence(
            evidence_version="valuation-calibration-v1",
            model_spec_hash=model.model_spec_hash,
            calibration_snapshot_id=CALIBRATION_SNAPSHOT,
            evaluation_split_id="outer-validation-v1",
            target_definition_hash=TARGET_HASH,
            calibration_cutoff_at=dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc),
            probability_report=probability_report(),
            interval_report=interval_report(),
        )
        calibrated = bind_model_calibration(model, evidence)
        bound.append(calibrated)
        registry[evidence.evidence_hash] = evidence
    return tuple(bound), registry


def quality(*, score=0.8, trap=0.1, state=QualityState.ALTA, risk=RiskState.DESCONOCIDO, coverage=1.0, risk_coverage=1.0, snapshot=SNAPSHOT):
    return QualityAssessment(
        quality_score=score,
        quality_state=state,
        value_trap_probability=trap,
        risk_state=risk,
        feature_coverage=coverage,
        risk_feature_coverage=risk_coverage,
        lineage=lineage("quality-risk-v1", snapshot=snapshot, config_char="9"),
    )


def calibrate_risk(assessment):
    evidence = RiskCalibrationEvidence(
        evidence_version="risk-calibration-v1",
        risk_model_spec_hash=assessment.risk_model_spec_hash,
        calibration_snapshot_id=CALIBRATION_SNAPSHOT,
        evaluation_split_id="outer-validation-v1",
        target_definition_hash="8" * 64,
        calibration_cutoff_at=dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc),
        probability_report=probability_report(),
    )
    bound = bind_risk_calibration(assessment, evidence)
    return bound, {evidence.evidence_hash: evidence}


class EnsembleTests(unittest.TestCase):
    def setUp(self):
        self.policy = ValuationPolicy(
            policy_version="wp07a-policy-v2",
            min_model_count=2,
            min_confidence=0.20,
            probability_threshold=0.65,
        )

    def economic_inputs(self):
        models, registry = calibrate_models(
            (
                raw_model(
                    "relative-pe-v2",
                    "relative_pe",
                    (120, 135, 150, 165, 180),
                    score=1.5,
                ),
                raw_model(
                    "fcff-v2", "fcff", (115, 130, 145, 160, 175), score=1.2
                ),
            )
        )
        assessment, risk_registry = calibrate_risk(quality())
        return models, registry, assessment, risk_registry

    def test_economic_classification_requires_bound_model_and_risk_evidence(self):
        models, registry, assessment, risk_registry = self.economic_inputs()
        result = combine_valuation_models(
            price=price(),
            estimates=models,
            quality=assessment,
            policy=self.policy,
            model_calibration_registry=registry,
            risk_calibration_registry=risk_registry,
        )
        self.assertEqual(ValuationState.ECONOMICA, result.valuation_state)
        self.assertTrue(result.distribution_available)
        self.assertGreaterEqual(
            result.probability_economic, self.policy.probability_threshold
        )
        self.assertGreater(result.expected_return_p50, 0)
        self.assertRegex(result.policy_hash, r"^[0-9a-f]{64}$")
        self.assertRegex(result.quality_assessment_hash, r"^[0-9a-f]{64}$")

    def test_missing_model_registry_returns_no_fabricated_distribution(self):
        models, _registry, assessment, risk_registry = self.economic_inputs()
        result = combine_valuation_models(
            price=price(),
            estimates=models,
            quality=assessment,
            policy=self.policy,
            model_calibration_registry=None,
            risk_calibration_registry=risk_registry,
        )
        self.assertEqual(ValuationState.DATOS_INSUFICIENTES, result.valuation_state)
        self.assertFalse(result.distribution_available)
        self.assertIsNone(result.fair_value_p50)
        self.assertIsNone(result.probability_economic)
        self.assertIn("MODEL_CALIBRATION_REGISTRY_REQUIRED", result.reason_codes)

    def test_unbound_low_value_trap_blocks_only_economic_classification(self):
        models, registry, _assessment, _risk_registry = self.economic_inputs()
        uncalibrated = quality(risk=RiskState.DESCONOCIDO)
        result = combine_valuation_models(
            price=price(),
            estimates=models,
            quality=uncalibrated,
            policy=self.policy,
            model_calibration_registry=registry,
        )
        self.assertEqual(ValuationState.DATOS_INSUFICIENTES, result.valuation_state)
        self.assertTrue(result.distribution_available)
        self.assertGreater(result.fair_value_p50, result.current_price)
        self.assertIn(
            "VALUE_TRAP_CALIBRATION_REQUIRED_FOR_ECONOMIC_CLASSIFICATION",
            result.reason_codes,
        )

    def test_high_quality_does_not_turn_expensive_price_into_economic(self):
        models, registry = calibrate_models(
            (
                raw_model(
                    "relative-pe-v2", "relative_pe", (45, 55, 60, 65, 75), score=-2
                ),
                raw_model("fcff-v2", "fcff", (50, 58, 62, 68, 78), score=-1.5),
            )
        )
        assessment = quality(score=0.99, trap=0.05, state=QualityState.ALTA)
        result = combine_valuation_models(
            price=price(),
            estimates=models,
            quality=assessment,
            policy=self.policy,
            model_calibration_registry=registry,
        )
        self.assertEqual(ValuationState.CARA, result.valuation_state)
        self.assertGreater(result.quality_score, 0.9)
        self.assertLess(result.expected_return_p50, 0)

    def test_high_value_trap_can_force_abstention_without_changing_fair_value(self):
        models, registry, _assessment, _risk_registry = self.economic_inputs()
        risky = quality(
            score=0.25,
            trap=0.90,
            state=QualityState.BAJA,
            risk=RiskState.ALTO,
        )
        result = combine_valuation_models(
            price=price(),
            estimates=models,
            quality=risky,
            policy=self.policy,
            model_calibration_registry=registry,
        )
        self.assertEqual(ValuationState.DATOS_INSUFICIENTES, result.valuation_state)
        self.assertGreater(result.fair_value_p50, result.current_price)
        self.assertIn("VALUE_TRAP_RISK_FORCES_ABSTENTION", result.reason_codes)

    def test_incompatible_model_quality_or_price_lineage_fails_closed(self):
        models, registry, assessment, risk_registry = self.economic_inputs()
        incompatible_model = raw_model(
            "fcff-other-v2",
            "fcff",
            (115, 130, 145, 160, 175),
            snapshot="snapshot_" + "7" * 64,
        )
        incompatible_models, incompatible_registry = calibrate_models(
            (models[0], incompatible_model)
        )
        result = combine_valuation_models(
            price=price(),
            estimates=incompatible_models,
            quality=assessment,
            policy=self.policy,
            model_calibration_registry=incompatible_registry,
            risk_calibration_registry=risk_registry,
        )
        self.assertFalse(result.distribution_available)
        self.assertIn("INCOMPATIBLE_MODEL_OR_QUALITY_LINEAGE", result.reason_codes)

        wrong_price = price(snapshot="snapshot_" + "6" * 64)
        result = combine_valuation_models(
            price=wrong_price,
            estimates=models,
            quality=assessment,
            policy=self.policy,
            model_calibration_registry=registry,
            risk_calibration_registry=risk_registry,
        )
        self.assertFalse(result.distribution_available)
        self.assertIn("INCOMPATIBLE_PRICE_LINEAGE", result.reason_codes)

    def test_duplicate_models_or_families_are_not_double_counted(self):
        first = raw_model(
            "relative-pe-v2", "relative_pe", (90, 95, 100, 105, 110)
        )
        second = raw_model(
            "relative-pe-alt-v2", "relative_pe", (92, 97, 102, 107, 112)
        )
        models, registry = calibrate_models((first, second))
        result = combine_valuation_models(
            price=price(),
            estimates=models,
            quality=quality(),
            policy=self.policy,
            model_calibration_registry=registry,
        )
        self.assertFalse(result.distribution_available)
        self.assertIn("DUPLICATE_MODEL_FAMILY", result.reason_codes)

    def test_calibration_evidence_from_different_oos_splits_is_rejected(self):
        first = raw_model(
            "relative-pe-v2", "relative_pe", (90, 95, 100, 105, 110)
        )
        second = raw_model("fcff-v2", "fcff", (92, 97, 102, 107, 112))
        evidence1 = ModelCalibrationEvidence(
            "calibration-v1",
            first.model_spec_hash,
            CALIBRATION_SNAPSHOT,
            "outer-validation-v1",
            TARGET_HASH,
            dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc),
            probability_report(),
            interval_report(),
        )
        evidence2 = ModelCalibrationEvidence(
            "calibration-v1",
            second.model_spec_hash,
            CALIBRATION_SNAPSHOT,
            "outer-validation-v2",
            TARGET_HASH,
            dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc),
            probability_report(),
            interval_report(),
        )
        models = (
            bind_model_calibration(first, evidence1),
            bind_model_calibration(second, evidence2),
        )
        registry = {
            evidence1.evidence_hash: evidence1,
            evidence2.evidence_hash: evidence2,
        }
        result = combine_valuation_models(
            price=price(),
            estimates=models,
            quality=quality(),
            policy=self.policy,
            model_calibration_registry=registry,
        )
        self.assertFalse(result.distribution_available)
        self.assertIn("MODEL_CALIBRATION_EVIDENCE_INVALID", result.reason_codes)

    def test_result_and_hash_are_deterministic_under_model_reordering(self):
        models, registry, assessment, risk_registry = self.economic_inputs()
        first = combine_valuation_models(
            price=price(),
            estimates=models,
            quality=assessment,
            policy=self.policy,
            model_calibration_registry=registry,
            risk_calibration_registry=risk_registry,
        )
        second = combine_valuation_models(
            price=price(),
            estimates=tuple(reversed(models)),
            quality=assessment,
            policy=self.policy,
            model_calibration_registry=registry,
            risk_calibration_registry=risk_registry,
        )
        self.assertEqual(first, second)
        self.assertEqual(first.result_hash, second.result_hash)

    def test_route_failure_remains_fail_closed(self):
        models, registry = calibrate_models(
            (
                raw_model("network-v1", "crypto_network", (90, 95, 100, 105, 110)),
                raw_model("pe-v1", "relative_pe", (90, 95, 100, 105, 110)),
            )
        )
        policy = ValuationPolicy(
            policy_version="wp07a-policy-v2",
            min_model_count=1,
            min_confidence=0,
        )
        result = combine_valuation_models(
            price=price(),
            estimates=models,
            quality=quality(),
            policy=policy,
            entity_type=EntityType.CRYPTO,
            model_calibration_registry=registry,
        )
        self.assertFalse(result.distribution_available)
        self.assertIn("VALUATION_ROUTE_FORBIDDEN_MODEL", result.reason_codes)


if __name__ == "__main__":
    unittest.main()
