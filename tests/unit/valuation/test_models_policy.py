import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from packages.valuation.models import (
    CalibrationStatus,
    ModelDistribution,
    PriceObservation,
    ValuationError,
    ValuationLineage,
    ValuationResult,
    ValuationState,
    QualityState,
    RiskState,
    valuation_result_payload_hash,
)
from packages.valuation.policy import ValuationPolicy, load_policy


def price(snapshot_char="a", currency="USD"):
    return PriceObservation(
        price=100.0,
        observed_at=dt.datetime(2026, 8, 11, 20, tzinfo=dt.timezone.utc),
        available_at=dt.datetime(2026, 8, 11, 20, 1, tzinfo=dt.timezone.utc),
        currency=currency,
        data_snapshot_id="snapshot_" + snapshot_char * 64,
        source_hash="f" * 64,
    )


def lineage(model_version="model-v1", snapshot_char="a"):
    return ValuationLineage(
        data_snapshot_id="snapshot_" + snapshot_char * 64,
        feature_set_version="features-v1",
        model_version=model_version,
        source_cutoff_at=dt.datetime(2026, 8, 12, tzinfo=dt.timezone.utc),
        currency="USD",
        configuration_hash="c" * 64,
        peer_universe_hash="b" * 64,
    )


class ModelAndPolicyTests(unittest.TestCase):
    def test_price_and_lineage_hashes_are_deterministic(self):
        self.assertEqual(price().observation_hash, price().observation_hash)
        self.assertEqual(lineage().lineage_hash, lineage().lineage_hash)
        self.assertEqual(lineage().compatibility_key, lineage().compatibility_key)

    def test_price_and_lineage_temporal_invariants(self):
        with self.assertRaisesRegex(ValuationError, "cannot precede"):
            PriceObservation(
                price=100,
                observed_at=dt.datetime(2026, 8, 12, tzinfo=dt.timezone.utc),
                available_at=dt.datetime(2026, 8, 11, tzinfo=dt.timezone.utc),
                currency="USD",
                data_snapshot_id="snapshot_" + "a" * 64,
                source_hash="b" * 64,
            )
        with self.assertRaisesRegex(ValuationError, "timezone-aware"):
            ValuationLineage(
                data_snapshot_id="snapshot_" + "a" * 64,
                feature_set_version="features-v1",
                model_version="model-v1",
                source_cutoff_at=dt.datetime(2026, 8, 12),
                currency="USD",
                configuration_hash="c" * 64,
            )
        late_price = PriceObservation(
            price=100,
            observed_at=dt.datetime(2026, 8, 12, 1, tzinfo=dt.timezone.utc),
            available_at=dt.datetime(2026, 8, 12, 2, tzinfo=dt.timezone.utc),
            currency="USD",
            data_snapshot_id="snapshot_" + "a" * 64,
            source_hash="b" * 64,
        )
        with self.assertRaisesRegex(ValuationError, "not available"):
            lineage().assert_price_compatible(late_price)

    def test_model_distribution_rejects_non_monotonic_production_or_fake_pass(self):
        with self.assertRaisesRegex(ValuationError, "monotonic"):
            ModelDistribution(
                "model-v1", "relative-pe", 80, 100, 90, 120, 130, 0.7, lineage()
            )
        with self.assertRaisesRegex(ValuationError, "production"):
            ModelDistribution(
                "model-v1",
                "relative-pe",
                80,
                90,
                100,
                110,
                120,
                0.7,
                lineage(),
                production_change_allowed=True,
            )
        with self.assertRaisesRegex(ValuationError, "requires calibration_hash"):
            ModelDistribution(
                "model-v1",
                "relative-pe",
                80,
                90,
                100,
                110,
                120,
                0.7,
                lineage(),
                calibration_status=CalibrationStatus.PASS,
            )

    def test_policy_hash_json_and_peer_floor_are_deterministic(self):
        policy = ValuationPolicy(policy_version="wp07a-policy-v2")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(policy.to_mapping()), encoding="utf-8")
            loaded = load_policy(path)
        self.assertEqual(policy, loaded)
        self.assertEqual(policy.policy_hash, loaded.policy_hash)
        self.assertEqual(13, policy.minimum_peer_observations(3))
        self.assertEqual(1.0, policy.weight_for("relative_pe"))

    def test_policy_rejects_unknown_fields_and_unsafe_thresholds(self):
        with self.assertRaisesRegex(ValuationError, "unknown policy fields"):
            ValuationPolicy.from_mapping({"policy_version": "v01", "surprise": True})
        with self.assertRaisesRegex(ValuationError, "below abstain"):
            ValuationPolicy(
                policy_version="policy-v1",
                max_value_trap_for_economic=0.8,
                value_trap_abstain_threshold=0.7,
            )

    def test_unavailable_distribution_cannot_fabricate_fair_value(self):
        payload = {
            "current_price": 100.0,
            "price_observation_hash": price().observation_hash,
            "data_snapshot_id": price().data_snapshot_id,
            "currency": "USD",
            "valuation_as_of": dt.datetime(2026, 8, 12, tzinfo=dt.timezone.utc),
            "distribution_available": False,
            "fair_value_p10": None,
            "fair_value_p25": None,
            "fair_value_p50": None,
            "fair_value_p75": None,
            "fair_value_p90": None,
            "expected_return_p10": None,
            "expected_return_p50": None,
            "expected_return_p90": None,
            "probability_economic": None,
            "probability_expensive": None,
            "relative_valuation_score": None,
            "intrinsic_valuation_score": None,
            "quality_score": 0.5,
            "value_trap_probability": 0.5,
            "model_agreement_score": 0.0,
            "valuation_confidence": 0.0,
            "valuation_state": ValuationState.DATOS_INSUFICIENTES,
            "quality_state": QualityState.MEDIA,
            "risk_state": RiskState.DESCONOCIDO,
            "entity_type": "GENERAL_CORPORATE",
            "policy_version": "wp07a-policy-v2",
            "policy_hash": "1" * 64,
            "quality_assessment_hash": "2" * 64,
            "model_count": 0,
            "model_hashes": (),
            "reason_codes": ("NO_MODEL",),
            "production_change_allowed": False,
        }
        result = ValuationResult(
            **payload,
            result_hash=valuation_result_payload_hash(payload),
        )
        self.assertIsNone(result.fair_value_p50)
        with self.assertRaisesRegex(ValuationError, "must not fabricate"):
            ValuationResult(
                **{**payload, "fair_value_p50": 100.0},
                result_hash=valuation_result_payload_hash(
                    {**payload, "fair_value_p50": 100.0}
                ),
            )


if __name__ == "__main__":
    unittest.main()
