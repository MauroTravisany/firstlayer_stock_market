import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from packages.valuation.models import (
    ModelDistribution,
    ValuationError,
    ValuationLineage,
)
from packages.valuation.policy import ValuationPolicy, load_policy


def lineage(model_version="model-v1"):
    return ValuationLineage(
        data_snapshot_id="snapshot_" + "a" * 64,
        feature_set_version="features-v1",
        model_version=model_version,
        source_cutoff_at=dt.datetime(2026, 8, 12, tzinfo=dt.timezone.utc),
        currency="USD",
        peer_universe_hash="b" * 64,
        configuration_hash="c" * 64,
    )


class ModelAndPolicyTests(unittest.TestCase):
    def test_lineage_hash_is_deterministic(self):
        first = lineage()
        second = lineage()
        self.assertEqual(first.lineage_hash, second.lineage_hash)
        self.assertEqual(first.compatibility_key, second.compatibility_key)

    def test_lineage_requires_timezone_and_hashes(self):
        with self.assertRaisesRegex(ValuationError, "timezone-aware"):
            ValuationLineage(
                data_snapshot_id="snapshot_" + "a" * 64,
                feature_set_version="features-v1",
                model_version="model-v1",
                source_cutoff_at=dt.datetime(2026, 8, 12),
                currency="USD",
            )
        with self.assertRaisesRegex(ValuationError, "peer_universe_hash"):
            ValuationLineage(
                data_snapshot_id="snapshot_" + "a" * 64,
                feature_set_version="features-v1",
                model_version="model-v1",
                source_cutoff_at=dt.datetime(
                    2026, 8, 12, tzinfo=dt.timezone.utc
                ),
                currency="USD",
                peer_universe_hash="not-a-hash",
            )

    def test_model_distribution_rejects_non_monotonic_or_production(self):
        with self.assertRaisesRegex(ValuationError, "monotonic"):
            ModelDistribution(
                model_name="model-v1",
                model_family="relative-pe",
                p10=80,
                p25=100,
                p50=90,
                p75=120,
                p90=130,
                confidence=0.7,
                lineage=lineage(),
            )
        with self.assertRaisesRegex(ValuationError, "production"):
            ModelDistribution(
                model_name="model-v1",
                model_family="relative-pe",
                p10=80,
                p25=90,
                p50=100,
                p75=110,
                p90=120,
                confidence=0.7,
                lineage=lineage(),
                production_change_allowed=True,
            )

    def test_policy_hash_and_json_loading_are_deterministic(self):
        policy = ValuationPolicy(policy_version="wp07a-policy-v1")
        payload = policy.to_mapping()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_policy(path)
        self.assertEqual(policy, loaded)
        self.assertEqual(policy.policy_hash, loaded.policy_hash)

    def test_policy_rejects_unknown_fields_and_unsafe_thresholds(self):
        with self.assertRaisesRegex(ValuationError, "unknown policy fields"):
            ValuationPolicy.from_mapping(
                {"policy_version": "v1", "surprise": True}
            )
        with self.assertRaisesRegex(ValuationError, "below abstain"):
            ValuationPolicy(
                policy_version="v1",
                max_value_trap_for_economic=0.8,
                value_trap_abstain_threshold=0.7,
            )


if __name__ == "__main__":
    unittest.main()
