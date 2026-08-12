import datetime as dt
import unittest

from packages.valuation.ensemble import combine_valuation_models
from packages.valuation.models import (
    ModelDistribution,
    QualityAssessment,
    QualityState,
    RiskState,
    ValuationLineage,
    ValuationState,
)
from packages.valuation.policy import ValuationPolicy


def lineage(model_version, snapshot_char="a", cutoff_day=12):
    return ValuationLineage(
        data_snapshot_id="snapshot_" + snapshot_char * 64,
        feature_set_version="valuation-features-v1",
        model_version=model_version,
        source_cutoff_at=dt.datetime(
            2026, 8, cutoff_day, tzinfo=dt.timezone.utc
        ),
        currency="USD",
        peer_universe_hash="b" * 64,
        configuration_hash="c" * 64,
    )


def model(
    name,
    family,
    quantiles,
    *,
    confidence=0.95,
    score=1.0,
    snapshot_char="a",
):
    return ModelDistribution(
        model_name=name,
        model_family=family,
        p10=quantiles[0],
        p25=quantiles[1],
        p50=quantiles[2],
        p75=quantiles[3],
        p90=quantiles[4],
        confidence=confidence,
        lineage=lineage(name, snapshot_char=snapshot_char),
        score=score,
    )


def quality(
    *,
    quality_score=0.8,
    trap=0.1,
    state=QualityState.ALTA,
    risk=RiskState.BAJO,
    coverage=1.0,
):
    return QualityAssessment(
        quality_score=quality_score,
        quality_state=state,
        value_trap_probability=trap,
        risk_state=risk,
        feature_coverage=coverage,
    )


class EnsembleTests(unittest.TestCase):
    def setUp(self):
        self.policy = ValuationPolicy(
            policy_version="wp07a-policy-v1",
            min_model_count=2,
            min_confidence=0.35,
            probability_threshold=0.65,
        )

    def test_economic_classification_uses_probability_distribution(self):
        estimates = (
            model(
                "relative-pe-v1",
                "relative_pe",
                (120, 135, 150, 165, 180),
                score=1.5,
            ),
            model(
                "fcff-v1",
                "fcff",
                (115, 130, 145, 160, 175),
                score=1.2,
            ),
            model(
                "residual-income-v1",
                "residual_income",
                (110, 125, 140, 155, 170),
                score=1.0,
            ),
        )
        result = combine_valuation_models(
            current_price=100,
            estimates=estimates,
            quality=quality(),
            policy=self.policy,
        )
        self.assertEqual(ValuationState.ECONOMICA, result.valuation_state)
        self.assertGreaterEqual(
            result.probability_economic, self.policy.probability_threshold
        )
        self.assertGreater(result.expected_return_p50, 0)
        self.assertGreater(result.relative_valuation_score, 0)
        self.assertGreater(result.intrinsic_valuation_score, 0)
        self.assertFalse(result.production_change_allowed)

    def test_high_quality_does_not_turn_expensive_price_into_economic(self):
        estimates = (
            model(
                "relative-pe-v1",
                "relative_pe",
                (45, 55, 60, 65, 75),
                score=-2.0,
            ),
            model(
                "fcff-v1",
                "fcff",
                (50, 58, 62, 68, 78),
                score=-1.5,
            ),
        )
        result = combine_valuation_models(
            current_price=100,
            estimates=estimates,
            quality=quality(quality_score=0.99),
            policy=self.policy,
        )
        self.assertEqual(ValuationState.CARA, result.valuation_state)
        self.assertGreater(result.quality_score, 0.9)
        self.assertLess(result.expected_return_p50, 0)

    def test_value_trap_can_force_abstention_without_changing_fair_value(self):
        estimates = (
            model(
                "relative-pe-v1",
                "relative_pe",
                (130, 140, 150, 165, 180),
            ),
            model(
                "fcff-v1",
                "fcff",
                (125, 138, 148, 160, 175),
            ),
        )
        result = combine_valuation_models(
            current_price=100,
            estimates=estimates,
            quality=quality(
                quality_score=0.25,
                trap=0.90,
                state=QualityState.BAJA,
                risk=RiskState.ALTO,
            ),
            policy=self.policy,
        )
        self.assertEqual(
            ValuationState.DATOS_INSUFICIENTES, result.valuation_state
        )
        self.assertGreater(result.fair_value_p50, result.current_price)
        self.assertIn(
            "VALUE_TRAP_RISK_FORCES_ABSTENTION", result.reason_codes
        )

    def test_incompatible_lineage_fails_closed(self):
        estimates = (
            model(
                "relative-pe-v1",
                "relative_pe",
                (90, 95, 100, 105, 110),
                snapshot_char="a",
            ),
            model(
                "fcff-v1",
                "fcff",
                (90, 95, 100, 105, 110),
                snapshot_char="d",
            ),
        )
        result = combine_valuation_models(
            current_price=100,
            estimates=estimates,
            quality=quality(),
            policy=self.policy,
        )
        self.assertEqual(
            ValuationState.DATOS_INSUFICIENTES, result.valuation_state
        )
        self.assertIn("INCOMPATIBLE_MODEL_LINEAGE", result.reason_codes)

    def test_insufficient_model_count_fails_closed(self):
        result = combine_valuation_models(
            current_price=100,
            estimates=(
                model(
                    "relative-pe-v1",
                    "relative_pe",
                    (90, 95, 100, 105, 110),
                ),
            ),
            quality=quality(),
            policy=self.policy,
        )
        self.assertEqual(
            ValuationState.DATOS_INSUFICIENTES, result.valuation_state
        )
        self.assertEqual(1, result.model_count)
        self.assertIn("INSUFFICIENT_APPLICABLE_MODELS", result.reason_codes)

    def test_wide_disagreement_reduces_confidence_or_abstains(self):
        estimates = (
            model(
                "relative-pe-v1",
                "relative_pe",
                (40, 45, 50, 55, 60),
            ),
            model(
                "fcff-v1",
                "fcff",
                (180, 190, 200, 210, 220),
            ),
        )
        result = combine_valuation_models(
            current_price=100,
            estimates=estimates,
            quality=quality(),
            policy=self.policy,
        )
        self.assertLess(result.model_agreement_score, 0.5)
        self.assertEqual(
            ValuationState.DATOS_INSUFICIENTES, result.valuation_state
        )
        self.assertTrue(
            {
                "LOW_MODEL_AGREEMENT",
                "VALUATION_CONFIDENCE_BELOW_POLICY",
                "FAIR_VALUE_INTERVAL_TOO_WIDE",
            }
            & set(result.reason_codes)
        )

    def test_result_and_hash_are_deterministic(self):
        estimates = (
            model(
                "relative-pe-v1",
                "relative_pe",
                (90, 95, 100, 105, 110),
            ),
            model(
                "fcff-v1",
                "fcff",
                (92, 97, 102, 107, 112),
            ),
        )
        first = combine_valuation_models(
            current_price=100,
            estimates=estimates,
            quality=quality(),
            policy=self.policy,
        )
        second = combine_valuation_models(
            current_price=100,
            estimates=tuple(reversed(estimates)),
            quality=quality(),
            policy=self.policy,
        )
        self.assertEqual(first.result_hash, second.result_hash)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
