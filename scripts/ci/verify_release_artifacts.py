"""Verify immutable CI image artifacts against an approved git SHA."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


class ArtifactVerificationError(RuntimeError):
    """Artifact provenance or integrity could not be proven."""


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactVerificationError(f"invalid JSON: {path}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifacts(artifacts_dir: Path, inventory_path: Path, approved_sha: str):
    if not GIT_SHA.fullmatch(approved_sha):
        raise ArtifactVerificationError("approved SHA must contain exactly 40 lowercase hex characters")

    inventory = _load_json(inventory_path)
    if not isinstance(inventory, list) or not inventory:
        raise ArtifactVerificationError("service inventory must be a non-empty list")
    expected = {}
    for row in inventory:
        if not isinstance(row, dict) or set(row) != {"service", "context"}:
            raise ArtifactVerificationError("service inventory rows require service and context")
        service = row["service"]
        if service in expected:
            raise ArtifactVerificationError(f"duplicate service in inventory: {service}")
        expected[service] = row["context"]

    records = {}
    for metadata_path in sorted(artifacts_dir.rglob("metadata.json")):
        metadata = _load_json(metadata_path)
        service = metadata.get("service")
        if service not in expected:
            raise ArtifactVerificationError(f"unexpected service artifact: {service}")
        if service in records:
            raise ArtifactVerificationError(f"duplicate service artifact: {service}")
        if metadata.get("git_sha") != approved_sha:
            raise ArtifactVerificationError(f"git SHA mismatch for {service}")
        if metadata.get("context") != expected[service]:
            raise ArtifactVerificationError(f"build context mismatch for {service}")
        if metadata.get("local_image") != f"wp01/{service}:{approved_sha}":
            raise ArtifactVerificationError(f"local image identity mismatch for {service}")
        if not IMAGE_ID.fullmatch(str(metadata.get("image_id", ""))):
            raise ArtifactVerificationError(f"invalid image ID for {service}")

        artifact_dir = metadata_path.parent
        archive = artifact_dir / "image.tar.gz"
        checksum_file = artifact_dir / "image.tar.gz.sha256"
        if not archive.is_file() or not checksum_file.is_file():
            raise ArtifactVerificationError(f"archive or checksum missing for {service}")
        expected_checksum = checksum_file.read_text(encoding="utf-8").split()[0]
        if not re.fullmatch(r"[0-9a-f]{64}", expected_checksum):
            raise ArtifactVerificationError(f"invalid checksum record for {service}")
        actual_checksum = _sha256(archive)
        if actual_checksum != expected_checksum:
            raise ArtifactVerificationError(f"archive checksum mismatch for {service}")

        records[service] = {
            **metadata,
            "archive": archive.as_posix(),
            "archive_checksum": actual_checksum,
        }

    missing = sorted(set(expected) - set(records))
    if missing:
        raise ArtifactVerificationError(f"missing service artifacts: {', '.join(missing)}")
    return [records[service] for service in sorted(records)]


def verify_loaded_image_id(metadata_path: Path, actual_image_id: str):
    metadata = _load_json(Path(metadata_path))
    expected = str(metadata.get("image_id", ""))
    if not IMAGE_ID.fullmatch(actual_image_id):
        raise ArtifactVerificationError("loaded image ID is not a valid sha256 image ID")
    if actual_image_id != expected:
        raise ArtifactVerificationError("loaded image ID does not match immutable metadata")
    return {
        "status": "PASS",
        "service": metadata.get("service"),
        "image_id": actual_image_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--approved-sha")
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--actual-image-id")
    args = parser.parse_args()
    try:
        if args.metadata or args.actual_image_id:
            if not args.metadata or not args.actual_image_id:
                raise ArtifactVerificationError(
                    "--metadata and --actual-image-id must be provided together"
                )
            result = verify_loaded_image_id(args.metadata, args.actual_image_id)
            print(json.dumps(result, sort_keys=True))
            return 0
        if not args.artifacts or not args.inventory or not args.approved_sha:
            raise ArtifactVerificationError(
                "artifact mode requires --artifacts, --inventory and --approved-sha"
            )
        records = verify_artifacts(args.artifacts, args.inventory, args.approved_sha)
    except ArtifactVerificationError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": "PASS",
                "approved_sha": args.approved_sha,
                "services": [record["service"] for record in records],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
