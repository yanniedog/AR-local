"""Strict, read-only validation for the preservation evidence locator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Optional

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parent
DEFAULT_EVIDENCE = ROOT / "docs" / "preservation" / "PRESERVATION_EVIDENCE_V1.json"
DEFAULT_SCHEMA = ROOT / "contracts" / "preservation-evidence-v1.schema.json"
PRESERVATION_ROOT = "<AUSTRALIANRATES_PRESERVATION_ROOT>"


def validate_evidence(
    evidence: Mapping[str, Any], schema: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate schema plus cross-field/keyed invariants JSON Schema cannot express."""

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(evidence)

    storage = evidence["storage"]
    retrieval = evidence["retrieval"]
    if storage["root_placeholder"] != PRESERVATION_ROOT:
        raise ValueError("storage.root_placeholder is not the preservation root token")
    if retrieval["required_root"] != storage["root_placeholder"]:
        raise ValueError("retrieval.required_root must equal storage.root_placeholder")
    if storage["snapshot_relative_path"] != evidence["snapshot_id"]:
        raise ValueError("storage.snapshot_relative_path must equal snapshot_id")

    manifest_paths = [str(item["path"]) for item in evidence["manifests"]]
    if len(manifest_paths) != len(set(manifest_paths)):
        raise ValueError("manifests must contain unique path values")
    inventory_path = str(retrieval["inventory_relative_path"])
    if manifest_paths.count(inventory_path) != 1:
        raise ValueError("inventory_relative_path must identify exactly one manifest")
    return dict(evidence)


def load_and_validate(
    evidence_path: Path = DEFAULT_EVIDENCE,
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict) or not isinstance(schema, dict):
        raise ValueError("preservation evidence and schema must be JSON objects")
    return validate_evidence(evidence, schema)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the off-repository preservation evidence locator."
    )
    parser.add_argument("validate", choices=("validate",))
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args(argv)
    evidence = load_and_validate(args.evidence, args.schema)
    print(
        json.dumps(
            {
                "ok": True,
                "snapshot_id": evidence["snapshot_id"],
                "manifest_count": len(evidence["manifests"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
