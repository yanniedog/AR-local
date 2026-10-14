"""Wire, identity and complexity validation before interpreting public programmes."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from .public_pricing import canonical_bytes, decimal_value

SCHEMA = Path(__file__).resolve().parents[1] / "contracts/public_rates/public-rate-catalogue-v1.schema.json"


@lru_cache(maxsize=16)
def _validator(kind: str):
    schema = json.loads(SCHEMA.read_bytes())
    return Draft202012Validator({"$ref": f"#/$defs/{kind}", "$defs": schema["$defs"]},
                               format_checker=FormatChecker())


def validate_wire(value: Any, kind: str) -> None:
    _validator(kind).validate(value)


def _formula_budget(formula: Any, depth: int = 0, counter: list | None = None) -> None:
    counter = counter if counter is not None else [0]
    counter[0] += 1
    if depth > 16 or counter[0] > 256 or not isinstance(formula, Mapping):
        raise ValueError("formula_budget_exceeded")
    for field in ("formula", "minimum", "maximum"):
        if isinstance(formula.get(field), Mapping):
            _formula_budget(formula[field], depth + 1, counter)
    for field in ("operands", "choices", "tiers"):
        for child in formula.get(field, []):
            _formula_budget(child.get("formula") if field != "operands" else child, depth + 1, counter)


def validate_programme(programme: Mapping[str, Any]) -> None:
    if len(canonical_bytes(programme)) > 256 * 1024:
        raise ValueError("programme_byte_budget_exceeded")
    if programme.get("formula") is not None:
        _formula_budget(programme["formula"])
    for phase in programme.get("phases", []):
        _formula_budget(phase["formula"])
    validate_wire(programme, "Programme")
    identities = [item["componentId"] for item in programme["components"]]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate_component_identity")
    for condition in programme["conditions"]:
        if "minimum" in condition and "maximum" in condition:
            if decimal_value(condition["minimum"]) > decimal_value(condition["maximum"]):
                raise ValueError("invalid_condition_bounds")
    phases = sorted(programme.get("phases", []), key=lambda phase: phase["startMonth"])
    for index, phase in enumerate(phases):
        end = phase.get("endMonth")
        if end is not None and end <= phase["startMonth"]:
            raise ValueError("invalid_phase_interval")
        if index and phases[index - 1].get("endMonth", 10 ** 9) > phase["startMonth"]:
            raise ValueError("overlapping_phases")
