import datetime as dt
import unittest

from packages.common import data_snapshots as snapshots


class SnapshotTests(unittest.TestCase):
    def record(self):
        return snapshots.build_snapshot_record(
            environment="shadow",
            data_contract_version="audit-contracts-v1",
            contract_set_hash="a" * 64,
            schema_snapshot_hash="b" * 64,
            source_cutoff_at=dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc),
            source_manifest={
                "tables": [
                    {
                        "name": "prices",
                        "partition": "2026-08-10",
                        "content_sha256": "c" * 64,
                    }
                ]
            },
            created_by="unit-test",
            created_at=dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc),
        )

    def test_same_content_produces_same_snapshot_identity(self):
        self.assertEqual(
            self.record()["data_snapshot_id"], self.record()["data_snapshot_id"]
        )

    def test_publish_requires_quality_pass_and_becomes_immutable(self):
        published = snapshots.publish_snapshot(
            self.record(),
            {"status": "PASS", "checks": []},
            published_at=dt.datetime(2026, 8, 11, tzinfo=dt.timezone.utc),
        )
        snapshots.assert_publishable(published)
        self.assertTrue(published["immutable"])

    def test_tampered_source_identity_is_rejected(self):
        record = self.record()
        record["source_manifest_hash"] = "f" * 64
        self.assertIn(
            "SOURCE_MANIFEST_HASH_MISMATCH", snapshots.validate_identity(record)
        )

    def test_well_formed_but_tampered_content_checksum_is_rejected(self):
        record = self.record()
        record["content_checksum"] = "f" * 64
        self.assertIn(
            "CONTENT_CHECKSUM_MISMATCH", snapshots.validate_identity(record)
        )

    def test_source_manifest_requires_unique_content_hashes(self):
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.build_snapshot_record(
                environment="shadow",
                data_contract_version="audit-contracts-v1",
                contract_set_hash="a" * 64,
                schema_snapshot_hash="b" * 64,
                source_cutoff_at=dt.datetime(
                    2026, 8, 10, tzinfo=dt.timezone.utc
                ),
                source_manifest={
                    "tables": [
                        {
                            "name": "prices",
                            "partition": "2026-08-10",
                            "content_sha256": "bad",
                        }
                    ]
                },
                created_by="unit-test",
            )

    def test_source_manifest_order_is_canonical(self):
        common = dict(
            environment="shadow",
            data_contract_version="audit-contracts-v1",
            contract_set_hash="a" * 64,
            schema_snapshot_hash="b" * 64,
            source_cutoff_at=dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc),
            created_by="unit-test",
            created_at=dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc),
        )
        left = snapshots.build_snapshot_record(
            **common,
            source_manifest={
                "tables": [
                    {"name": "prices", "content_sha256": "c" * 64},
                    {"name": "financials", "content_sha256": "d" * 64},
                ]
            },
        )
        right = snapshots.build_snapshot_record(
            **common,
            source_manifest={
                "tables": [
                    {"name": "financials", "content_sha256": "d" * 64},
                    {"name": "prices", "content_sha256": "c" * 64},
                ]
            },
        )
        self.assertEqual(left["data_snapshot_id"], right["data_snapshot_id"])
        self.assertEqual(left["source_manifest_hash"], right["source_manifest_hash"])

    def test_source_manifest_requires_checksums_and_unique_identities(self):
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.build_snapshot_record(
                environment="shadow",
                data_contract_version="audit-contracts-v1",
                contract_set_hash="a" * 64,
                schema_snapshot_hash="b" * 64,
                source_cutoff_at=dt.datetime(
                    2026, 8, 10, tzinfo=dt.timezone.utc
                ),
                source_manifest={"tables": [{"name": "prices"}]},
                created_by="unit-test",
            )

    def test_failed_quality_gate_cannot_publish(self):
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.publish_snapshot(self.record(), {"status": "FAIL"})
