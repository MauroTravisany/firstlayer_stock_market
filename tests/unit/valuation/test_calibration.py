import unittest

from packages.valuation.calibration import (
    IntervalForecast,
    ProbabilityForecast,
    apply_conformal_interval,
    conformal_absolute_error,
    interval_calibration_report,
    probability_calibration_report,
)
from packages.valuation.models import ValuationError


class CalibrationTests(unittest.TestCase):
    def test_perfect_probability_calibration(self):
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
        report = probability_calibration_report(
            forecasts, bins=10, min_samples=100
        )
        self.assertEqual("PASS", report.status)
        self.assertAlmostEqual(0.0, report.expected_calibration_error)
        self.assertLess(report.brier_score, 0.25)
        self.assertEqual(500, report.sample_size)

    def test_overconfident_forecasts_fail(self):
        forecasts = [
            ProbabilityForecast(0.99, index % 2 == 0)
            for index in range(200)
        ]
        report = probability_calibration_report(
            forecasts,
            min_samples=100,
            max_ece=0.10,
            max_brier=0.25,
        )
        self.assertEqual("FAIL", report.status)
        self.assertIn(
            "EXPECTED_CALIBRATION_ERROR_TOO_HIGH", report.reason_codes
        )
        self.assertIn("BRIER_SCORE_TOO_HIGH", report.reason_codes)

    def test_small_sample_is_insufficient_not_pass(self):
        report = probability_calibration_report(
            [ProbabilityForecast(0.7, True) for _ in range(10)],
            min_samples=100,
        )
        self.assertEqual("INSUFFICIENT", report.status)
        self.assertIn(
            "CALIBRATION_SAMPLE_TOO_SMALL", report.reason_codes
        )

    def test_interval_coverage_report(self):
        forecasts = [
            IntervalForecast(90, 110, 100) for _ in range(80)
        ] + [
            IntervalForecast(90, 110, 120) for _ in range(20)
        ]
        report = interval_calibration_report(
            forecasts,
            target_coverage=0.80,
            min_samples=100,
            tolerance=0.01,
        )
        self.assertEqual("PASS", report.status)
        self.assertAlmostEqual(0.80, report.empirical_coverage)
        self.assertAlmostEqual(20.0, report.mean_interval_width)

    def test_conformal_error_and_interval(self):
        residual = conformal_absolute_error(
            realized=[100, 102, 98, 110, 90],
            predicted_median=[100, 100, 100, 100, 100],
            coverage=0.80,
        )
        self.assertEqual(10.0, residual)
        lower, upper = apply_conformal_interval(
            median=100,
            raw_lower=95,
            raw_upper=105,
            absolute_error=residual,
        )
        self.assertEqual((90, 110), (lower, upper))

    def test_invalid_intervals_fail_closed(self):
        with self.assertRaisesRegex(ValuationError, "lower"):
            IntervalForecast(110, 90, 100)
        with self.assertRaisesRegex(ValuationError, "contain the median"):
            apply_conformal_interval(
                median=100,
                raw_lower=101,
                raw_upper=110,
                absolute_error=5,
            )


if __name__ == "__main__":
    unittest.main()
