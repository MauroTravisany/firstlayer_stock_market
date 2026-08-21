import datetime as dt
import unittest

from tools import wp04_bcch_fx_source as source

UTC = dt.timezone.utc

class FakeResponse:
    def __init__(self, document, status_code=200): self._document = document; self.status_code = status_code
    def json(self): return self._document

def document(observations, code=0, series_id=source.SERIES_ID):
    return {"Codigo": code, "Descripcion": "Success" if code == 0 else "Failure", "Series": {"seriesId": series_id, "Obs": observations}, "SeriesInfos": []}

class Wp04BcchFxSourceTests(unittest.TestCase):
    def test_official_rows_are_scalar_reference_rates_and_token_is_not_persisted(self):
        captured = {}
        def fake_get(*_args, **kwargs):
            captured.update(kwargs)
            return FakeResponse(document([
                {"indexDateString":"01-10-2024","value":"897.68","statusCode":"OK"},
                {"indexDateString":"05-10-2024","value":"","statusCode":"ND"},
                {"indexDateString":"07-10-2024","value":"923.74","statusCode":"OK"},
            ]))
        rows, status = source.fetch_bcch_observed_dollar(token="secret-value", start_date=dt.date(2024,10,1), end_date=dt.date(2024,10,7), ingestion_run_id="run-test", ingested_at=dt.datetime(2024,10,9,12,tzinfo=UTC), get=fake_get)
        self.assertEqual(2, len(rows))
        self.assertEqual("secret-value", captured["params"]["token"])
        first = rows[0]
        self.assertEqual("BCCH_BDE", first["provider"])
        self.assertEqual("RAW_REFERENCE_RATE_VALIDATED", first["quality_status"])
        self.assertEqual(897.68, first["adjusted_close"])
        for field in ("open","high","low","close","volume"):
            self.assertIsNone(first[field])
        self.assertEqual(first["bar_end"], first["available_at"])
        self.assertEqual({"ND":1}, status["skipped_status_counts"])
        self.assertFalse(status["token_persisted"])
        self.assertNotIn("secret-value", str(rows) + str(status))

    def test_same_observation_has_stable_revision_across_runs(self):
        payload = document([{"indexDateString":"01-10-2024","value":"897.68","statusCode":"OK"}])
        get = lambda *_args, **_kwargs: FakeResponse(payload)
        kwargs = dict(token="secret", start_date=dt.date(2024,10,1), end_date=dt.date(2024,10,1), ingested_at=dt.datetime(2024,10,3,tzinfo=UTC), get=get)
        first, _ = source.fetch_bcch_observed_dollar(ingestion_run_id="one", **kwargs)
        second, _ = source.fetch_bcch_observed_dollar(ingestion_run_id="two", **kwargs)
        self.assertEqual(first[0]["raw_revision_id"], second[0]["raw_revision_id"])
        self.assertEqual(first[0]["payload_hash"], second[0]["payload_hash"])

    def test_missing_token_fails_before_network(self):
        with self.assertRaisesRegex(source.BcchFxSourceError, "BCCH_API_TOKEN"):
            source.fetch_bcch_observed_dollar(token=None, start_date=dt.date(2024,1,1), end_date=dt.date(2024,1,2), ingestion_run_id="run", ingested_at=dt.datetime(2024,1,4,tzinfo=UTC), get=lambda *_a, **_k: self.fail("network called"))

    def test_bad_values_and_duplicate_dates_fail_closed(self):
        cases = [
            (document([], code=5), "non-success"),
            (document([{"indexDateString":"01-10-2024","value":"-1","statusCode":"OK"}]), "non-positive"),
            (document([{"indexDateString":"01-10-2024","value":"900","statusCode":"OK"},{"indexDateString":"01-10-2024","value":"901","statusCode":"OK"}]), "duplicate"),
        ]
        for payload, expected in cases:
            with self.subTest(expected=expected), self.assertRaisesRegex(source.BcchFxSourceError, expected):
                source.fetch_bcch_observed_dollar(token="secret", start_date=dt.date(2024,10,1), end_date=dt.date(2024,10,2), ingestion_run_id="run", ingested_at=dt.datetime(2024,10,4,tzinfo=UTC), get=lambda *_a, _payload=payload, **_k: FakeResponse(_payload))

if __name__ == "__main__": unittest.main()
