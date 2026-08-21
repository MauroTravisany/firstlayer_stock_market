import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from tools import wp04_primary_source_quality as quality

UTC = dt.timezone.utc

class FakeIndex:
    def __init__(self, timezone): self.tz = timezone
class FakeFrame:
    def __init__(self, rows, timezone): self.index = FakeIndex(timezone); self._rows = rows
    def iterrows(self): yield from self._rows

def row():
    return {"Open":900,"High":902,"Low":898,"Close":901,"Adj Close":901,"Volume":1000}

def normalizer(payload, **kwargs):
    return {"raw_revision_id": f"{kwargs['ticker']}:{payload['timestamp'].isoformat()}"}

class Wp04DailyProviderDateTests(unittest.TestCase):
    def test_bst_monday_daily_fx_remains_monday(self):
        london = ZoneInfo("Europe/London")
        frame = FakeFrame([(dt.datetime(2024, 7, 8, 0, 0, tzinfo=london), row())], london)
        accepted, status, rejected = quality.normalize_yahoo_frame(frame, provider_symbol="CLP=X", ticker="CLP=X", asset_type="FX", exchange="FX_24_5", source_interval="1d", currency="CLP", ingestion_run_id="run-test", source_version="test", ingested_at=dt.datetime(2026, 8, 20, tzinfo=UTC), normalizer=normalizer)
        self.assertEqual(1, len(accepted))
        self.assertEqual([], rejected)
        self.assertEqual(0, status["off_session_row_count"])

if __name__ == "__main__": unittest.main()
