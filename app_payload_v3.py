"""Build a dormant payload-v3 candidate from local canonical entity files only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from cdr_domain.contract_validation import validate_contract
from cdr_domain.deserialize import canonical_product_from_primitive
from cdr_domain.generation import (
    GenerationInputs,
    build_generation_candidate,
    write_generation_candidate,
)
from cdr_domain.validate import validate_canonical_product


class DuplicateInputKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise DuplicateInputKeyError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _load_local_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be readable UTF-8 JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def build_local_candidate(
    entities_path: Path,
    metadata_path: Path,
    output_root: Path,
) -> tuple[Path, dict[str, str]]:
    entity_document = _load_local_object(entities_path, "canonical entities")
    validate_contract("canonical-core-v3.schema.json", entity_document)
    products = []
    for value in entity_document["products"]:
        product = canonical_product_from_primitive(value)
        validate_canonical_product(product)
        products.append(product)

    metadata = _load_local_object(metadata_path, "generation metadata")
    inputs = GenerationInputs.from_mapping(metadata)
    if entity_document["observation_date"] != inputs.observation_date:
        raise ValueError("entity and metadata observation dates disagree")
    if entity_document["normalization_version"] != inputs.normalization_version:
        raise ValueError("entity and metadata normalization versions disagree")

    candidate = build_generation_candidate(products, inputs)
    directory = write_generation_candidate(candidate, output_root)
    return directory, {
        "generation_id": candidate.generation_id,
        "manifest_sha256": candidate.manifest_sha256,
        "core_sha256": candidate.core.sha256,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build an unpublished payload-v3 candidate from local canonical JSON. "
            "This command performs no network or pointer operation."
        )
    )
    parser.add_argument("--entities", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    directory, summary = build_local_candidate(
        arguments.entities,
        arguments.metadata,
        arguments.output_root,
    )
    print(
        json.dumps(
            {**summary, "candidate_directory": str(directory)},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
