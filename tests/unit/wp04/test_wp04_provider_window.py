import datetime as dt
from pathlib import Path
import subprocess
import sys
import unittest

from tools import wp04_provider_window as provider
from tools import wp04_shadow_backfill_windowed as windowed


ROOT = Path(__file__).resolve().parents[3]
UTC = dt.timezone.utc


class Wp04ProviderWindowTests(unittest.TestCase):
    def test_window_is_relative_to_current_provider_anchor(self):
        document = provider.resolve_provider_window(
            anchor_at=dt.datetime(2026, 8, 18, 12, tzinfo=UTC)
        )
        self.assertEqual("2026-08-16", document["end_date"])
        self.assertEqual("2026-07-02", document["intraday_start_date"])
        self.assertEqual("2025-08-16", document["hourly_start_date"])
        self.assertEqual(provider.POLICY_VERSION, document["policy_version"])
        self.assertTrue(document["intraday"]["within_provider_window"])
        self.assertTrue(document["hourly"]["within_provider_window"])
        self.assertRegex(document["window_checksum"], r"^[0-9a-f]{64}$")
        self.assertFalse(document["production_change_allowed"])

    def test_unsafe_lookbacks_fail_closed(self):
        with self.assertRaisesRegex(
            provider.ProviderWindowError,
            "15m window",
        ):
            provider.resolve_provider_window(
                anchor_at=dt.datetime(2026, 8, 18, tzinfo=UTC),
                intraday_lookback_days=59,
            )
        with self.assertRaisesRegex(
            provider.ProviderWindowError,
            "1h window",
        ):
            provider.resolve_provider_window(
                anchor_at=dt.datetime(2026, 8, 18, tzinfo=UTC),
                hourly_lookback_days=729,
            )

    def test_windowed_planner_passes_only_resolved_dates(self):
        captured = {}

        def fake_planner(**kwargs):
            captured.update(kwargs)
            return {
                "operation": "WP04_SHADOW_BACKFILL",
                "plan_checksum": "a" * 64,
                "production_change_allowed": False,
            }

        plan, window = windowed.build_windowed_plan(
            git_sha="b" * 40,
            asset_set_path=Path("assets.json"),
            tickers=None,
            daily_start_date=dt.date(2024, 1, 1),
            end_lag_days=2,
            intraday_lookback_days=45,
            hourly_lookback_days=365,
            max_rows=100_000,
            work_dir=Path("/tmp/wp04-test"),
            timeout_seconds=30,
            anchor_at=dt.datetime(2026, 8, 18, 12, tzinfo=UTC),
            planner=fake_planner,
        )
        self.assertEqual(dt.date(2026, 8, 16), captured["end_date"])
        self.assertEqual(
            dt.date(2026, 7, 2),
            captured["intraday_start_date"],
        )
        self.assertEqual(
            dt.date(2025, 8, 16),
            captured["hourly_start_date"],
        )
        self.assertEqual(
            window["window_checksum"],
            plan["provider_window_checksum"],
        )
        self.assertEqual(window, plan["provider_window_policy"])

    def test_cli_entrypoints_are_available(self):
        for path in (
            ROOT / "tools" / "wp04_provider_window.py",
            ROOT / "tools" / "wp04_shadow_backfill_windowed.py",
        ):
            result = subprocess.run(
                [sys.executable, str(path), "--help"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()