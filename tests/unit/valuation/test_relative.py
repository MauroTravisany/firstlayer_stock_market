import datetime as dt
import math
import unittest

from packages.valuation.models import ValuationError, ValuationLineage
from packages.valuation.policy import ValuationPolicy
from packages.valuation.relative import (
    PeerObservation,
    RelativeMetric,
    RelativeSubject,
    estimate_relative_value,
)


def lineage():
    return ValuationLineage(
        data_snapshot_id="snapshot_" + "1" * 64,
        feature_set_version="valuation-features-v1",
        model_version="relative-ridge-v1",
        source_cutoff_at=dt.datetime(2026, 8, 12, tzinfo=dt.timezone.utc),
        currency="USD",
        peer_universe_hash="2" * 64,
        configuration_hash="3" * 64,
    )


def peers():
    rows = []
    for index in range(16):
        features = {
            "growth": 0.03 + index * 0.01,
            "margin": 0.08 + index * 0.008,
            "leverage": 3.0 - index * 0.10,
        }
        log_multiple = (
            2.30
            + 2.0 * features["growth"]
            + 1.1 * features["margin"]
            - 0.18 * features["leverage"]
        )
        rows.append(
            PeerObservation(
                ticker=f"P{index:02d}",
                observed_multiple=math.exp(log_multiple),
                features=features,
            )
        )
    return rows


class RelativeValuationTests(unittest.TestCase):
    def setUp(self):
        self.policy = ValuationPolicy(
            policy_version="wp07a-policy-v1",
            min_peer_count=8,
            ridge_penalty=0.10,
        )

    def test_relative_estimate_is_deterministic_and_detects_cheap_price(self):
        subject = RelativeSubject(
            ticker="TEST",
            metric=RelativeMetric.PE,
            current_price=35.0,
            anchor_per_share=5.0,
            features={"growth": 0.10, "margin": 0.14, "leverage": 2.3},
        )
        first = estimate_relative_value(subject, peers(), lineage(), self.policy)
        second = estimate_relative_value(subject, peers(), lineage(), self.policy)
        self.assertEqual(first, second)
        self.assertGreater(first.predicted_multiple, first.observed_multiple)
        self.assertGreater(first.robust_residual_z, 0)
        self.assertGreater(first.distribution.p50, subject.current_price)
        self.assertEqual(16, first.peer_count)
        self.assertEqual(
            ("growth", "leverage", "margin"), first.feature_names
        )
        self.assertFalse(first.distribution.production_change_allowed)

    def test_expensive_subject_has_negative_relative_score(self):
        subject = RelativeSubject(
            ticker="TEST",
            metric=RelativeMetric.PS,
            current_price=200.0,
            anchor_per_share=4.0,
            features={"growth": 0.10, "margin": 0.14, "leverage": 2.3},
        )
        result = estimate_relative_value(
            subject, peers(), lineage(), self.policy
        )
        self.assertLess(result.robust_residual_z, 0)
        self.assertLess(result.distribution.p50, subject.current_price)

    def test_ev_ebitda_converts_enterprise_to_equity_value(self):
        subject = RelativeSubject(
            ticker="TEST",
            metric=RelativeMetric.EV_EBITDA,
            current_price=50.0,
            enterprise_anchor=100.0,
            net_debt=200.0,
            shares_outstanding=20.0,
            features={"growth": 0.10, "margin": 0.14, "leverage": 2.3},
        )
        result = estimate_relative_value(
            subject, peers(), lineage(), self.policy
        )
        expected_equity_price = (
            result.predicted_multiple * 100.0 - 200.0
        ) / 20.0
        self.assertGreater(expected_equity_price, 0)
        self.assertAlmostEqual(
            expected_equity_price,
            result.distribution.p50,
            delta=result.distribution.p50 * 0.35,
        )

    def test_feature_mismatch_and_small_peer_set_fail_closed(self):
        subject = RelativeSubject(
            ticker="TEST",
            metric=RelativeMetric.PB,
            current_price=50.0,
            anchor_per_share=10.0,
            features={"growth": 0.10, "margin": 0.14, "leverage": 2.3},
        )
        with self.assertRaisesRegex(ValuationError, "at least 8 peers"):
            estimate_relative_value(
                subject, peers()[:7], lineage(), self.policy
            )
        broken = list(peers())
        broken[-1] = PeerObservation(
            ticker="BROKEN",
            observed_multiple=10.0,
            features={"growth": 0.1, "margin": 0.1},
        )
        with self.assertRaisesRegex(ValuationError, "feature mismatch"):
            estimate_relative_value(
                subject, broken, lineage(), self.policy
            )

    def test_material_feature_extrapolation_is_explicit(self):
        subject = RelativeSubject(
            ticker="OUTLIER",
            metric=RelativeMetric.P_FCF,
            current_price=30.0,
            anchor_per_share=3.0,
            features={"growth": 1.5, "margin": 0.9, "leverage": -5.0},
        )
        result = estimate_relative_value(
            subject, peers(), lineage(), self.policy
        )
        self.assertTrue(result.extrapolated_features)
        self.assertIn(
            "SUBJECT_FEATURE_EXTRAPOLATION",
            result.distribution.reason_codes,
        )
        self.assertLess(result.distribution.confidence, 0.7)

    def test_non_positive_anchor_fails_closed(self):
        with self.assertRaisesRegex(ValuationError, "anchor_per_share"):
            RelativeSubject(
                ticker="LOSS",
                metric=RelativeMetric.PE,
                current_price=50.0,
                anchor_per_share=-2.0,
                features={"growth": 0.1},
            )


if __name__ == "__main__":
    unittest.main()
