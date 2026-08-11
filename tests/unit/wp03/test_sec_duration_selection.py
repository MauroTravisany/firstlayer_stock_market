import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[3]
CUSTOM = ROOT / "cloud-functions" / "financial_data" / "custom_function"
PKG = types.ModuleType("custom_function")
PKG.__path__ = [str(CUSTOM)]
sys.modules.setdefault("custom_function", PKG)

pit_spec = importlib.util.spec_from_file_location("custom_function.point_in_time", CUSTOM / "point_in_time.py")
pit = importlib.util.module_from_spec(pit_spec)
sys.modules["custom_function.point_in_time"] = pit
pit_spec.loader.exec_module(pit)
sec_spec = importlib.util.spec_from_file_location("custom_function.sec_source", CUSTOM / "sec_source.py")
sec = importlib.util.module_from_spec(sec_spec)
sys.modules["custom_function.sec_source"] = sec
sec_spec.loader.exec_module(sec)


class SecDurationSelectionTests(unittest.TestCase):
    def test_quarter_fact_beats_ytd_fact_for_10q(self):
        facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            {"accn": "a", "start": "2026-01-01", "end": "2026-06-30", "filed": "2026-08-01", "fy": 2026, "fp": "Q2", "val": 220.0},
            {"accn": "a", "start": "2026-04-01", "end": "2026-06-30", "filed": "2026-08-01", "fy": 2026, "fp": "Q2", "frame": "CY2026Q2", "val": 120.0},
        ]}}}}}
        value, _unit, row = sec._choose_fact(
            facts, ["Revenues"], accession="a", period_end="2026-06-30",
            unit_preferences=["USD"], duration_target=91, require_duration=True,
        )
        self.assertEqual(120.0, value)
        self.assertEqual("2026-04-01", row["start"])

    def test_ytd_only_fact_is_rejected_as_quarter_value(self):
        facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            {"accn": "a", "start": "2026-01-01", "end": "2026-09-30", "filed": "2026-11-01", "fy": 2026, "fp": "Q3", "val": 350.0},
        ]}}}}}
        value, unit, row = sec._choose_fact(
            facts, ["Revenues"], accession="a", period_end="2026-09-30",
            unit_preferences=["USD"], duration_target=91, require_duration=True,
        )
        self.assertIsNone(value)
        self.assertIsNone(unit)
        self.assertIsNone(row)

    def test_compact_sec_timestamp_normalizes_to_utc(self):
        self.assertEqual("2026-05-02T13:30:00Z", pit.normalize_timestamp("20260502133000"))


if __name__ == "__main__":
    unittest.main()
