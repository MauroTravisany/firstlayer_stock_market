import datetime as dt
import unittest

from packages.valuation.calibration import (
    IntervalForecast,
    ModelCalibrationEvidence,
    ProbabilityForecast,
    RiskCalibrationEvidence,
    apply_conformal_interval,
    bind_model_calibration,
    calibration_evidence_hash,
    conformal_absolute_error,
    interval_calibration_report,
    probability_calibration_report,
)
from packages.valuation.models import (
    CalibrationStatus,
    ModelDistribution,
    ValuationError,
    ValuationLineage,
)


def lineage():
    return ValuationLineage(
        data_snapshot_id="snapshot_" + "a" * 64,
        feature_set_version="valuation-features-v1",
        model_version="model-v1",
        source_cutoff_at=dt.datetime(2026, 8, 12, tzinfo=dt.timezone.utc),
        currency="USD",
        configuration_hash="b" * 64,
    )


def perfect_probability_report():
    forecasts = []
    for _ in range(50):
        forecasts.extend(
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
    return probability_calibration_report(forecasts, bins=10, min_samples=100)


def passing_interval_report():
    forecasts = [IntervalForecast(90, 110, 100) for _ in range(80)] + [
        IntervalForecast(90, 110, 120) for _ in range(20)
    ]
    return interval_calibration_report(
        forecasts,
        target_coverage=0.80,
        min_samples=100,
        tolerance=0.01,
    )


class CalibrationTests(unittest.TestCase):
    def test_perfect_probability_calibration(self):
        report = perfect_probability_report()
        self.assertEqual(CalibrationStatus.PASS, report.status)
        self.assertAlmostEqual(0.0, report.expected_calibration_error)
        self.assertLess(report.brier_score, 0.25)
        self.assertEqual(500, report.sample_size)
        self.assertEqual(500, report.effective_sample_size)

    def test_weight_concentration_reduces_effective_sample_and_blocks_pass(self):
        forecasts = [ProbabilityForecast(0.5, index % 2 == 0) for index in range(99)]
        forecasts.append(ProbabilityForecast(0.5, True, weight=1000))
        report = probability_calibration_report(
            forecasts,
            min_samples=100,
            min_effective_samples=80,
            max_ece=1.0,
            max_brier=1.0,
        )
        self.assertEqual(CalibrationStatus.INSUFFICIENT, report.status)
        self.assertIn("CALIBRATION_EFFECTIVE_SAMPLE_TOO_SMALL", report.reason_codes)

    def test_overconfident_forecasts_fail(self):
        forecasts = [
            ProbabilityForecast(0.99, index % 2 == 0) for index in range(200)
        ]
        report = probability_calibration_report(
            forecasts,
            min_samples=100,
            max_ece=0.10,
            max_brier=0.25,
        )
        self.assertEqual(CalibrationStatus.FAIL, report.status)
        self.assertIn("EXPECTED_CALIBRATION_ERROR_TOO_HIGH", report.reason_codes)
        self.assertIn("BRIER_SCORE_TOO_HIGH", report.reason_codes)

    def test_small_sample_is_insufficient_not_pass(self):
        report = probability_calibration_report(
            [ProbabilityForecast(0.7, True) for _ in range(10)],
            min_samples=100,
        )
        self.assertEqual(CalibrationStatus.INSUFFICIENT, report.status)
        self.assertIn("CALIBRATION_SAMPLE_TOO_SMALL", report.reason_codes)

    def test_interval_coverage_report(self):
        report = passing_interval_report()
        self.assertEqual(CalibrationStatus.PASS, report.status)
        self.assertAlmostEqual(0.80, report.empirical_coverage)
        self.assertAlmostEqual(20.0, report.mean_interval_width)

    def test_model_evidence_is_bound_to_exact_model_spec(self):
        model = ModelDistribution(
            "model-v1",
            "fcff",
            80,
            90,
            100,
            110,
            120,
            0.5,
            lineage(),
        )
        evidence = ModelCalibrationEvidence(
            evidence_version="calibration-evidence-v1",
            model_spec_hash=model.model_spec_hash,
            calibration_snapshot_id="snapshot_" + "c" * 64,
            evaluation_split_id="outer-validation-v1",
            target_definition_hash="d" * 64,
            calibration_cutoff_at=dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc),
            probability_report=perfect_probability_report(),
            interval_report=passing_interval_report(),
        )
        bound = bind_model_calibration(model, evidence)
        self.assertEqual(CalibrationStatus.PASS, bound.calibration_status)
        self.assertEqual(evidence.evidence_hash, bound.calibration_hash)
        self.assertNotEqual(model.model_hash, bound.model_hash)
        different = ModelDistribution(
            "other-v1",
            "fcff",
            80,
            90,
            100,
            110,
            120,
            0.5,
            lineage(),
        )
        with self.assertRaisesRegex(ValuationError, "another model spec"):
            bind_model_calibration(different, evidence)

    def test_calibration_hash_requires_both_reports_to_pass(self):
        self.assertRegex(
            calibration_evidence_hash(
                perfect_probability_report(), passing_interval_report()
            ),
            r"^[0-9a-f]{64}$",
        )
        insufficient = probability_calibration_report(
            [ProbabilityForecast(0.5, True)], min_samples=100
        )
        with self.assertRaisesRegex(ValuationError, "requires PASS"):
            calibration_evidence_hash(insufficient, passing_interval_report())

    def test_conformal_error_and_interval(self):
        residual = conformal_absolute_error(
            realized=[100, 102, 98, 110, 90],
            predicted_median=[100, 100, 100, 100, 100],
            coverage=0.80,
        )
        self.assertEqual(10.0, residual)
        self.assertEqual(
            (90, 110),
            apply_conformal_interval(
                median=100,
                raw_lower=95,
                raw_upper=105,
                absolute_error=residual,
            ),
        )

    def test_invalid_or_non_positive_intervals_fail_closed(self):
        with self.assertRaisesRegex(ValuationError, "lower"):
            IntervalForecast(110, 90, 100)
        with self.assertRaisesRegex(ValuationError, "positive"):
            IntervalForecast(-1, 90, 20)
        with self.assertRaisesRegex(ValuationError, "contain the median"):
            apply_conformal_interval(
                median=100,
                raw_lower=101,
                raw_upper=110,
                absolute_error=5,
            )
        with self.assertRaisesRegex(ValuationError, "non-positive"):
            apply_conformal_interval(
                median=5,
                raw_lower=1,
                raw_upper=10,
                absolute_error=8,
            )

    def test_risk_evidence_requires_probability_pass(self):
        report = perfect_probability_report()
        evidence = RiskCalibrationEvidence(
            evidence_version="risk-calibration-v1",
            risk_model_spec_hash="e" * 64,
            calibration_snapshot_id="snapshot_" + "f" * 64,
            evaluation_split_id="outer-validation-v1",
            target_definition_hash="1" * 64,
            calibration_cutoff_at=dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc),
            probability_report=report,
        )
        self.assertRegex(evidence.evidence_hash, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
