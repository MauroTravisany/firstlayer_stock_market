import datetime as dt
import unittest

from packages.common import hashing


class HashingTests(unittest.TestCase):
    def test_canonical_json_is_order_independent(self):
        left = {"b": [2, 1], "a": {"z": 3, "y": True}}
        right = {"a": {"y": True, "z": 3}, "b": [2, 1]}
        self.assertEqual(hashing.canonical_json(left), hashing.canonical_json(right))
        self.assertEqual(hashing.sha256_json(left), hashing.sha256_json(right))

    def test_negative_zero_has_one_canonical_representation(self):
        self.assertEqual(
            hashing.canonical_json({"value": -0.0}),
            hashing.canonical_json({"value": 0.0}),
        )

    def test_timezone_is_normalized_to_utc(self):
        value = {
            "at": dt.datetime(
                2026,
                8,
                10,
                20,
                tzinfo=dt.timezone(dt.timedelta(hours=-4)),
            )
        }
        self.assertIn("2026-08-11T00:00:00Z", hashing.canonical_json(value))

    def test_non_finite_and_naive_datetime_fail(self):
        for value in (
            {"x": float("nan")},
            {"x": dt.datetime(2026, 1, 1)},
        ):
            with self.subTest(value=value):
                with self.assertRaises(hashing.CanonicalizationError):
                    hashing.canonical_json(value)

    def test_candidate_ids_are_global_to_experiment_and_run(self):
        experiment = "123e4567-e89b-42d3-a456-426614174000"
        run_a = hashing.run_id(experiment, "attempt-a")
        run_b = hashing.run_id(experiment, "attempt-b")
        config = {"weight": 1.0}
        first = hashing.candidate_id(experiment, run_a, 1, None, config)
        repeated = hashing.candidate_id(experiment, run_a, 1, None, config)
        other_run = hashing.candidate_id(experiment, run_b, 1, None, config)
        self.assertEqual(first, repeated)
        self.assertNotEqual(first, other_run)
        self.assertRegex(first, hashing.CANDIDATE_ID)
