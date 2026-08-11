"""Validate machine-readable contracts, implementations, and frozen manifests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.common.data_contracts import (
    ContractError,
    contract_summary,
    load_contract_directory,
    manifest_document,
    validate_implementation,
)


def runtime_manifest_document(manifest: dict) -> dict:
    return {
        "data_contract_version": manifest["data_contract_version"],
        "contract_set_hash": manifest["contract_set_hash"],
        "schema_snapshot_hash": manifest["schema_snapshot_hash"],
    }


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON manifest {path}: {exc}") from exc


def _write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run(
    repo_root: Path,
    contracts_dir: Path,
    *,
    manifest_path: Path | None = None,
    runtime_manifest_path: Path | None = None,
    write_manifest: bool = False,
    write_runtime_manifest: bool = False,
    validate_implementations: bool = True,
) -> int:
    try:
        contract_set = load_contract_directory(contracts_dir)
        problems: list[str] = []
        if validate_implementations:
            for contract in contract_set.contracts:
                problems.extend(validate_implementation(contract, repo_root))

        manifest = manifest_document(contract_set)
        if manifest_path:
            if write_manifest:
                _write_json(manifest_path, manifest)
            elif not manifest_path.is_file():
                problems.append(f"MISSING_CONTRACT_MANIFEST:{manifest_path}")
            elif _load_json(manifest_path) != manifest:
                problems.append("STALE_CONTRACT_MANIFEST")

        runtime_manifest = runtime_manifest_document(manifest)
        if runtime_manifest_path:
            if write_runtime_manifest:
                _write_json(runtime_manifest_path, runtime_manifest)
            elif not runtime_manifest_path.is_file():
                problems.append(
                    f"MISSING_RUNTIME_CONTRACT_MANIFEST:{runtime_manifest_path}"
                )
            elif _load_json(runtime_manifest_path) != runtime_manifest:
                problems.append("STALE_RUNTIME_CONTRACT_MANIFEST")

        if problems:
            print(
                json.dumps(
                    {"status": "FAIL", "problems": sorted(set(problems))},
                    sort_keys=True,
                )
            )
            return 2
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 2

    result = json.loads(contract_summary(contract_set))
    result.update(
        {
            "manifest": manifest_path.as_posix() if manifest_path else None,
            "runtime_manifest": (
                runtime_manifest_path.as_posix() if runtime_manifest_path else None
            ),
        }
    )
    print(json.dumps(result, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--contracts-dir", type=Path)
    parser.add_argument(
        "--manifest", type=Path, default=Path("contracts/manifest.json")
    )
    parser.add_argument(
        "--runtime-manifest",
        type=Path,
        default=Path("cloud-functions/strategy_brain/contract_set_manifest.json"),
    )
    parser.add_argument("--write-manifest", action="store_true")
    parser.add_argument("--write-runtime-manifest", action="store_true")
    parser.add_argument("--skip-implementation-validation", action="store_true")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    contracts = (args.contracts_dir or root / "contracts").resolve()
    manifest = args.manifest if args.manifest.is_absolute() else root / args.manifest
    runtime = (
        args.runtime_manifest
        if args.runtime_manifest.is_absolute()
        else root / args.runtime_manifest
    )
    return run(
        root,
        contracts,
        manifest_path=manifest,
        runtime_manifest_path=runtime,
        write_manifest=args.write_manifest,
        write_runtime_manifest=args.write_runtime_manifest,
        validate_implementations=not args.skip_implementation_validation,
    )


if __name__ == "__main__":
    raise SystemExit(main())
