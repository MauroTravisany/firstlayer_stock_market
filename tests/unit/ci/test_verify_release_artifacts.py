import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.ci import verify_release_artifacts


SHA = "a" * 40


class ReleaseArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.artifacts = self.root / "artifacts"
        self.inventory = self.root / "services.json"
        self.inventory.write_text(
            json.dumps([{"service": "stockdaily", "context": "cloud-functions/daily_stocks"}]),
            encoding="utf-8",
        )
        artifact = self.artifacts / f"cloud-run-image-stockdaily-{SHA}"
        artifact.mkdir(parents=True)
        archive = artifact / "image.tar.gz"
        archive.write_bytes(b"immutable image fixture")
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        (artifact / "image.tar.gz.sha256").write_text(
            f"{checksum}  image.tar.gz\n", encoding="utf-8"
        )
        (artifact / "metadata.json").write_text(
            json.dumps(
                {
                    "service": "stockdaily",
                    "context": "cloud-functions/daily_stocks",
                    "git_sha": SHA,
                    "local_image": f"wp01/stockdaily:{SHA}",
                    "image_id": "sha256:" + "b" * 64,
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_complete_exact_artifact_set_is_accepted(self):
        records = verify_release_artifacts.verify_artifacts(
            self.artifacts, self.inventory, SHA
        )
        self.assertEqual([record["service"] for record in records], ["stockdaily"])
        self.assertEqual(records[0]["git_sha"], SHA)

    def test_wrong_approved_sha_is_rejected(self):
        with self.assertRaises(verify_release_artifacts.ArtifactVerificationError):
            verify_release_artifacts.verify_artifacts(
                self.artifacts, self.inventory, "c" * 40
            )

    def test_tampered_archive_is_rejected(self):
        next(self.artifacts.rglob("image.tar.gz")).write_bytes(b"tampered")
        with self.assertRaises(verify_release_artifacts.ArtifactVerificationError):
            verify_release_artifacts.verify_artifacts(
                self.artifacts, self.inventory, SHA
            )

    def test_missing_inventory_service_is_rejected(self):
        self.inventory.write_text(
            json.dumps(
                [
                    {"service": "stockdaily", "context": "cloud-functions/daily_stocks"},
                    {"service": "stockfinancial", "context": "cloud-functions/financial_data"},
                ]
            ),
            encoding="utf-8",
        )
        with self.assertRaises(verify_release_artifacts.ArtifactVerificationError):
            verify_release_artifacts.verify_artifacts(
                self.artifacts, self.inventory, SHA
            )

    def test_loaded_image_id_matches_metadata(self):
        metadata = next(self.artifacts.rglob("metadata.json"))
        result = verify_release_artifacts.verify_loaded_image_id(
            metadata, "sha256:" + "b" * 64
        )
        self.assertEqual(result["status"], "PASS")

    def test_tampered_loaded_image_metadata_is_rejected(self):
        metadata = next(self.artifacts.rglob("metadata.json"))
        with self.assertRaises(verify_release_artifacts.ArtifactVerificationError):
            verify_release_artifacts.verify_loaded_image_id(
                metadata, "sha256:" + "c" * 64
            )


if __name__ == "__main__":
    unittest.main()
