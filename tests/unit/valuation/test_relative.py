import datetime as dt
import math
import unittest

from packages.valuation.models import PriceObservation, ValuationError, ValuationLineage
from packages.valuation.policy import ValuationPolicy
from packages.valuation.relative import (
    RELATIVE_MODEL_VERSION,
    PeerObservation,
    RelativeMetric,
    RelativeSubject,
    build_peer_universe_hash,
    build_relative_configuration_hash,
    estimate_relative_value,
)


def price(snapshot_char="1"):
    return PriceObservation(
        price=35.0,
        observed_at=dt.datetime(2026, 8, 11, 20, tzinfo=dt.timezone.utc),
        available_at=dt.datetime(2026, 8, 11, 20, 1, tzinfo=dt.timezone.utc),
        currency="USD",
        data_snapshot_id="snapshot_" + snapshot_char * 64,
        source_hash="9" * 64,
    )


def peers(count=20):
    rows = []
    for index in range(count):
        features = {
            "growth": 0.03 + index * 0.008,
            "margin": 0.08 + index * 0.006,
            "leverage": 3.0 - index * 0.08,
        }
        log_multiple = (
            2.30
            + 2.0 * features["growth"]
            + 1.1 * features["margin"]
            - 0.18 * features["leverage"]
            + (0.03 if index % 2 else -0.03)
        )
        rows.append(
            PeerObservation(
                ticker=f"P{index:02d}",
                observed_multiple=math.exp(log_multiple),
                features=features,
            )
        )
    return rows


def lineage(metric, peer_rows, policy, snapshot_char="1"):
    feature_names = tuple(sorted(peer_rows[0].features))
    return ValuationLineage(
        data_snapshot_id="snapshot_" + snapshot_char * 64,
        feature_set_version="valuation-features-v1",
        model_version=RELATIVE_MODEL_VERSION,
        source_cutoff_at=dt.datetime(2026, 8, 12, tzinfo=dt.timezone.utc),
        currency="USD",
        configuration_hash=build_relative_configuration_hash(
            metric, feature_names, policy
        ),
        peer_universe_hash=build_peer_universe_hash(peer_rows),
    )


