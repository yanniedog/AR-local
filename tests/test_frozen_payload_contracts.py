from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "contracts/v3"


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_frozen_payload_schemas_remain_valid() -> None:
    paths = [
        ROOT / "contracts/app-insight-assets.schema.json",
        ROOT / "contracts/app-payload-v2.schema.json",
        *sorted(V3.glob("*.schema.json")),
    ]
    assert len(paths) == 7
    for path in paths:
        schema = _json(path)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)


def test_frozen_v3_schema_set_matches_immutable_lock() -> None:
    lock = _json(V3 / "contract-lock.json")
    names = sorted(path.name for path in V3.glob("*.schema.json"))
    assert lock["schemas"] == names
    schemas = {name: _json(V3 / name) for name in names}
    canonical = json.dumps(
        schemas,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == lock["schema_set_sha256"]
