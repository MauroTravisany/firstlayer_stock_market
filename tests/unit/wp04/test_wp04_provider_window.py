import datetime as dt
from pathlib import Path
import subprocess
import sys
import unittest

from tools import wp04_backfill_core as core
from tools import wp04_provider_window as provider
from tools import wp04_shadow_backfill_windowed as windowed


ROOT = Path(__file__).resolve().parents[3]
UTC = dt.timezone.utc


def base_plan(**overrides):
    value = {
        "schema_version": 1,
        "operation": "WP04_SHADOW_BACKFILL",
        "git_sha": "b" * 40,
        "asset_set_version": "test-v1",
        "asset_set_sha256": "c" * 64,
        "assets": [{"ticker": "AAPL"}],
        "start_date": "2024-01-01",
        "end_date": "2026-08-16",
        "intraday_start_date": "2026-07-02",
        "hourly_start_date": "2025-08-16",
        "files": {},
        "total_row_count": 0,
        "max_rows": 100_000,
        "provider_versions": {"YAHOO": "test"},
        "production_change_allowed": False,
    }
    value.update(overrides)
    return core.finalize_plan(value)


class Wp04ProviderWindowTests(unittest.TestCase):
    def test_window_is_relative_to_current_provider_anchor(self):
        document = provider.resolve_provider_window(
            anchor_at=dt.datetime(2026, 8, 18, 12, tzinfo=UTC)
        )
        self.assertEqual("2026-08-16", document["end_date"])
        self.assertEqual("2026-07-02", document["intraday_start_date"])
        self.assertEqual("2025-08-16", document["hourly_start_date"])
        self.assertEqual(provider.POLICY_VERSION, document["policy_version"])
        self.assertEqual(58, document["intraday"]["safe_lookback_days"])
        self.assertEqual(728, document["hourly"]["safe_lookback_days"])
        self.assertTrue(document["intraday"]["within_provider_window"])
        self.assertTrue(document["hourly"]["within_provider_window"])
        self.assertRegex(document["window_checksum"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            document["window_checksum"],
            provider.verify_provider_window(document),
        )
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

    def test_provider_window_tampering_is_rejected(self):
        document = provider.resolve_provider_window(
            anchor_at=dt.datetime(2026, 8, 18, 12, tzinfo=UTC)
        )
        changed = dict(document)
        changed["intraday_start_date"] = "2026-06-16"
        with self.assertRaisesRegex(
            provider.ProviderWindowError,
            "checksum mismatch",
        ):
            provider.verify_provider_window(changed)

    def test_windowed_planner_passes_only_resolved_dates(self):
        captured = {}

        def fake_planner(**kwargs):
            captured.update(kwargs)
            return base_plan(
                git_sha=kwargs["git_sha"],
                start_date=kwargs["start_date"].isoformat(),
                end_date=kwargs["end_date"].isoformat(),
                intraday_start_date=kwargs["intraday_start_date"].isoformat(),
                hourly_start_date=kwargs["hourly_start_date"].isoformat(),
                max_rows=kwargs["max_rows"],
            )

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
        core.verify_plan_checksum(plan, plan["plan_checksum"])

    def test_legacy_plan_without_provider_policy_is_not_executable(self):
        plan = base_plan()
        with self.assertRaisesRegex(
            core.Wp04BackfillError,
            "provider_window_policy",
        ):
            core.verify_plan_checksum(plan, plan["plan_checksum"])

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