class RelativeValuationTests(unittest.TestCase):
    def setUp(self):
        self.policy = ValuationPolicy(
            policy_version="wp07a-policy-v2",
            min_peer_count=8,
            min_peer_observations_per_parameter=3,
            ridge_penalty=0.10,
        )

    def test_relative_estimate_is_deterministic_and_uses_loo_uncertainty(self):
        peer_rows = peers()
        subject = RelativeSubject(
            ticker="TEST",
            metric=RelativeMetric.PE,
            price=price(),
            anchor_per_share=5.0,
            features={"growth": 0.10, "margin": 0.14, "leverage": 2.3},
        )
        model_lineage = lineage(RelativeMetric.PE, peer_rows, self.policy)
        first = estimate_relative_value(
            subject, peer_rows, model_lineage, self.policy
        )
        second = estimate_relative_value(
            subject, peer_rows, model_lineage, self.policy
        )
        self.assertEqual(first, second)
        self.assertGreater(first.predicted_multiple, first.observed_multiple)
        self.assertGreater(first.robust_residual_z, 0)
        self.assertGreater(first.distribution.p50, subject.price.price)
        self.assertEqual("LEAVE_ONE_OUT", first.validation_method)
        self.assertIn(
            "LEAVE_ONE_OUT_RESIDUAL_UNCERTAINTY",
            first.distribution.reason_codes,
        )
        self.assertIn(
            "MODEL_REQUIRES_OOS_CALIBRATION",
            first.distribution.reason_codes,
        )
        self.assertLessEqual(first.distribution.confidence, 0.75)

    def test_expensive_subject_has_negative_relative_score(self):
        peer_rows = peers()
        expensive_price = PriceObservation(
            price=200.0,
            observed_at=price().observed_at,
            available_at=price().available_at,
            currency="USD",
            data_snapshot_id=price().data_snapshot_id,
            source_hash=price().source_hash,
        )
        subject = RelativeSubject(
            ticker="TEST",
            metric=RelativeMetric.PS,
            price=expensive_price,
            anchor_per_share=4.0,
            features={"growth": 0.10, "margin": 0.14, "leverage": 2.3},
        )
        result = estimate_relative_value(
            subject,
            peer_rows,
            lineage(RelativeMetric.PS, peer_rows, self.policy),
            self.policy,
        )
        self.assertLess(result.robust_residual_z, 0)
        self.assertLess(result.distribution.p50, subject.price.price)

    def test_ev_ebitda_converts_enterprise_to_equity_value(self):
        peer_rows = peers()
        subject = RelativeSubject(
            ticker="TEST",
            metric=RelativeMetric.EV_EBITDA,
            price=PriceObservation(
                price=50.0,
                observed_at=price().observed_at,
                available_at=price().available_at,
                currency="USD",
                data_snapshot_id=price().data_snapshot_id,
                source_hash=price().source_hash,
            ),
            enterprise_anchor=100.0,
            net_debt=200.0,
            shares_outstanding=20.0,
            features={"growth": 0.10, "margin": 0.14, "leverage": 2.3},
        )
        result = estimate_relative_value(
            subject,
            peer_rows,
            lineage(RelativeMetric.EV_EBITDA, peer_rows, self.policy),
            self.policy,
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

    def test_duplicate_self_inclusion_and_small_peer_set_fail_closed(self):
        peer_rows = peers()
        subject = RelativeSubject(
            ticker="TEST",
            metric=RelativeMetric.PB,
            price=price(),
            anchor_per_share=10.0,
            features={"growth": 0.10, "margin": 0.14, "leverage": 2.3},
        )
        with self.assertRaisesRegex(ValuationError, "at least 13 peers"):
            estimate_relative_value(
                subject,
                peer_rows[:12],
                lineage(RelativeMetric.PB, peer_rows[:12], self.policy),
                self.policy,
            )
        duplicate = list(peer_rows)
        duplicate[-1] = PeerObservation(
            ticker=duplicate[0].ticker,
            observed_multiple=duplicate[-1].observed_multiple,
            features=duplicate[-1].features,
        )
        with self.assertRaisesRegex(ValuationError, "unique"):
            build_peer_universe_hash(duplicate)
        self_included = list(peer_rows)
        self_included[-1] = PeerObservation(
            ticker="TEST",
            observed_multiple=peer_rows[-1].observed_multiple,
            features=peer_rows[-1].features,
        )
        with self.assertRaisesRegex(ValuationError, "subject ticker"):
            estimate_relative_value(
                subject,
                self_included,
                lineage(RelativeMetric.PB, self_included, self.policy),
                self.policy,
            )

    def test_peer_and_configuration_hashes_must_match_actual_inputs(self):
        peer_rows = peers()
        subject = RelativeSubject(
            ticker="TEST",
            metric=RelativeMetric.PE,
            price=price(),
            anchor_per_share=5.0,
            features={"growth": 0.10, "margin": 0.14, "leverage": 2.3},
        )
        valid = lineage(RelativeMetric.PE, peer_rows, self.policy)
        wrong_peer_hash = ValuationLineage(
            data_snapshot_id=valid.data_snapshot_id,
            feature_set_version=valid.feature_set_version,
            model_version=valid.model_version,
            source_cutoff_at=valid.source_cutoff_at,
            currency=valid.currency,
            configuration_hash=valid.configuration_hash,
            peer_universe_hash="0" * 64,
        )
        with self.assertRaisesRegex(ValuationError, "peer_universe_hash"):
            estimate_relative_value(subject, peer_rows, wrong_peer_hash, self.policy)
        wrong_config = ValuationLineage(
            data_snapshot_id=valid.data_snapshot_id,
            feature_set_version=valid.feature_set_version,
            model_version=valid.model_version,
            source_cutoff_at=valid.source_cutoff_at,
            currency=valid.currency,
            configuration_hash="0" * 64,
            peer_universe_hash=valid.peer_universe_hash,
        )
        with self.assertRaisesRegex(ValuationError, "configuration_hash"):
            estimate_relative_value(subject, peer_rows, wrong_config, self.policy)

    def test_price_snapshot_or_cutoff_mismatch_fails_closed(self):
        peer_rows = peers()
        subject = RelativeSubject(
            ticker="TEST",
            metric=RelativeMetric.PE,
            price=price(snapshot_char="2"),
            anchor_per_share=5.0,
            features={"growth": 0.10, "margin": 0.14, "leverage": 2.3},
        )
        with self.assertRaisesRegex(ValuationError, "same data snapshot"):
            estimate_relative_value(
                subject,
                peer_rows,
                lineage(RelativeMetric.PE, peer_rows, self.policy, snapshot_char="1"),
                self.policy,
            )

    def test_material_feature_extrapolation_is_explicit(self):
        peer_rows = peers()
        subject = RelativeSubject(
            ticker="OUTLIER",
            metric=RelativeMetric.P_FCF,
            price=price(),
            anchor_per_share=3.0,
            features={"growth": 1.5, "margin": 0.9, "leverage": -5.0},
        )
        result = estimate_relative_value(
            subject,
            peer_rows,
            lineage(RelativeMetric.P_FCF, peer_rows, self.policy),
            self.policy,
        )
        self.assertTrue(result.extrapolated_features)
        self.assertIn(
            "SUBJECT_FEATURE_EXTRAPOLATION", result.distribution.reason_codes
        )


if __name__ == "__main__":
    unittest.main()
